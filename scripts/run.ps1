# Starts all four components, each in its own window so the logs stay visible.
#
#   powershell -ExecutionPolicy Bypass -File scripts\run.ps1
#
# Ports default to 8090 функциональный модуль, 8081 модуль работы с БД,
# 8000 бэкенд, 5173 фронтенд. If another program already holds one of them,
# override it — the components are told about each other automatically:
#
#   powershell -ExecutionPolicy Bypass -File scripts\run.ps1 -BackendPort 8200

param(
    [int]$EnginePort = 8090,
    [int]$DbPort = 8081,
    [int]$BackendPort = 8000,
    [int]$FrontendPort = 5173
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

function Get-PortOwner($port) {
    $owner = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique | Select-Object -First 1
    if (-not $owner) { return $null }
    return (Get-Process -Id $owner -ErrorAction SilentlyContinue)
}

$busy = $false
foreach ($item in @(
    @{ Port = $EnginePort;   Flag = "-EnginePort" },
    @{ Port = $DbPort;       Flag = "-DbPort" },
    @{ Port = $BackendPort;  Flag = "-BackendPort" },
    @{ Port = $FrontendPort; Flag = "-FrontendPort" }
)) {
    $owner = Get-PortOwner $item.Port
    if ($owner) {
        Write-Host "Порт $($item.Port) занят процессом $($owner.ProcessName) (PID $($owner.Id))" -ForegroundColor Yellow
        Write-Host "  освободить:  powershell -ExecutionPolicy Bypass -File scripts\stop.ps1" -ForegroundColor Yellow
        Write-Host "  или взять другой порт:  ... run.ps1 $($item.Flag) $($item.Port + 100)" -ForegroundColor Yellow
        $busy = $true
    }
}
if ($busy) { exit 1 }

if (-not (Test-Path "$root\prediction-engine\prediction-engine.exe")) {
    Write-Host "Не найден prediction-engine.exe — сначала выполните scripts\setup.ps1" -ForegroundColor Red
    exit 1
}

function Start-Component($title, $workDir, $command) {
    Start-Process powershell -ArgumentList @(
        "-NoExit", "-Command",
        "`$host.UI.RawUI.WindowTitle = '$title'; Set-Location '$workDir'; $command"
    ) | Out-Null
    Write-Host "[запущен] $title" -ForegroundColor Green
}

Start-Component "1. Функциональный модуль (Go, :$EnginePort)" "$root\prediction-engine" `
    "`$env:PORT = '$EnginePort'; .\prediction-engine.exe"

Start-Component "2. Модуль работы с БД (:$DbPort)" "$root\db-service" `
    ".\.venv\Scripts\python.exe -m uvicorn app.main:app --port $DbPort"

Start-Sleep -Seconds 2

# The backend finds the other two services through these variables, so a
# non-default port stays consistent across the whole комплекс.
Start-Component "3. Бэкенд (:$BackendPort)" "$root\backend" `
    ("`$env:APP_DB_SERVICE_URL = 'http://localhost:$DbPort'; " +
     "`$env:APP_PREDICTION_ENGINE_URL = 'http://localhost:$EnginePort'; " +
     ".\.venv\Scripts\python.exe -m uvicorn app.main:app --port $BackendPort")

Start-Component "4. Фронтенд (:$FrontendPort)" "$root\frontend" `
    ("`$env:VITE_API_BASE = 'http://localhost:$BackendPort'; " +
     "npm run dev -- --port $FrontendPort")

Write-Host "`nОжидание готовности сервисов..." -ForegroundColor Cyan
Start-Sleep -Seconds 6

foreach ($check in @(
    @{ Name = "Функциональный модуль"; Url = "http://localhost:$EnginePort/health" },
    @{ Name = "Модуль работы с БД";   Url = "http://localhost:$DbPort/health" },
    @{ Name = "Бэкенд";               Url = "http://localhost:$BackendPort/health" }
)) {
    try {
        Invoke-RestMethod -Uri $check.Url -TimeoutSec 5 | Out-Null
        Write-Host "[ok] $($check.Name)" -ForegroundColor Green
    } catch {
        Write-Host "[!]  $($check.Name) не отвечает — посмотрите его окно" -ForegroundColor Red
    }
}

Write-Host "`nПриложение: http://localhost:$FrontendPort" -ForegroundColor Cyan
Write-Host "Если база пустая, войдите и нажмите «Обновить данные и пересчитать рейтинги»." -ForegroundColor Cyan

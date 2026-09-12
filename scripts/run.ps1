# Starts all four components, each in its own window so the logs stay visible.
#
#   powershell -ExecutionPolicy Bypass -File scripts\run.ps1
#
# Ports: 8090 функциональный модуль, 8081 модуль работы с БД,
#        8000 бэкенд, 5173 фронтенд.

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

function Test-Port($port) {
    $null -ne (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
}

foreach ($port in 8090, 8081, 8000, 5173) {
    if (Test-Port $port) {
        Write-Host "Порт $port уже занят — возможно, сервис уже запущен." -ForegroundColor Yellow
        Write-Host "Освободить все порты: .\scripts\stop.ps1" -ForegroundColor Yellow
        exit 1
    }
}

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

Start-Component "1. Функциональный модуль (Go, :8090)" "$root\prediction-engine" `
    "`$env:PORT = '8090'; .\prediction-engine.exe"

Start-Component "2. Модуль работы с БД (:8081)" "$root\db-service" `
    ".\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8081"

Start-Sleep -Seconds 2

Start-Component "3. Бэкенд (:8000)" "$root\backend" `
    ".\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000"

Start-Component "4. Фронтенд (:5173)" "$root\frontend" `
    "npm run dev"

Write-Host "`nОжидание готовности сервисов..." -ForegroundColor Cyan
Start-Sleep -Seconds 6

foreach ($check in @(
    @{ Name = "Функциональный модуль"; Url = "http://localhost:8090/health" },
    @{ Name = "Модуль работы с БД";   Url = "http://localhost:8081/health" },
    @{ Name = "Бэкенд";               Url = "http://localhost:8000/health" }
)) {
    try {
        Invoke-RestMethod -Uri $check.Url -TimeoutSec 5 | Out-Null
        Write-Host "[ok] $($check.Name)" -ForegroundColor Green
    } catch {
        Write-Host "[!]  $($check.Name) не отвечает — посмотрите его окно" -ForegroundColor Red
    }
}

Write-Host "`nПриложение: http://localhost:5173" -ForegroundColor Cyan
Write-Host "Если база пустая, войдите и нажмите «Обновить данные и пересчитать рейтинги»." -ForegroundColor Cyan

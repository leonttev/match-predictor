# Prepares the project on a fresh Windows machine: checks the toolchains,
# creates the Python virtual environments, installs dependencies and builds
# the Go module.
#
#   powershell -ExecutionPolicy Bypass -File scripts\setup.ps1

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

function Test-Tool($command, $name, $wingetId) {
    $found = Get-Command $command -ErrorAction SilentlyContinue
    if ($found) {
        Write-Host "[ok]   $name найден" -ForegroundColor Green
        return $true
    }
    Write-Host "[!]    $name не найден. Установить командой:" -ForegroundColor Yellow
    Write-Host "         winget install --id $wingetId -e" -ForegroundColor Yellow
    return $false
}

Write-Host "`n=== Проверка инструментов ===" -ForegroundColor Cyan
$ok = $true
if (-not (Test-Tool "python" "Python 3.12+" "Python.Python.3.12")) { $ok = $false }
if (-not (Test-Tool "go" "Go 1.22+" "GoLang.Go")) { $ok = $false }
if (-not (Test-Tool "node" "Node.js 20+" "OpenJS.NodeJS.LTS")) { $ok = $false }

if (-not $ok) {
    Write-Host "`nУстановите отсутствующие инструменты, откройте новое окно PowerShell и запустите скрипт снова." -ForegroundColor Red
    exit 1
}

Write-Host "`n=== Функциональный модуль (Go) ===" -ForegroundColor Cyan
Push-Location "$root\prediction-engine"
go build -o prediction-engine.exe .
if ($LASTEXITCODE -ne 0) { Pop-Location; throw "Сборка Go-модуля не удалась" }
Write-Host "[ok]   prediction-engine.exe собран" -ForegroundColor Green
Pop-Location

foreach ($service in @("db-service", "backend")) {
    Write-Host "`n=== $service (Python) ===" -ForegroundColor Cyan
    Push-Location "$root\$service"
    if (-not (Test-Path ".venv")) {
        python -m venv .venv
        Write-Host "[ok]   виртуальное окружение создано" -ForegroundColor Green
    }
    & ".\.venv\Scripts\python.exe" -m pip install --upgrade pip --quiet
    & ".\.venv\Scripts\python.exe" -m pip install -r requirements.txt --quiet
    if ($LASTEXITCODE -ne 0) { Pop-Location; throw "Установка зависимостей $service не удалась" }
    Write-Host "[ok]   зависимости установлены" -ForegroundColor Green
    Pop-Location
}

Write-Host "`n=== Фронтенд (Node) ===" -ForegroundColor Cyan
Push-Location "$root\frontend"
npm install --silent
if ($LASTEXITCODE -ne 0) { Pop-Location; throw "npm install не удался" }
Write-Host "[ok]   зависимости установлены" -ForegroundColor Green
Pop-Location

Write-Host "`nГотово. Запуск: powershell -ExecutionPolicy Bypass -File scripts\run.ps1" -ForegroundColor Cyan

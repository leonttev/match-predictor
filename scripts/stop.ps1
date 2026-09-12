# Stops everything started by run.ps1 by freeing the ports it uses.
#
#   powershell -ExecutionPolicy Bypass -File scripts\stop.ps1
#
# Pass the same port overrides that were given to run.ps1:
#
#   powershell -ExecutionPolicy Bypass -File scripts\stop.ps1 -BackendPort 8200

param(
    [int]$EnginePort = 8090,
    [int]$DbPort = 8081,
    [int]$BackendPort = 8000,
    [int]$FrontendPort = 5173
)

foreach ($port in @($EnginePort, $DbPort, $BackendPort, $FrontendPort)) {
    $pids = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique
    foreach ($processId in $pids) {
        try {
            $name = (Get-Process -Id $processId -ErrorAction Stop).ProcessName
            Stop-Process -Id $processId -Force
            Write-Host "[остановлен] порт $port — $name (PID $processId)" -ForegroundColor Green
        } catch {
            Write-Host "[!] не удалось остановить процесс на порту $port" -ForegroundColor Yellow
        }
    }
}
Write-Host "Готово." -ForegroundColor Cyan

# Stops everything started by run.ps1 by freeing the four ports it uses.
#
#   powershell -ExecutionPolicy Bypass -File scripts\stop.ps1

foreach ($port in 8090, 8081, 8000, 5173) {
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

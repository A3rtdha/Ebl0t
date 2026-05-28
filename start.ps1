# Запуск Eblot без Docker
Set-Location $PSScriptRoot

if (-not (Test-Path .env)) {
    Write-Error "Нет файла .env — скопируй .env.example и задай DISCORD_TOKEN"
    exit 1
}

$proxyLine = Get-Content .env | Where-Object { $_ -match '^\s*PROXY\s*=' } | Select-Object -First 1
if ($proxyLine -match 'PROXY\s*=\s*(.+)$') {
    $proxyUrl = $matches[1].Trim().Trim('"').Trim("'")
    if ($proxyUrl -match '127\.0\.0\.1:(\d+)|localhost:(\d+)') {
        $port = if ($matches[1]) { $matches[1] } else { $matches[2] }
        $ok = (Test-NetConnection 127.0.0.1 -Port $port -WarningAction SilentlyContinue).TcpTestSucceeded
        if (-not $ok) {
            Write-Host "Прокси $proxyUrl недоступен (порт $port). Запускаю без прокси." -ForegroundColor Yellow
            Write-Host "Включи VPN или раскомментируй PROXY в .env когда прокси поднимется." -ForegroundColor Yellow
            $env:PROXY = ''
        } else {
            $env:PROXY = $proxyUrl
        }
    }
}

# Один инстанс: несколько python main.py → тройные ответы на один скрин
$pidFile = Join-Path $PSScriptRoot ".eblot.pid"
if (Test-Path $pidFile) {
    $oldPid = [int](Get-Content $pidFile -Raw)
    if (Get-Process -Id $oldPid -ErrorAction SilentlyContinue) {
        Write-Host "Останавливаю предыдущий инстанс Eblot (PID $oldPid)..." -ForegroundColor Yellow
        Stop-Process -Id $oldPid -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 2
    }
}
# Подчистить зомби без pid-файла (старые запуски)
Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match 'main\.py' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 1

Write-Host "Запуск бота..." -ForegroundColor Cyan
python main.py

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

Write-Host "Запуск бота..." -ForegroundColor Cyan
python main.py

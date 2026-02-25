# Скрипт остановки приложения
Write-Host "Остановка приложения..." -ForegroundColor Yellow

# Остановка процессов Python
Get-Process python -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Get-Process pythonw -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue

Write-Host "Приложение остановлено." -ForegroundColor Green



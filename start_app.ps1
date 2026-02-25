# Скрипт запуска приложения
Write-Host "Установка зависимостей..." -ForegroundColor Green
python -m pip install -r requirements.txt

Write-Host "`nЗапуск приложения..." -ForegroundColor Green
python app.py


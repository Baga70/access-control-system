@echo off
chcp 65001 >nul
echo Установка зависимостей...
python -m pip install -r requirements.txt
echo.
echo Запуск приложения...
python app.py
pause


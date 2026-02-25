@echo off
chcp 65001 >nul
echo Остановка приложения...
taskkill /F /IM python.exe /T 2>nul
taskkill /F /IM pythonw.exe /T 2>nul
echo.
echo Приложение остановлено.
pause



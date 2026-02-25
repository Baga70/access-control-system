@echo off
REM Скрипт для автоматического запуска backup через Task Scheduler Windows
REM 
REM Инструкция по настройке:
REM 1. Откройте Task Scheduler (Планировщик задач)
REM 2. Создайте новую задачу (Create Basic Task)
REM 3. Настройте:
REM    - Trigger: Ежедневно в 2:00 (или другое удобное время)
REM    - Action: Start a program
REM    - Program: python (или полный путь к python.exe)
REM    - Arguments: "C:\Users\koval\OneDrive\Desktop\RRR\auto_backup.py"
REM    - Start in: "C:\Users\koval\OneDrive\Desktop\RRR"
REM 4. Сохраните задачу
REM
REM Или используйте этот файл для ручного запуска

cd /d "%~dp0"
python auto_backup.py

if %ERRORLEVEL% NEQ 0 (
    echo Ошибка выполнения backup!
    exit /b 1
)

echo Backup успешно выполнен!
exit /b 0


@echo off
echo ============================================
echo Применение миграции: Добавление таблицы departments
echo ============================================
echo.

set PGPASSWORD=300307

psql -U postgres -d access_control_db -f "migrations\001_add_departments_table.sql"

if %errorlevel% equ 0 (
    echo.
    echo ============================================
    echo ✓ Миграция успешно применена!
    echo ============================================
) else (
    echo.
    echo ============================================
    echo ✗ Ошибка при применении миграции
    echo ============================================
)

set PGPASSWORD=
pause

@echo off
REM ============================================
REM ПОШАГОВАЯ НАСТРОЙКА РЕПЛИКАЦИИ PostgreSQL
REM ============================================

echo.
echo =====================================================
echo НАСТРОЙКА РЕПЛИКАЦИИ POSTGRESQL (WINDOWS)
echo =====================================================
echo.

REM Переменные (ИЗМЕНИТЕ ПОД СВОЮ УСТАНОВКУ PostgreSQL)
set PGUSER=postgres
set PGPASSWORD=300307
set PGHOST=localhost
set PGPORT=5432
set PGDATABASE=access_control_db

REM Путь к PostgreSQL (ИЗМЕНИТЕ если PostgreSQL установлен в другом месте)
set PGBIN=C:\Program Files\PostgreSQL\17\bin
set PGDATA=C:\Program Files\PostgreSQL\17\data
set REPLICA_DATA=C:\PostgreSQL_Replica\data

echo.
echo [ШАГ 1] Проверка подключения к PostgreSQL...
echo.
"%PGBIN%\psql" -U %PGUSER% -d %PGDATABASE% -c "SELECT version();"
if errorlevel 1 (
    echo ОШИБКА: Не удалось подключиться к PostgreSQL
    echo Проверьте:
    echo - PostgreSQL запущен?
    echo - Пароль правильный?
    echo - База данных существует?
    pause
    exit /b 1
)

echo.
echo [ШАГ 2] Проверка текущих настроек WAL...
echo.
"%PGBIN%\psql" -U %PGUSER% -d %PGDATABASE% -c "SHOW wal_level;"
"%PGBIN%\psql" -U %PGUSER% -d %PGDATABASE% -c "SHOW max_wal_senders;"

echo.
echo =====================================================
echo ВАЖНО: Для репликации нужно настроить postgresql.conf
echo =====================================================
echo.
echo Откройте файл:
echo %PGDATA%\postgresql.conf
echo.
echo И добавьте/измените следующие строки:
echo.
echo wal_level = replica
echo max_wal_senders = 3
echo wal_keep_size = 64
echo.
echo После изменений ПЕРЕЗАПУСТИТЕ PostgreSQL!
echo.
pause

echo.
echo [ШАГ 3] Создание папки для реплики...
echo.
if not exist "%REPLICA_DATA%" (
    mkdir "%REPLICA_DATA%"
    echo Папка создана: %REPLICA_DATA%
) else (
    echo ВНИМАНИЕ: Папка уже существует!
    echo Если хотите пересоздать реплику, сначала удалите эту папку.
    echo.
    set /p CONTINUE="Продолжить? (y/n): "
    if /i not "%CONTINUE%"=="y" exit /b 0
)

echo.
echo [ШАГ 4] Создание базовой копии (pg_basebackup)...
echo Это может занять несколько минут...
echo.

"%PGBIN%\pg_basebackup" -h %PGHOST% -p %PGPORT% -U %PGUSER% -D "%REPLICA_DATA%" -P -R --wal-method=stream

if errorlevel 1 (
    echo.
    echo ОШИБКА при создании базовой копии!
    echo.
    echo Возможные причины:
    echo 1. PostgreSQL не перезапущен после изменения postgresql.conf
    echo 2. Недостаточно прав доступа
    echo 3. Папка реплики уже занята
    echo.
    pause
    exit /b 1
)

echo.
echo [ШАГ 5] Настройка файла конфигурации реплики...
echo.

REM pg_basebackup с параметром -R уже создал нужные настройки
REM Проверим наличие standby.signal
if exist "%REPLICA_DATA%\standby.signal" (
    echo ✓ Файл standby.signal найден
) else (
    echo Создание файла standby.signal...
    echo. > "%REPLICA_DATA%\standby.signal"
)

REM Изменить порт реплики, чтобы не конфликтовал с мастером
echo.
echo [ШАГ 6] Изменение порта реплики на 5433...
echo.

REM Добавить/изменить порт в postgresql.conf реплики
findstr /C:"port = 5433" "%REPLICA_DATA%\postgresql.conf" >nul
if errorlevel 1 (
    echo port = 5433 >> "%REPLICA_DATA%\postgresql.conf"
    echo ✓ Порт изменен на 5433
) else (
    echo ✓ Порт уже установлен на 5433
)

echo.
echo =====================================================
echo РЕПЛИКАЦИЯ НАСТРОЕНА!
echo =====================================================
echo.
echo Теперь нужно:
echo.
echo 1. ЗАРЕГИСТРИРОВАТЬ РЕПЛИКУ как службу Windows:
echo    "%PGBIN%\pg_ctl" register -N "PostgreSQL_Replica" -D "%REPLICA_DATA%"
echo.
echo 2. ЗАПУСТИТЬ РЕПЛИКУ:
echo    net start PostgreSQL_Replica
echo.
echo 3. ПРОВЕРИТЬ РЕПЛИКАЦИЮ на мастере:
echo    psql -U postgres -d access_control_db
echo    SELECT * FROM pg_stat_replication;
echo.
echo 4. ПРОВЕРИТЬ РЕПЛИКУ:
echo    psql -U postgres -h localhost -p 5433 -d access_control_db
echo    SELECT pg_is_in_recovery();
echo.
echo =====================================================

pause

echo.
echo Хотите автоматически зарегистрировать и запустить реплику?
set /p AUTO="(y/n): "

if /i "%AUTO%"=="y" (
    echo.
    echo Регистрация службы...
    "%PGBIN%\pg_ctl" register -N "PostgreSQL_Replica" -D "%REPLICA_DATA%"
    
    echo.
    echo Запуск службы...
    net start PostgreSQL_Replica
    
    echo.
    echo Ожидание 10 секунд для инициализации...
    timeout /t 10 /nobreak
    
    echo.
    echo [ПРОВЕРКА] Статус репликации на мастере:
    "%PGBIN%\psql" -U %PGUSER% -d %PGDATABASE% -c "SELECT application_name, state, sync_state FROM pg_stat_replication;"
    
    echo.
    echo [ПРОВЕРКА] Режим на реплике:
    "%PGBIN%\psql" -U %PGUSER% -h %PGHOST% -p 5433 -d %PGDATABASE% -c "SELECT pg_is_in_recovery();"
)

echo.
echo =====================================================
echo ГОТОВО!
echo =====================================================
pause

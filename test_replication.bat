@echo off
REM ================================================
REM БЫСТРАЯ ПРОВЕРКА РЕПЛИКАЦИИ
REM ================================================

echo.
echo ================================================
echo ПРОВЕРКА РЕПЛИКАЦИИ POSTGRESQL
echo ================================================
echo.

echo [ШАГ 1] Проверка репликации на МАСТЕРЕ...
echo.
psql -U postgres -d access_control_db -c "SELECT pid, usename, client_addr, state, sync_state FROM pg_stat_replication;"

echo.
echo.
echo [ШАГ 2] Проверка режима работы мастера...
echo.
psql -U postgres -d access_control_db -c "SELECT pg_is_in_recovery() AS is_replica;"

echo.
echo.
echo [ШАГ 3] Вставка тестовых данных...
echo.
psql -U postgres -d access_control_db -c "CREATE TABLE IF NOT EXISTS replication_test (id SERIAL PRIMARY KEY, test_data TEXT, created_at TIMESTAMP DEFAULT NOW());"
psql -U postgres -d access_control_db -c "INSERT INTO replication_test (test_data) VALUES ('Test at %date% %time%');"

echo.
echo.
echo [ШАГ 4] Проверка данных на мастере...
echo.
psql -U postgres -d access_control_db -c "SELECT * FROM replication_test ORDER BY created_at DESC LIMIT 5;"

echo.
echo.
echo ================================================
echo РЕЗУЛЬТАТ:
echo ================================================
echo.
echo Если в [ШАГ 1] есть строки - репликация работает!
echo Если в [ШАГ 1] пусто - репликация НЕ настроена
echo.
echo ТЕПЕРЬ ПРОВЕРЬТЕ РЕПЛИКУ:
echo 1. Подключитесь: psql -U postgres -h localhost -p 5433 -d access_control_db
echo 2. Выполните: SELECT * FROM replication_test ORDER BY created_at DESC LIMIT 5;
echo 3. Данные должны совпадать с мастером!
echo.
echo ================================================

pause

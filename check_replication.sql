-- ============================================
-- СКРИПТ ПРОВЕРКИ РЕПЛИКАЦИИ POSTGRESQL
-- ============================================

-- 1. ПРОВЕРКА НА МАСТЕРЕ
-- Запустить на мастере (порт 5432)
-- psql -U postgres -d access_control_db -f check_replication.sql

\echo '================================================'
\echo 'ПРОВЕРКА РЕПЛИКАЦИИ - МАСТЕР СЕРВЕР'
\echo '================================================'

\echo ''
\echo '1. Активные WAL-senders (должна быть хотя бы одна реплика):'
SELECT 
    pid,
    usename,
    application_name,
    client_addr,
    state,
    sync_state,
    replay_lsn,
    pg_size_pretty(pg_wal_lsn_diff(pg_current_wal_lsn(), replay_lsn)) AS lag
FROM pg_stat_replication;

\echo ''
\echo '2. Режим работы (должно быть false = мастер):'
SELECT pg_is_in_recovery() AS is_replica;

\echo ''
\echo '3. Текущая позиция WAL на мастере:'
SELECT pg_current_wal_lsn() AS current_wal_position;

\echo ''
\echo '4. Размер WAL (Write-Ahead Log):'
SELECT pg_size_pretty(pg_wal_lsn_diff(pg_current_wal_lsn(), '0/0')) AS total_wal_size;

\echo ''
\echo '5. Количество активных соединений:'
SELECT 
    count(*) AS total_connections,
    count(*) FILTER (WHERE state = 'active') AS active_connections,
    count(*) FILTER (WHERE state = 'idle') AS idle_connections
FROM pg_stat_activity
WHERE datname = 'access_control_db';

\echo ''
\echo '================================================'
\echo 'ТЕСТ РЕПЛИКАЦИИ'
\echo '================================================'

-- Создать тестовую таблицу (если не существует)
\echo ''
\echo 'Создание тестовой таблицы...'
CREATE TABLE IF NOT EXISTS replication_test (
    id SERIAL PRIMARY KEY,
    test_data TEXT,
    checked_on TEXT DEFAULT 'master',
    created_at TIMESTAMP DEFAULT NOW()
);

-- Вставить тестовую запись
\echo 'Вставка тестовой записи...'
INSERT INTO replication_test (test_data, checked_on) 
VALUES ('Test at ' || NOW(), 'master');

-- Показать последние записи
\echo ''
\echo 'Последние 5 записей в replication_test:'
SELECT * FROM replication_test ORDER BY created_at DESC LIMIT 5;

\echo ''
\echo '================================================'
\echo 'ИНСТРУКЦИЯ ДЛЯ ПРОВЕРКИ НА РЕПЛИКЕ:'
\echo '================================================'
\echo '1. Подключитесь к реплике:'
\echo '   psql -U postgres -h localhost -p 5433 -d access_control_db'
\echo ''
\echo '2. Выполните запрос:'
\echo '   SELECT pg_is_in_recovery(); -- Должно быть true'
\echo ''
\echo '3. Проверьте данные:'
\echo '   SELECT * FROM replication_test ORDER BY created_at DESC LIMIT 5;'
\echo ''
\echo 'Тестовая запись должна появиться на реплике через 1-2 секунды!'
\echo '================================================'

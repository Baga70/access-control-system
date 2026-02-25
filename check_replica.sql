-- ============================================
-- СКРИПТ ПРОВЕРКИ РЕПЛИКАЦИИ - РЕПЛИКА
-- ============================================

-- Запустить на реплике (порт 5433 или другой порт реплики)
-- psql -U postgres -h localhost -p 5433 -d access_control_db -f check_replica.sql

\echo '================================================'
\echo 'ПРОВЕРКА РЕПЛИКАЦИИ - STANDBY (РЕПЛИКА)'
\echo '================================================'

\echo ''
\echo '1. Режим работы (должно быть true = реплика в режиме восстановления):'
SELECT pg_is_in_recovery() AS is_in_recovery;

\echo ''
\echo '2. Последняя полученная позиция WAL:'
SELECT pg_last_wal_receive_lsn() AS last_receive_lsn;

\echo ''
\echo '3. Последняя воспроизведенная позиция WAL:'
SELECT pg_last_wal_replay_lsn() AS last_replay_lsn;

\echo ''
\echo '4. Время последней транзакции на реплике:'
SELECT pg_last_xact_replay_timestamp() AS last_xact_timestamp;

\echo ''
\echo '5. Задержка репликации (в секундах):'
SELECT 
    EXTRACT(EPOCH FROM (now() - pg_last_xact_replay_timestamp())) AS lag_seconds,
    CASE 
        WHEN EXTRACT(EPOCH FROM (now() - pg_last_xact_replay_timestamp())) < 5 THEN '✅ ОТЛИЧНО'
        WHEN EXTRACT(EPOCH FROM (now() - pg_last_xact_replay_timestamp())) < 30 THEN '⚠️ НОРМА'
        ELSE '❌ МЕДЛЕННО'
    END AS status
;

\echo ''
\echo '6. Информация о подключении к мастеру:'
SELECT 
    conninfo AS master_connection_info
FROM pg_stat_wal_receiver;

\echo ''
\echo '7. Статистика WAL receiver:'
SELECT 
    status,
    receive_start_lsn,
    received_lsn,
    latest_end_lsn,
    pg_size_pretty(pg_wal_lsn_diff(received_lsn, receive_start_lsn)) AS received_size
FROM pg_stat_wal_receiver;

\echo ''
\echo '================================================'
\echo 'ПРОВЕРКА СИНХРОНИЗАЦИИ ДАННЫХ'
\echo '================================================'

\echo ''
\echo 'Тестовые данные из replication_test:'
\echo '(Эти данные должны совпадать с данными на мастере)'
SELECT 
    id,
    test_data,
    checked_on,
    created_at,
    CASE 
        WHEN created_at > NOW() - INTERVAL '1 minute' THEN '🆕 НОВАЯ'
        WHEN created_at > NOW() - INTERVAL '1 hour' THEN '📅 НЕДАВНЯЯ'
        ELSE '📂 СТАРАЯ'
    END AS record_age
FROM replication_test 
ORDER BY created_at DESC 
LIMIT 10;

\echo ''
\echo '================================================'
\echo 'АНАЛИЗ РЕПЛИКАЦИИ'
\echo '================================================'

\echo ''
\echo '✅ ЕСЛИ ВЫ ВИДИТЕ ДАННЫЕ:'
\echo '   - Репликация работает корректно'
\echo '   - Данные синхронизируются с мастера'
\echo ''
\echo '⚠️ ЕСЛИ ДАННЫХ НЕТ ИЛИ ОНИ УСТАРЕВШИЕ:'
\echo '   - Проверьте статус WAL receiver'
\echo '   - Проверьте сетевое подключение к мастеру'
\echo '   - Проверьте логи PostgreSQL'
\echo ''
\echo '📊 РЕКОМЕНДАЦИИ:'
\echo '   - Задержка < 5 сек - отлично'
\echo '   - Задержка 5-30 сек - нормально'
\echo '   - Задержка > 30 сек - требует внимания'
\echo '================================================'

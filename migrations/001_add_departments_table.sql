-- ============================================
-- МИГРАЦИЯ: Добавление таблицы отделов
-- Дата: 2026-02-17
-- ============================================

-- Создание таблицы отделов
CREATE TABLE IF NOT EXISTS departments (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL UNIQUE,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Создание индекса для быстрого поиска
CREATE INDEX IF NOT EXISTS idx_departments_name ON departments(name);

-- Миграция существующих отделов из таблицы employees
INSERT INTO departments (name)
SELECT DISTINCT department 
FROM employees 
WHERE department IS NOT NULL AND department != ''
ON CONFLICT (name) DO NOTHING;

-- Добавление внешнего ключа на таблицу departments (опционально, если хотим строгую связь)
-- Пока оставляем department как VARCHAR для обратной совместимости
-- ALTER TABLE employees ADD COLUMN department_id INTEGER REFERENCES departments(id);


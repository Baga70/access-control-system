"""
Скрипт применения миграции: создание таблицы departments
Запуск: python run_migration.py
"""
import psycopg2

DATABASE_CONFIG = {
    'host': 'localhost',
    'port': 5432,
    'database': 'access_control_db',
    'user': 'postgres',
    'password': '300307',
    'client_encoding': 'utf8'
}

SQL = """
-- Создание таблицы отделов
CREATE TABLE IF NOT EXISTS departments (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL UNIQUE,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Индекс для быстрого поиска
CREATE INDEX IF NOT EXISTS idx_departments_name ON departments(name);

-- Перенос существующих отделов из employees
INSERT INTO departments (name)
SELECT DISTINCT department 
FROM employees 
WHERE department IS NOT NULL AND department != ''
ON CONFLICT (name) DO NOTHING;
"""

try:
    conn = psycopg2.connect(**DATABASE_CONFIG)
    cursor = conn.cursor()
    cursor.execute(SQL)
    conn.commit()

    # Показываем результат
    cursor.execute("SELECT name FROM departments ORDER BY name")
    departments = cursor.fetchall()

    cursor.close()
    conn.close()

    print("=" * 50)
    print("✓ Миграция успешно применена!")
    print(f"✓ Отделов в базе данных: {len(departments)}")
    if departments:
        print("\nСписок отделов:")
        for d in departments:
            print(f"  - {d[0]}")
    print("=" * 50)

except Exception as e:
    print("=" * 50)
    print(f"✗ Ошибка: {e}")
    print("=" * 50)

input("\nНажмите Enter для выхода...")

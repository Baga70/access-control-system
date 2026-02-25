-- ============================================
-- СИСТЕМА УПРАВЛЕНИЯ ДОСТУПОМ
-- SQL-скрипт для создания всех таблиц и связей
-- ============================================

-- Удаление существующих таблиц (если есть)
DROP TABLE IF EXISTS access_logs;
DROP TABLE IF EXISTS group_access_levels;
DROP TABLE IF EXISTS group_employees;
DROP TABLE IF EXISTS employee_groups;
DROP TABLE IF EXISTS access_keys;
DROP TABLE IF EXISTS employees;
DROP TABLE IF EXISTS departments;
DROP TABLE IF EXISTS access_levels;
DROP TABLE IF EXISTS access_points;

-- ============================================
-- Создание таблиц
-- ============================================

-- Таблица: Уровни доступа
CREATE TABLE access_levels (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL UNIQUE,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Таблица: Точки доступа
CREATE TABLE access_points (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL UNIQUE,
    location VARCHAR(200),
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Таблица: Отделы
CREATE TABLE departments (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL UNIQUE,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Таблица: Сотрудники
CREATE TABLE employees (
    id SERIAL PRIMARY KEY,
    full_name VARCHAR(200) NOT NULL,
    position VARCHAR(100),
    department VARCHAR(100),
    phone VARCHAR(20),
    email VARCHAR(100),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Таблица: Ключи доступа
CREATE TABLE access_keys (
    id SERIAL PRIMARY KEY,
    employee_id INTEGER NOT NULL,
    key_identifier VARCHAR(100) NOT NULL UNIQUE,
    key_type VARCHAR(50) DEFAULT 'RFID',
    issued_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expiry_date TIMESTAMP,
    is_active BOOLEAN DEFAULT TRUE,
    FOREIGN KEY (employee_id) REFERENCES employees(id) ON DELETE CASCADE
);

-- Таблица: Группы сотрудников
CREATE TABLE employee_groups (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL UNIQUE,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Таблица связи N:M: Группы сотрудников - Уровни доступа
CREATE TABLE group_access_levels (
    id SERIAL PRIMARY KEY,
    group_id INTEGER NOT NULL,
    access_level_id INTEGER NOT NULL,
    FOREIGN KEY (group_id) REFERENCES employee_groups(id) ON DELETE CASCADE,
    FOREIGN KEY (access_level_id) REFERENCES access_levels(id) ON DELETE CASCADE,
    UNIQUE(group_id, access_level_id)
);

-- Таблица связи N:M: Сотрудники - Группы
CREATE TABLE group_employees (
    id SERIAL PRIMARY KEY,
    employee_id INTEGER NOT NULL,
    group_id INTEGER NOT NULL,
    FOREIGN KEY (employee_id) REFERENCES employees(id) ON DELETE CASCADE,
    FOREIGN KEY (group_id) REFERENCES employee_groups(id) ON DELETE CASCADE,
    UNIQUE(employee_id, group_id)
);

-- Таблица: Логи доступа
CREATE TABLE access_logs (
    id SERIAL PRIMARY KEY,
    employee_id INTEGER NOT NULL,
    access_key_id INTEGER NOT NULL,
    access_point_id INTEGER NOT NULL,
    access_level_id INTEGER NOT NULL,
    access_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    access_result VARCHAR(20) NOT NULL CHECK (access_result IN ('granted', 'denied', 'expired', 'inactive')),
    reason TEXT,
    FOREIGN KEY (employee_id) REFERENCES employees(id) ON DELETE CASCADE,
    FOREIGN KEY (access_key_id) REFERENCES access_keys(id) ON DELETE CASCADE,
    FOREIGN KEY (access_point_id) REFERENCES access_points(id) ON DELETE CASCADE,
    FOREIGN KEY (access_level_id) REFERENCES access_levels(id) ON DELETE CASCADE
);

-- ============================================
-- Создание индексов для ускорения запросов
-- ============================================

CREATE INDEX idx_access_keys_employee ON access_keys(employee_id);
CREATE INDEX idx_access_keys_identifier ON access_keys(key_identifier);
CREATE INDEX idx_access_logs_employee ON access_logs(employee_id);
CREATE INDEX idx_access_logs_key ON access_logs(access_key_id);
CREATE INDEX idx_access_logs_point ON access_logs(access_point_id);
CREATE INDEX idx_access_logs_time ON access_logs(access_time);
CREATE INDEX idx_access_logs_result ON access_logs(access_result);
CREATE INDEX idx_group_employees_employee ON group_employees(employee_id);
CREATE INDEX idx_group_employees_group ON group_employees(group_id);
CREATE INDEX idx_group_access_levels_group ON group_access_levels(group_id);
CREATE INDEX idx_group_access_levels_level ON group_access_levels(access_level_id);
CREATE INDEX idx_departments_name ON departments(name);

-- ============================================
-- Вставка тестовых данных (опционально)
-- ============================================

-- Тестовые уровни доступа
INSERT INTO access_levels (name, description) VALUES
('Уровень 1 - Рецепция', 'Доступ к рецепции и общим зонам'),
('Уровень 2 - Офисные помещения', 'Доступ к офисным помещениям'),
('Уровень 3 - Служебные помещения', 'Доступ к служебным помещениям'),
('Уровень 4 - Административные помещения', 'Полный доступ ко всем помещениям');

-- Тестовые точки доступа
INSERT INTO access_points (name, location, description) VALUES
('Точка 1 - Главный вход', '1 этаж, центральный вход', 'Главный вход в здание'),
('Точка 2 - Офисный блок A', '2 этаж, блок A', 'Вход в офисный блок A'),
('Точка 3 - Офисный блок B', '2 этаж, блок B', 'Вход в офисный блок B'),
('Точка 4 - Служебные помещения', '1 этаж, задняя часть', 'Вход в служебные помещения'),
('Точка 5 - Администрация', '3 этаж, крыло C', 'Вход в административный блок');

-- Тестовые отделы
INSERT INTO departments (name, description) VALUES
('Отдел продаж', 'Отдел продаж и маркетинга'),
('Бухгалтерия', 'Бухгалтерия и финансовый отдел'),
('Администрация', 'Административный отдел'),
('Рецепция', 'Служба приема и регистрации');

-- Тестовые сотрудники
INSERT INTO employees (full_name, position, department, phone, email) VALUES
('Иванов Иван Иванович', 'Менеджер', 'Отдел продаж', '+7 (999) 123-45-67', 'ivanov@example.com'),
('Петрова Мария Сергеевна', 'Бухгалтер', 'Бухгалтерия', '+7 (999) 234-56-78', 'petrova@example.com'),
('Сидоров Петр Александрович', 'Директор', 'Администрация', '+7 (999) 345-67-89', 'sidorov@example.com'),
('Козлова Анна Владимировна', 'Секретарь', 'Рецепция', '+7 (999) 456-78-90', 'kozlova@example.com');

-- Тестовые группы
INSERT INTO employee_groups (name, description) VALUES
('Персонал', 'Основной персонал'),
('Администрация', 'Административный состав'),
('Офисные работники', 'Работники офисных помещений');

-- Привязка уровней доступа к группам
INSERT INTO group_access_levels (group_id, access_level_id) VALUES
(1, 1),  -- Персонал - Уровень 1
(1, 2),  -- Персонал - Уровень 2
(2, 1),  -- Администрация - Уровень 1
(2, 2),  -- Администрация - Уровень 2
(2, 3),  -- Администрация - Уровень 3
(2, 4),  -- Администрация - Уровень 4
(3, 1),  -- Офисные работники - Уровень 1
(3, 2);  -- Офисные работники - Уровень 2

-- Привязка сотрудников к группам
INSERT INTO group_employees (employee_id, group_id) VALUES
(1, 1),  -- Иванов - Персонал
(2, 1),  -- Петрова - Персонал
(3, 2),  -- Сидоров - Администрация
(4, 3);  -- Козлова - Офисные работники

-- Тестовые ключи доступа
INSERT INTO access_keys (employee_id, key_identifier, key_type, issued_date) VALUES
(1, 'RFID-001-ABC123', 'RFID', CURRENT_TIMESTAMP),
(2, 'RFID-002-DEF456', 'RFID', CURRENT_TIMESTAMP),
(3, 'RFID-003-GHI789', 'RFID', CURRENT_TIMESTAMP),
(4, 'RFID-004-JKL012', 'RFID', CURRENT_TIMESTAMP);

-- Тестовые логи доступа
INSERT INTO access_logs (employee_id, access_key_id, access_point_id, access_level_id, access_time, access_result, reason) VALUES
(1, 1, 1, 1, CURRENT_TIMESTAMP - INTERVAL '1 day', 'granted', 'Успешный доступ'),
(1, 1, 2, 2, CURRENT_TIMESTAMP - INTERVAL '12 hours', 'granted', 'Успешный доступ'),
(2, 2, 1, 1, CURRENT_TIMESTAMP - INTERVAL '6 hours', 'granted', 'Успешный доступ'),
(3, 3, 1, 4, CURRENT_TIMESTAMP - INTERVAL '3 hours', 'granted', 'Успешный доступ'),
(3, 3, 5, 4, CURRENT_TIMESTAMP - INTERVAL '1 hour', 'granted', 'Успешный доступ');

-- Администратор по умолчанию
-- Пароль: admin123 (хэш bcrypt)
-- Примечание: в реальном приложении хэш должен быть в отдельной таблице users
-- INSERT INTO admin_users (username, password_hash) VALUES
-- ('admin', '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewY5LSYWW9zzhj2a');


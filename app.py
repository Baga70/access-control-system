"""
Система управления доступом
Flask приложение для управления доступом
"""

from flask import Flask, render_template, request, jsonify as flask_jsonify, redirect, url_for, session, flash, make_response
from flask.json.provider import DefaultJSONProvider
from functools import wraps
import pg8000
import json
import csv
import io
from datetime import datetime, timedelta
import bcrypt
import os
import logging
from logging.handlers import RotatingFileHandler
import re
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
from werkzeug.middleware.dispatcher import DispatcherMiddleware
from backup_manager import BackupManager

# Импорт APScheduler с обработкой ошибок
try:
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.interval import IntervalTrigger
    APSCHEDULER_AVAILABLE = True
except ImportError:
    APSCHEDULER_AVAILABLE = False
    BackgroundScheduler = None
    IntervalTrigger = None

import atexit

app = Flask(__name__)
app.secret_key = 'your-secret-key-change-this-in-production'

# Настройка системы логирования
if not os.path.exists('logs'):
    os.makedirs('logs')

# Настройка формата логирования
log_format = logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# Файловый обработчик с ротацией
file_handler = RotatingFileHandler(
    'logs/app.log',
    maxBytes=10485760,  # 10MB
    backupCount=10
)
file_handler.setFormatter(log_format)
file_handler.setLevel(logging.INFO)

# Обработчик ошибок
error_handler = RotatingFileHandler(
    'logs/errors.log',
    maxBytes=10485760,  # 10MB
    backupCount=10
)
error_handler.setFormatter(log_format)
error_handler.setLevel(logging.ERROR)

# Настройка логгера приложения
app.logger.setLevel(logging.INFO)
app.logger.addHandler(file_handler)
app.logger.addHandler(error_handler)

# Логгер для базы данных
db_logger = logging.getLogger('database')
db_logger.setLevel(logging.INFO)
db_logger.addHandler(file_handler)
db_logger.addHandler(error_handler)

# Логгер для доступа
access_logger = logging.getLogger('access')
access_logger.setLevel(logging.INFO)
access_logger.addHandler(file_handler)

# ======================
# Prometheus метрики
# ======================

# Счётчик HTTP запросов
http_requests_total = Counter(
    'http_requests_total',
    'Total HTTP requests',
    ['method', 'endpoint', 'status']
)

# Гистограмма длительности запросов
http_request_duration = Histogram(
    'http_request_duration_seconds',
    'HTTP request duration in seconds',
    ['method', 'endpoint']
)

# Счётчик операций с БД
db_operations_total = Counter(
    'db_operations_total',
    'Total database operations',
    ['operation', 'table', 'status']
)

# Активные соединения с БД
db_active_connections = Gauge(
    'db_active_connections',
    'Active database connections'
)

# Размер базы данных
db_size_bytes = Gauge(
    'db_size_bytes',
    'Database size in bytes',
    ['database']
)

# ======================
# Middleware для метрик
# ======================

@app.before_request
def before_request():
    """Логирование и метрики перед запросом"""
    # Пропускаем статические файлы и /metrics
    if request.path.startswith('/static') or request.path == '/metrics':
        return
    request.start_time = datetime.now()
    access_logger.info(f"{request.method} {request.path} - User: {session.get('username', 'anonymous')}")

@app.after_request
def after_request(response):
    """Логирование и метрики после запроса"""
    # Пропускаем статические файлы и /metrics
    if request.path.startswith('/static') or request.path == '/metrics':
        return response
    
    if hasattr(request, 'start_time'):
        duration = (datetime.now() - request.start_time).total_seconds()
        
        # Метрики Prometheus
        try:
            http_requests_total.labels(
                method=request.method,
                endpoint=request.endpoint or 'unknown',
                status=response.status_code
            ).inc()
            
            http_request_duration.labels(
                method=request.method,
                endpoint=request.endpoint or 'unknown'
            ).observe(duration)
        except:
            pass  # Если prometheus_client не установлен
        
        access_logger.info(
            f"{request.method} {request.path} - "
            f"Status: {response.status_code} - "
            f"Duration: {duration:.3f}s"
        )
    
    return response

@app.route('/metrics')
def metrics():
    """Эндпоинт для Prometheus"""
    return generate_latest(), 200, {'Content-Type': CONTENT_TYPE_LATEST}

# ======================
# Функции валидации
# ======================

def validate_email(email):
    """Валидация email"""
    if not email:
        return True  # Email опционален
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email) is not None

def validate_phone(phone):
    """Валидация телефона"""
    if not phone:
        return True  # Телефон опционален
    # Удаляем пробелы, скобки, дефисы
    cleaned = re.sub(r'[\s\(\)\-]', '', phone)
    # Проверяем формат: +7 или 8 и 10 цифр
    pattern = r'^(\+?7|8)?\d{10}$'
    return re.match(pattern, cleaned) is not None

def validate_text_field(value, field_name, min_length=1, max_length=None, required=True):
    """Валидация текстового поля"""
    if not value and required:
        return f"Поле '{field_name}' обязательно для заполнения"
    if value and min_length and len(value.strip()) < min_length:
        return f"Поле '{field_name}' должно содержать минимум {min_length} символов"
    if value and max_length and len(value) > max_length:
        return f"Поле '{field_name}' должно содержать максимум {max_length} символов"
    return None

def validate_employee_data(data):
    """Валидация данных сотрудника"""
    errors = []
    
    # Валидация обязательных полей
    name_error = validate_text_field(data.get('full_name'), 'ФИО', min_length=2, max_length=200, required=True)
    if name_error:
        errors.append(name_error)
    
    # Валидация опциональных полей
    if data.get('position'):
        pos_error = validate_text_field(data.get('position'), 'Должность', min_length=2, max_length=100, required=False)
        if pos_error:
            errors.append(pos_error)
    
    if data.get('department'):
        dept_error = validate_text_field(data.get('department'), 'Отдел', min_length=2, max_length=100, required=False)
        if dept_error:
            errors.append(dept_error)
    
    # Валидация email
    if data.get('email') and not validate_email(data['email']):
        errors.append("Некорректный формат email")
    
    # Валидация телефона
    if data.get('phone') and not validate_phone(data['phone']):
        errors.append("Некорректный формат телефона")
    
    return errors

def validate_key_data(data):
    """Валидация данных ключа доступа"""
    errors = []
    
    if not data.get('employee_id'):
        errors.append("Необходимо указать сотрудника")
    
    key_error = validate_text_field(data.get('key_identifier'), 'Идентификатор ключа', min_length=3, max_length=100, required=True)
    if key_error:
        errors.append(key_error)
    
    if data.get('expiry_date'):
        try:
            expiry = datetime.fromisoformat(data['expiry_date'].replace('Z', '+00:00'))
            if expiry < datetime.now():
                errors.append("Дата истечения не может быть в прошлом")
        except (ValueError, AttributeError):
            errors.append("Некорректный формат даты истечения")
    
    return errors

# Настройка JSON для Flask 3.0+ с поддержкой datetime
class CustomJSONProvider(DefaultJSONProvider):
    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.strftime('%Y-%m-%d %H:%M:%S')
        elif hasattr(obj, 'isoformat'):
            return obj.isoformat()
        return super().default(obj)

app.json = CustomJSONProvider(app)

# Обертка для jsonify с поддержкой datetime
def jsonify(*args, **kwargs):
    """Обертка jsonify с поддержкой datetime"""
    return flask_jsonify(*args, **kwargs)

# Добавление фильтра tojson для Jinja2 с поддержкой datetime
def datetime_handler(obj):
    """Конвертер для datetime объектов в JSON"""
    if isinstance(obj, datetime):
        return obj.strftime('%Y-%m-%d %H:%M:%S')
    elif hasattr(obj, 'isoformat'):
        return obj.isoformat()
    return str(obj)

@app.template_filter('tojson')
def tojson_filter(data):
    return json.dumps(data, ensure_ascii=False, default=datetime_handler)

# Конфигурация базы данных
DATABASE_CONFIG = {
    'host': 'localhost',
    'port': 5432,
    'database': 'access_control_db',
    'user': 'postgres',
    'password': '300307',
    'client_encoding': 'utf8'
}

# Инициализация менеджера backup
backup_manager = BackupManager(DATABASE_CONFIG)

# ======================
# Автоматическое резервное копирование
# ======================

def scheduled_backup():
    """Функция для автоматического создания backup"""
    try:
        app.logger.info("=" * 60)
        app.logger.info("Запуск автоматического резервного копирования...")
        result = backup_manager.full_backup(format='custom', compress=True)
        
        if result.get('success'):
            app.logger.info(f"✅ Автоматический backup успешно создан: {result['backup_id']}")
            app.logger.info(f"   Путь: {result.get('path', 'N/A')}")
            app.logger.info(f"   Размер: {result.get('size_bytes', 0) / (1024*1024):.2f} MB")
            app.logger.info(f"   Длительность: {result.get('duration_seconds', 0):.2f} секунд")
            
            # Опциональная очистка старых backup (старше 7 дней)
            try:
                from datetime import timedelta
                cutoff_date = datetime.now() - timedelta(days=7)
                backups = backup_manager.list_backups()
                deleted_count = 0
                
                for backup in backups:
                    created_str = backup.get('created_at', '')
                    if created_str:
                        try:
                            created_date = datetime.fromisoformat(created_str.replace('Z', '+00:00'))
                            if created_date.replace(tzinfo=None) < cutoff_date:
                                delete_result = backup_manager.delete_backup(backup['id'])
                                if delete_result.get('success'):
                                    deleted_count += 1
                                    app.logger.info(f"   Удален старый backup: {backup['id']}")
                        except:
                            pass
                
                if deleted_count > 0:
                    app.logger.info(f"   Удалено старых backup: {deleted_count}")
            except Exception as cleanup_error:
                app.logger.warning(f"   Предупреждение при очистке старых backup: {str(cleanup_error)}")
        else:
            app.logger.error(f"❌ Ошибка автоматического backup: {result.get('error', 'Неизвестная ошибка')}")
        app.logger.info("=" * 60)
    except Exception as e:
        app.logger.error(f"❌ Критическая ошибка при автоматическом backup: {str(e)}", exc_info=True)

# Инициализация планировщика задач
scheduler = None

if APSCHEDULER_AVAILABLE:
    try:
        scheduler = BackgroundScheduler()
        scheduler.add_job(
            func=scheduled_backup,
            trigger=IntervalTrigger(hours=1),  # Каждый час
            id='auto_backup_job',
            name='Автоматическое резервное копирование каждый час',
            replace_existing=True
        )
        
        # Запуск планировщика
        scheduler.start()
        app.logger.info("=" * 60)
        app.logger.info("✅ Планировщик автоматического резервного копирования запущен")
        app.logger.info("   Расписание: каждый час")
        app.logger.info("   Формат: custom (сжатый)")
        app.logger.info("   Очистка старых backup: автоматически (старше 7 дней)")
        app.logger.info("=" * 60)
    except Exception as e:
        app.logger.error(f"❌ Ошибка запуска планировщика: {str(e)}", exc_info=True)
        scheduler = None
else:
    app.logger.warning("=" * 60)
    app.logger.warning("⚠️  Автоматическое резервное копирование отключено")
    app.logger.warning("   APScheduler не установлен")
    app.logger.warning("   Установите: pip install APScheduler==3.10.4")
    app.logger.warning("=" * 60)

# Остановка планировщика при выходе из приложения
def shutdown_scheduler():
    """Остановка планировщика при выходе"""
    try:
        if scheduler and scheduler.running:
            scheduler.shutdown()
            app.logger.info("Планировщик автоматического резервного копирования остановлен")
    except:
        pass

atexit.register(shutdown_scheduler)

def get_db_connection():
    """Создание подключения к базе данных"""
    try:
        conn = pg8000.connect(
            host='127.0.0.1',
            port=5432,
            database='access_control_db',
            user='postgres',
            password='300307'
        )
        db_logger.info(f"Успешное подключение к БД: access_control_db")
        
        # Обновление метрик
        db_active_connections.inc()
        
        return conn
    except Exception as e:
        error_msg = f"Ошибка подключения к БД: {type(e).__name__}: {e}"
        db_logger.error(error_msg, exc_info=True)
        db_operations_total.labels(operation='connect', table='', status='error').inc()
        print(error_msg)
        return None

def close_db_connection(conn):
    """Закрытие подключения к базе данных с обновлением метрик"""
    if conn:
        try:
            conn.close()
            db_active_connections.dec()
        except:
            pass

class DictCursor:
    """Обертка для курсора pg8000, эмулирующая RealDictCursor"""
    def __init__(self, cursor):
        self.cursor = cursor
        self.description = cursor.description
        self.rowcount = cursor.rowcount
    
    def execute(self, query, params=None):
        if params:
            return self.cursor.execute(query, params)
        return self.cursor.execute(query)
    
    def _convert_value(self, value):
        """Конвертирует datetime и другие типы для JSON"""
        if isinstance(value, datetime):
            return value
        return value
    
    def fetchone(self):
        row = self.cursor.fetchone()
        if not row or not self.cursor.description:
            return row
        columns = [desc[0] for desc in self.cursor.description]
        converted_row = [self._convert_value(val) for val in row]
        return dict(zip(columns, converted_row))
    
    def fetchall(self):
        rows = self.cursor.fetchall()
        if not rows or not self.cursor.description:
            return []
        columns = [desc[0] for desc in self.cursor.description]
        return [dict(zip(columns, [self._convert_value(val) for val in row])) for row in rows]
    
    def close(self):
        return self.cursor.close()

def login_required(f):
    """Декоратор для проверки авторизации"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'logged_in' not in session or not session['logged_in']:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# Хэш пароля admin123
ADMIN_PASSWORD_HASH = bcrypt.hashpw('admin123'.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

# ======================
# Автоматическая миграция БД
# ======================

def run_auto_migrations():
    """Автоматически создаёт таблицу departments если её нет, и переносит данные"""
    conn = get_db_connection()
    if not conn:
        app.logger.warning("Не удалось подключиться к БД для автомиграции")
        return

    try:
        cursor = DictCursor(conn.cursor())

        # Создаём таблицу departments если не существует
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS departments (
                id SERIAL PRIMARY KEY,
                name VARCHAR(100) NOT NULL UNIQUE,
                description TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Создаём индекс если не существует
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_departments_name ON departments(name)
        """)

        # Переносим существующие отделы из employees (если их ещё нет в departments)
        cursor.execute("""
            INSERT INTO departments (name)
            SELECT DISTINCT department
            FROM employees
            WHERE department IS NOT NULL AND department != ''
            AND department NOT IN (SELECT name FROM departments)
        """)

        conn.commit()
        cursor.close()
        close_db_connection(conn)
        app.logger.info("✓ Автомиграция departments выполнена успешно")

    except Exception as e:
        conn.rollback()
        app.logger.error(f"Ошибка автомиграции: {str(e)}", exc_info=True)
        close_db_connection(conn)

# Запускаем миграцию при старте
run_auto_migrations()

@app.route('/')
def index():
    if 'logged_in' in session and session['logged_in']:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        if username == 'admin' and bcrypt.checkpw(password.encode('utf-8'), ADMIN_PASSWORD_HASH.encode('utf-8')):
            session['logged_in'] = True
            session['username'] = username
            flash('Успешная авторизация', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Неверный логин или пароль', 'error')
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('Вы вышли из системы', 'info')
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    conn = get_db_connection()
    if not conn:
        flash('Ошибка подключения к базе данных', 'error')
        return render_template('index.html', stats={})
    
    try:
        cursor = DictCursor(conn.cursor())
        
        # Статистика
        cursor.execute("SELECT COUNT(*) as count FROM employees WHERE is_active = TRUE")
        stats = cursor.fetchone()
        stats['employees'] = stats['count']
        
        cursor.execute("SELECT COUNT(*) as count FROM access_keys WHERE is_active = TRUE")
        stats['keys'] = cursor.fetchone()['count']
        
        cursor.execute("SELECT COUNT(*) as count FROM access_points")
        stats['points'] = cursor.fetchone()['count']
        
        cursor.execute("""
            SELECT COUNT(*) as count FROM access_logs 
            WHERE access_time >= CURRENT_DATE
        """)
        stats['today_logs'] = cursor.fetchone()['count']
        
        cursor.execute("""
            SELECT COUNT(*) as count FROM access_logs 
            WHERE access_result = 'granted' AND access_time >= CURRENT_DATE
        """)
        stats['today_granted'] = cursor.fetchone()['count']
        
        # Последние логи
        cursor.execute("""
            SELECT al.*, e.full_name, ap.name as point_name, ak.key_identifier, alvl.name as level_name
            FROM access_logs al
            JOIN employees e ON al.employee_id = e.id
            JOIN access_points ap ON al.access_point_id = ap.id
            JOIN access_keys ak ON al.access_key_id = ak.id
            JOIN access_levels alvl ON al.access_level_id = alvl.id
            ORDER BY al.access_time DESC
            LIMIT 10
        """)
        recent_logs = cursor.fetchall()
        
        cursor.close()
        close_db_connection(conn)
        
        return render_template('index.html', stats=stats, recent_logs=recent_logs)
        
    except Exception as e:
        app.logger.error(f"Ошибка получения данных для дашборда: {str(e)}", exc_info=True)
        flash(f'Ошибка получения данных: {str(e)}', 'error')
        if 'conn' in locals() and conn:
            close_db_connection(conn)
        return render_template('index.html', stats={}, recent_logs=[])

# ======================
# CRUD для сотрудников
# ======================

@app.route('/employees')
@login_required
def employees():
    conn = get_db_connection()
    if not conn:
        return render_template('employees.html', employees=[])
    
    try:
        cursor = DictCursor(conn.cursor())
        cursor.execute("SELECT * FROM employees ORDER BY id")
        employees = cursor.fetchall()
        cursor.close()
        close_db_connection(conn)
        return render_template('employees.html', employees=employees)
    except Exception as e:
        app.logger.error(f"Ошибка при получении списка сотрудников: {str(e)}", exc_info=True)
        flash(f'Ошибка: {str(e)}', 'error')
        if 'conn' in locals() and conn:
            close_db_connection(conn)
        return render_template('employees.html', employees=[])

@app.route('/api/employees', methods=['POST'])
@login_required
def create_employee():
    data = request.json
    app.logger.info(f"Попытка создания сотрудника: {data.get('full_name', 'N/A')}")
    
    # Валидация данных
    validation_errors = validate_employee_data(data)
    if validation_errors:
        app.logger.warning(f"Ошибки валидации при создании сотрудника: {validation_errors}")
        return jsonify({'success': False, 'error': 'Ошибки валидации', 'errors': validation_errors})
    
    conn = get_db_connection()
    if not conn:
        error_msg = "Ошибка подключения к базе данных"
        app.logger.error(error_msg)
        return jsonify({'success': False, 'error': error_msg})
    
    try:
        # Начало транзакции
        cursor = DictCursor(conn.cursor())
        
        cursor.execute("""
            INSERT INTO employees (full_name, position, department, phone, email, is_active)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (data['full_name'], data['position'], data.get('department'), 
              data.get('phone'), data.get('email'), data.get('is_active', True)))
        employee_id = cursor.fetchone()['id']
        
        # Коммит транзакции
        conn.commit()
        app.logger.info(f"Сотрудник успешно создан: ID={employee_id}, ФИО={data['full_name']}")
        db_operations_total.labels(operation='create', table='employees', status='success').inc()
        cursor.close()
        close_db_connection(conn)
        return jsonify({'success': True, 'id': employee_id})
    except Exception as e:
        # Откат транзакции при ошибке
        conn.rollback()
        error_msg = f"Ошибка при создании сотрудника: {str(e)}"
        app.logger.error(error_msg, exc_info=True)
        db_operations_total.labels(operation='create', table='employees', status='error').inc()
        cursor.close()
        close_db_connection(conn)
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/employees/<int:employee_id>', methods=['PUT'])
@login_required
def update_employee(employee_id):
    data = request.json
    app.logger.info(f"Попытка обновления сотрудника ID={employee_id}")
    
    # Валидация данных
    validation_errors = validate_employee_data(data)
    if validation_errors:
        app.logger.warning(f"Ошибки валидации при обновлении сотрудника ID={employee_id}: {validation_errors}")
        return jsonify({'success': False, 'error': 'Ошибки валидации', 'errors': validation_errors})
    
    conn = get_db_connection()
    if not conn:
        error_msg = "Ошибка подключения к базе данных"
        app.logger.error(error_msg)
        return jsonify({'success': False, 'error': error_msg})
    
    try:
        cursor = DictCursor(conn.cursor())
        cursor.execute("""
            UPDATE employees 
            SET full_name=%s, position=%s, department=%s, phone=%s, email=%s, is_active=%s, updated_at=CURRENT_TIMESTAMP
            WHERE id=%s
        """, (data['full_name'], data.get('position'), data.get('department'), 
              data.get('phone'), data.get('email'), data.get('is_active', True), employee_id))
        conn.commit()
        app.logger.info(f"Сотрудник успешно обновлен: ID={employee_id}")
        db_operations_total.labels(operation='update', table='employees', status='success').inc()
        cursor.close()
        close_db_connection(conn)
        return jsonify({'success': True})
    except Exception as e:
        conn.rollback()
        error_msg = f"Ошибка при обновлении сотрудника ID={employee_id}: {str(e)}"
        app.logger.error(error_msg, exc_info=True)
        db_operations_total.labels(operation='update', table='employees', status='error').inc()
        cursor.close()
        close_db_connection(conn)
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/employees/<int:employee_id>', methods=['DELETE'])
@login_required
def delete_employee(employee_id):
    app.logger.info(f"Попытка удаления сотрудника ID={employee_id}")
    conn = get_db_connection()
    
    if not conn:
        error_msg = "Ошибка подключения к базе данных"
        app.logger.error(error_msg)
        return jsonify({'success': False, 'error': error_msg})
    
    try:
        cursor = DictCursor(conn.cursor())
        cursor.execute("DELETE FROM employees WHERE id=%s", (employee_id,))
        conn.commit()
        app.logger.info(f"Сотрудник успешно удален: ID={employee_id}")
        db_operations_total.labels(operation='delete', table='employees', status='success').inc()
        cursor.close()
        close_db_connection(conn)
        return jsonify({'success': True})
    except Exception as e:
        conn.rollback()
        error_msg = f"Ошибка при удалении сотрудника ID={employee_id}: {str(e)}"
        app.logger.error(error_msg, exc_info=True)
        db_operations_total.labels(operation='delete', table='employees', status='error').inc()
        cursor.close()
        close_db_connection(conn)
        return jsonify({'success': False, 'error': str(e)})

# ======================
# API для отделов
# ======================

@app.route('/api/departments', methods=['GET'])
@login_required
def get_departments():
    """Получение списка отделов из таблицы departments"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'success': False, 'error': 'Ошибка подключения к базе данных'})
    
    try:
        cursor = DictCursor(conn.cursor())
        
        # Проверяем, существует ли таблица departments
        cursor.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_name = 'departments'
            )
        """)
        table_exists = cursor.fetchone()['exists']
        
        if table_exists:
            # Берем из таблицы departments
            cursor.execute("""
                SELECT name 
                FROM departments 
                ORDER BY name
            """)
            departments = [row['name'] for row in cursor.fetchall()]
        else:
            # Берем из employees (для обратной совместимости)
            cursor.execute("""
                SELECT DISTINCT department as name
                FROM employees 
                WHERE department IS NOT NULL AND department != ''
                ORDER BY department
            """)
            departments = [row['name'] for row in cursor.fetchall()]
        
        cursor.close()
        close_db_connection(conn)
        return jsonify({'success': True, 'departments': departments})
    except Exception as e:
        app.logger.error(f"Ошибка при получении списка отделов: {str(e)}", exc_info=True)
        if 'conn' in locals() and conn:
            close_db_connection(conn)
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/departments', methods=['POST'])
@login_required
def create_department():
    """Создание нового отдела и сохранение в таблицу departments"""
    data = request.json
    department_name = data.get('name', '').strip()
    
    if not department_name:
        return jsonify({'success': False, 'error': 'Название отдела обязательно'})
    
    if len(department_name) < 2:
        return jsonify({'success': False, 'error': 'Название отдела должно быть не менее 2 символов'})
    
    conn = get_db_connection()
    if not conn:
        return jsonify({'success': False, 'error': 'Ошибка подключения к базе данных'})
    
    try:
        cursor = DictCursor(conn.cursor())
        
        # Проверяем, существует ли таблица departments
        cursor.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_name = 'departments'
            )
        """)
        table_exists = cursor.fetchone()['exists']
        
        if table_exists:
            # Проверяем уникальность в таблице departments
            cursor.execute("""
                SELECT COUNT(*) as count 
                FROM departments 
                WHERE LOWER(name) = LOWER(%s)
            """, (department_name,))
            result = cursor.fetchone()
            
            if result['count'] > 0:
                cursor.close()
                close_db_connection(conn)
                return jsonify({'success': False, 'error': 'Отдел с таким названием уже существует'})
            
            # Сохраняем новый отдел в таблицу departments
            cursor.execute("""
                INSERT INTO departments (name, description)
                VALUES (%s, %s)
                RETURNING id
            """, (department_name, data.get('description', '')))
            department_id = cursor.fetchone()['id']
            conn.commit()
            
            app.logger.info(f"✓ Новый отдел создан и сохранен в БД: ID={department_id}, name={department_name}")
            db_operations_total.labels(operation='create', table='departments', status='success').inc()
            cursor.close()
            close_db_connection(conn)
            return jsonify({'success': True, 'department': department_name, 'id': department_id})
        else:
            # Если таблицы departments нет
            cursor.execute("""
                SELECT COUNT(*) as count 
                FROM employees 
                WHERE LOWER(department) = LOWER(%s)
            """, (department_name,))
            result = cursor.fetchone()
            
            if result['count'] > 0:
                cursor.close()
                close_db_connection(conn)
                return jsonify({'success': False, 'error': 'Отдел с таким названием уже существует'})
            
            cursor.close()
            close_db_connection(conn)
            app.logger.info(f"Новый отдел готов к использованию (таблица departments не создана): {department_name}")
            return jsonify({'success': True, 'department': department_name})
        
    except Exception as e:
        conn.rollback()
        app.logger.error(f"Ошибка при создании отдела: {str(e)}", exc_info=True)
        db_operations_total.labels(operation='create', table='departments', status='error').inc()
        if 'conn' in locals() and conn:
            close_db_connection(conn)
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/departments/<path:dept_name>', methods=['DELETE'])
@login_required
def delete_department(dept_name):
    """Удаление отдела из таблицы departments"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'success': False, 'error': 'Ошибка подключения к базе данных'})

    try:
        cursor = DictCursor(conn.cursor())

        # Считаем сколько сотрудников в этом отделе
        cursor.execute("""
            SELECT COUNT(*) as count FROM employees WHERE department = %s
        """, (dept_name,))
        emp_count = cursor.fetchone()['count']

        if emp_count > 0:
            force = request.args.get('force', 'false').lower() == 'true'
            if not force:
                cursor.close()
                close_db_connection(conn)
                return jsonify({
                    'success': False,
                    'needs_confirm': True,
                    'employees_count': emp_count,
                    'error': f'Отдел используется {emp_count} сотрудниками'
                })
            # force=true: убираем отдел у сотрудников
            cursor.execute("""
                UPDATE employees SET department = NULL WHERE department = %s
            """, (dept_name,))

        # Удаляем из таблицы departments
        cursor.execute("DELETE FROM departments WHERE name = %s", (dept_name,))
        conn.commit()

        app.logger.info(f"✓ Отдел удалён: {dept_name}")
        cursor.close()
        close_db_connection(conn)
        return jsonify({'success': True})

    except Exception as e:
        conn.rollback()
        app.logger.error(f"Ошибка при удалении отдела: {str(e)}", exc_info=True)
        if 'conn' in locals() and conn:
            close_db_connection(conn)
        return jsonify({'success': False, 'error': str(e)})


# ======================
# CRUD для ключей
# ======================

@app.route('/keys')
@login_required
def keys():
    conn = get_db_connection()
    if not conn:
        return render_template('keys.html', keys=[])
    
    try:
        cursor = DictCursor(conn.cursor())
        cursor.execute("""
            SELECT ak.*, e.full_name as employee_name
            FROM access_keys ak
            JOIN employees e ON ak.employee_id = e.id
            ORDER BY ak.id
        """)
        keys = cursor.fetchall()
        
        cursor.execute("SELECT id, full_name FROM employees ORDER BY full_name")
        employees = cursor.fetchall()
        
        cursor.close()
        close_db_connection(conn)
        return render_template('keys.html', keys=keys, employees=employees)
    except Exception as e:
        app.logger.error(f"Ошибка при получении списка ключей: {str(e)}", exc_info=True)
        if 'conn' in locals() and conn:
            close_db_connection(conn)
        return render_template('keys.html', keys=[], employees=[])

@app.route('/api/keys', methods=['POST'])
@login_required
def create_key():
    data = request.json
    app.logger.info(f"Попытка создания ключа: {data.get('key_identifier', 'N/A')}")
    
    # Валидация данных
    validation_errors = validate_key_data(data)
    if validation_errors:
        app.logger.warning(f"Ошибки валидации при создании ключа: {validation_errors}")
        return jsonify({'success': False, 'error': 'Ошибки валидации', 'errors': validation_errors})
    
    conn = get_db_connection()
    if not conn:
        error_msg = "Ошибка подключения к базе данных"
        app.logger.error(error_msg)
        return jsonify({'success': False, 'error': error_msg})
    
    try:
        cursor = DictCursor(conn.cursor())
        cursor.execute("""
            INSERT INTO access_keys (employee_id, key_identifier, key_type, expiry_date, is_active)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
        """, (data['employee_id'], data['key_identifier'], data.get('key_type', 'RFID'), 
              data.get('expiry_date') or None, data.get('is_active', True)))
        key_id = cursor.fetchone()['id']
        conn.commit()
        app.logger.info(f"Ключ успешно создан: ID={key_id}, identifier={data['key_identifier']}")
        db_operations_total.labels(operation='create', table='access_keys', status='success').inc()
        cursor.close()
        close_db_connection(conn)
        return jsonify({'success': True, 'id': key_id})
    except Exception as e:
        conn.rollback()
        error_msg = f"Ошибка при создании ключа: {str(e)}"
        app.logger.error(error_msg, exc_info=True)
        db_operations_total.labels(operation='create', table='access_keys', status='error').inc()
        cursor.close()
        close_db_connection(conn)
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/keys/<int:key_id>', methods=['PUT'])
@login_required
def update_key(key_id):
    data = request.json
    app.logger.info(f"Попытка обновления ключа ID={key_id}")
    
    # Валидация данных
    validation_errors = validate_key_data(data)
    if validation_errors:
        app.logger.warning(f"Ошибки валидации при обновлении ключа ID={key_id}: {validation_errors}")
        return jsonify({'success': False, 'error': 'Ошибки валидации', 'errors': validation_errors})
    
    conn = get_db_connection()
    if not conn:
        error_msg = "Ошибка подключения к базе данных"
        app.logger.error(error_msg)
        return jsonify({'success': False, 'error': error_msg})
    
    try:
        cursor = DictCursor(conn.cursor())
        cursor.execute("""
            UPDATE access_keys 
            SET key_identifier=%s, key_type=%s, expiry_date=%s, is_active=%s
            WHERE id=%s
        """, (data['key_identifier'], data.get('key_type', 'RFID'), 
              data.get('expiry_date') or None, data.get('is_active', True), key_id))
        conn.commit()
        app.logger.info(f"Ключ успешно обновлен: ID={key_id}")
        db_operations_total.labels(operation='update', table='access_keys', status='success').inc()
        cursor.close()
        close_db_connection(conn)
        return jsonify({'success': True})
    except Exception as e:
        conn.rollback()
        error_msg = f"Ошибка при обновлении ключа ID={key_id}: {str(e)}"
        app.logger.error(error_msg, exc_info=True)
        db_operations_total.labels(operation='update', table='access_keys', status='error').inc()
        cursor.close()
        close_db_connection(conn)
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/keys/<int:key_id>', methods=['DELETE'])
@login_required
def delete_key(key_id):
    app.logger.info(f"Попытка удаления ключа ID={key_id}")
    conn = get_db_connection()
    
    if not conn:
        error_msg = "Ошибка подключения к базе данных"
        app.logger.error(error_msg)
        return jsonify({'success': False, 'error': error_msg})
    
    try:
        cursor = DictCursor(conn.cursor())
        cursor.execute("DELETE FROM access_keys WHERE id=%s", (key_id,))
        conn.commit()
        app.logger.info(f"Ключ успешно удален: ID={key_id}")
        db_operations_total.labels(operation='delete', table='access_keys', status='success').inc()
        cursor.close()
        close_db_connection(conn)
        return jsonify({'success': True})
    except Exception as e:
        conn.rollback()
        error_msg = f"Ошибка при удалении ключа ID={key_id}: {str(e)}"
        app.logger.error(error_msg, exc_info=True)
        db_operations_total.labels(operation='delete', table='access_keys', status='error').inc()
        cursor.close()
        close_db_connection(conn)
        return jsonify({'success': False, 'error': str(e)})

# ======================
# CRUD для точек доступа
# ======================

@app.route('/points')
@login_required
def points():
    conn = get_db_connection()
    if not conn:
        return render_template('points.html', points=[])
    
    try:
        cursor = DictCursor(conn.cursor())
        cursor.execute("SELECT * FROM access_points ORDER BY id")
        points = cursor.fetchall()
        cursor.close()
        close_db_connection(conn)
        return render_template('points.html', points=points)
    except Exception as e:
        app.logger.error(f"Ошибка при получении списка точек доступа: {str(e)}", exc_info=True)
        if 'conn' in locals() and conn:
            close_db_connection(conn)
        return render_template('points.html', points=[])

@app.route('/api/points', methods=['POST'])
@login_required
def create_point():
    data = request.json
    app.logger.info(f"Попытка создания точки доступа: {data.get('name', 'N/A')}")
    
    # Валидация
    if not data.get('name') or len(data.get('name', '').strip()) < 2:
        return jsonify({'success': False, 'error': 'Название точки доступа обязательно (минимум 2 символа)'})
    
    conn = get_db_connection()
    if not conn:
        error_msg = "Ошибка подключения к базе данных"
        app.logger.error(error_msg)
        return jsonify({'success': False, 'error': error_msg})
    
    try:
        cursor = DictCursor(conn.cursor())
        cursor.execute("""
            INSERT INTO access_points (name, location, description)
            VALUES (%s, %s, %s)
            RETURNING id
        """, (data['name'], data.get('location'), data.get('description')))
        point_id = cursor.fetchone()['id']
        conn.commit()
        app.logger.info(f"Точка доступа успешно создана: ID={point_id}, name={data['name']}")
        db_operations_total.labels(operation='create', table='access_points', status='success').inc()
        cursor.close()
        close_db_connection(conn)
        return jsonify({'success': True, 'id': point_id})
    except Exception as e:
        conn.rollback()
        error_msg = f"Ошибка при создании точки доступа: {str(e)}"
        app.logger.error(error_msg, exc_info=True)
        db_operations_total.labels(operation='create', table='access_points', status='error').inc()
        cursor.close()
        close_db_connection(conn)
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/points/<int:point_id>', methods=['PUT'])
@login_required
def update_point(point_id):
    data = request.json
    app.logger.info(f"Попытка обновления точки доступа ID={point_id}")
    
    # Валидация
    if not data.get('name') or len(data.get('name', '').strip()) < 2:
        return jsonify({'success': False, 'error': 'Название точки доступа обязательно (минимум 2 символа)'})
    
    conn = get_db_connection()
    if not conn:
        error_msg = "Ошибка подключения к базе данных"
        app.logger.error(error_msg)
        return jsonify({'success': False, 'error': error_msg})
    
    try:
        cursor = DictCursor(conn.cursor())
        cursor.execute("""
            UPDATE access_points 
            SET name=%s, location=%s, description=%s
            WHERE id=%s
        """, (data['name'], data.get('location'), data.get('description'), point_id))
        conn.commit()
        app.logger.info(f"Точка доступа успешно обновлена: ID={point_id}")
        db_operations_total.labels(operation='update', table='access_points', status='success').inc()
        cursor.close()
        close_db_connection(conn)
        return jsonify({'success': True})
    except Exception as e:
        conn.rollback()
        error_msg = f"Ошибка при обновлении точки доступа ID={point_id}: {str(e)}"
        app.logger.error(error_msg, exc_info=True)
        db_operations_total.labels(operation='update', table='access_points', status='error').inc()
        cursor.close()
        close_db_connection(conn)
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/points/<int:point_id>', methods=['DELETE'])
@login_required
def delete_point(point_id):
    app.logger.info(f"Попытка удаления точки доступа ID={point_id}")
    conn = get_db_connection()
    
    if not conn:
        error_msg = "Ошибка подключения к базе данных"
        app.logger.error(error_msg)
        return jsonify({'success': False, 'error': error_msg})
    
    try:
        cursor = DictCursor(conn.cursor())
        cursor.execute("DELETE FROM access_points WHERE id=%s", (point_id,))
        conn.commit()
        app.logger.info(f"Точка доступа успешно удалена: ID={point_id}")
        db_operations_total.labels(operation='delete', table='access_points', status='success').inc()
        cursor.close()
        close_db_connection(conn)
        return jsonify({'success': True})
    except Exception as e:
        conn.rollback()
        error_msg = f"Ошибка при удалении точки доступа ID={point_id}: {str(e)}"
        app.logger.error(error_msg, exc_info=True)
        db_operations_total.labels(operation='delete', table='access_points', status='error').inc()
        cursor.close()
        close_db_connection(conn)
        return jsonify({'success': False, 'error': str(e)})

# ======================
# CRUD для уровней доступа
# ======================

@app.route('/levels')
@login_required
def levels():
    conn = get_db_connection()
    if not conn:
        return render_template('levels.html', levels=[])
    
    try:
        cursor = DictCursor(conn.cursor())
        cursor.execute("SELECT * FROM access_levels ORDER BY id")
        levels = cursor.fetchall()
        cursor.close()
        close_db_connection(conn)
        return render_template('levels.html', levels=levels)
    except Exception as e:
        app.logger.error(f"Ошибка при получении списка уровней доступа: {str(e)}", exc_info=True)
        if 'conn' in locals() and conn:
            close_db_connection(conn)
        return render_template('levels.html', levels=[])

@app.route('/api/levels', methods=['POST'])
@login_required
def create_level():
    data = request.json
    app.logger.info(f"Попытка создания уровня доступа: {data.get('name', 'N/A')}")
    
    # Валидация
    if not data.get('name') or len(data.get('name', '').strip()) < 2:
        return jsonify({'success': False, 'error': 'Название уровня доступа обязательно (минимум 2 символа)'})
    
    conn = get_db_connection()
    if not conn:
        error_msg = "Ошибка подключения к базе данных"
        app.logger.error(error_msg)
        return jsonify({'success': False, 'error': error_msg})
    
    try:
        cursor = DictCursor(conn.cursor())
        cursor.execute("""
            INSERT INTO access_levels (name, description)
            VALUES (%s, %s)
            RETURNING id
        """, (data['name'], data.get('description')))
        level_id = cursor.fetchone()['id']
        conn.commit()
        app.logger.info(f"Уровень доступа успешно создан: ID={level_id}, name={data['name']}")
        db_operations_total.labels(operation='create', table='access_levels', status='success').inc()
        cursor.close()
        close_db_connection(conn)
        return jsonify({'success': True, 'id': level_id})
    except Exception as e:
        conn.rollback()
        error_msg = f"Ошибка при создании уровня доступа: {str(e)}"
        app.logger.error(error_msg, exc_info=True)
        db_operations_total.labels(operation='create', table='access_levels', status='error').inc()
        cursor.close()
        close_db_connection(conn)
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/levels/<int:level_id>', methods=['PUT'])
@login_required
def update_level(level_id):
    data = request.json
    app.logger.info(f"Попытка обновления уровня доступа ID={level_id}")
    
    # Валидация
    if not data.get('name') or len(data.get('name', '').strip()) < 2:
        return jsonify({'success': False, 'error': 'Название уровня доступа обязательно (минимум 2 символа)'})
    
    conn = get_db_connection()
    if not conn:
        error_msg = "Ошибка подключения к базе данных"
        app.logger.error(error_msg)
        return jsonify({'success': False, 'error': error_msg})
    
    try:
        cursor = DictCursor(conn.cursor())
        cursor.execute("""
            UPDATE access_levels 
            SET name=%s, description=%s
            WHERE id=%s
        """, (data['name'], data.get('description'), level_id))
        conn.commit()
        app.logger.info(f"Уровень доступа успешно обновлен: ID={level_id}")
        db_operations_total.labels(operation='update', table='access_levels', status='success').inc()
        cursor.close()
        close_db_connection(conn)
        return jsonify({'success': True})
    except Exception as e:
        conn.rollback()
        error_msg = f"Ошибка при обновлении уровня доступа ID={level_id}: {str(e)}"
        app.logger.error(error_msg, exc_info=True)
        db_operations_total.labels(operation='update', table='access_levels', status='error').inc()
        cursor.close()
        close_db_connection(conn)
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/levels/<int:level_id>', methods=['DELETE'])
@login_required
def delete_level(level_id):
    app.logger.info(f"Попытка удаления уровня доступа ID={level_id}")
    conn = get_db_connection()
    
    if not conn:
        error_msg = "Ошибка подключения к базе данных"
        app.logger.error(error_msg)
        return jsonify({'success': False, 'error': error_msg})
    
    try:
        cursor = DictCursor(conn.cursor())
        cursor.execute("DELETE FROM access_levels WHERE id=%s", (level_id,))
        conn.commit()
        app.logger.info(f"Уровень доступа успешно удален: ID={level_id}")
        db_operations_total.labels(operation='delete', table='access_levels', status='success').inc()
        cursor.close()
        close_db_connection(conn)
        return jsonify({'success': True})
    except Exception as e:
        conn.rollback()
        error_msg = f"Ошибка при удалении уровня доступа ID={level_id}: {str(e)}"
        app.logger.error(error_msg, exc_info=True)
        db_operations_total.labels(operation='delete', table='access_levels', status='error').inc()
        cursor.close()
        close_db_connection(conn)
        return jsonify({'success': False, 'error': str(e)})

# ======================
# CRUD для групп
# ======================

@app.route('/groups')
@login_required
def groups():
    conn = get_db_connection()
    if not conn:
        return render_template('groups.html', groups=[], levels=[], employees=[])
    
    try:
        cursor = DictCursor(conn.cursor())
        
        cursor.execute("SELECT * FROM employee_groups ORDER BY id")
        groups = cursor.fetchall()
        
        cursor.execute("SELECT * FROM access_levels ORDER BY id")
        levels = cursor.fetchall()
        
        cursor.execute("SELECT id, full_name FROM employees ORDER BY full_name")
        employees = cursor.fetchall()
        
        # Получаем связи групп и уровней
        for group in groups:
            cursor.execute("""
                SELECT access_level_id FROM group_access_levels 
                WHERE group_id = %s
            """, (group['id'],))
            group['levels'] = [row['access_level_id'] for row in cursor.fetchall()]
            
            cursor.execute("""
                SELECT employee_id FROM group_employees 
                WHERE group_id = %s
            """, (group['id'],))
            group['employee_ids'] = [row['employee_id'] for row in cursor.fetchall()]
        
        cursor.close()
        close_db_connection(conn)
        return render_template('groups.html', groups=groups, levels=levels, employees=employees)
    except Exception as e:
        app.logger.error(f"Ошибка при получении списка групп: {str(e)}", exc_info=True)
        if 'conn' in locals() and conn:
            close_db_connection(conn)
        return render_template('groups.html', groups=[], levels=[], employees=[])

@app.route('/api/groups', methods=['POST'])
@login_required
def create_group():
    data = request.json
    app.logger.info(f"Попытка создания группы: {data.get('name', 'N/A')}")
    
    # Валидация
    if not data.get('name') or len(data.get('name', '').strip()) < 2:
        return jsonify({'success': False, 'error': 'Название группы обязательно (минимум 2 символа)'})
    
    conn = get_db_connection()
    if not conn:
        error_msg = "Ошибка подключения к базе данных"
        app.logger.error(error_msg)
        return jsonify({'success': False, 'error': error_msg})
    
    try:
        cursor = DictCursor(conn.cursor())
        cursor.execute("""
            INSERT INTO employee_groups (name, description)
            VALUES (%s, %s)
            RETURNING id
        """, (data['name'], data.get('description')))
        group_id = cursor.fetchone()['id']
        
        # Добавляем уровни доступа
        if 'levels' in data and data['levels']:
            for level_id in data['levels']:
                cursor.execute("""
                    INSERT INTO group_access_levels (group_id, access_level_id)
                    VALUES (%s, %s)
                """, (group_id, level_id))
        
        # Добавляем сотрудников
        if 'employees' in data and data['employees']:
            for employee_id in data['employees']:
                cursor.execute("""
                    INSERT INTO group_employees (group_id, employee_id)
                    VALUES (%s, %s)
                """, (group_id, employee_id))
        
        conn.commit()
        app.logger.info(f"Группа успешно создана: ID={group_id}, name={data['name']}")
        db_operations_total.labels(operation='create', table='employee_groups', status='success').inc()
        cursor.close()
        close_db_connection(conn)
        return jsonify({'success': True, 'id': group_id})
    except Exception as e:
        conn.rollback()
        error_msg = f"Ошибка при создании группы: {str(e)}"
        app.logger.error(error_msg, exc_info=True)
        db_operations_total.labels(operation='create', table='employee_groups', status='error').inc()
        cursor.close()
        close_db_connection(conn)
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/groups/<int:group_id>', methods=['PUT'])
@login_required
def update_group(group_id):
    data = request.json
    app.logger.info(f"Попытка обновления группы ID={group_id}")
    
    # Валидация
    if not data.get('name') or len(data.get('name', '').strip()) < 2:
        return jsonify({'success': False, 'error': 'Название группы обязательно (минимум 2 символа)'})
    
    conn = get_db_connection()
    if not conn:
        error_msg = "Ошибка подключения к базе данных"
        app.logger.error(error_msg)
        return jsonify({'success': False, 'error': error_msg})
    
    try:
        cursor = DictCursor(conn.cursor())
        cursor.execute("""
            UPDATE employee_groups 
            SET name=%s, description=%s
            WHERE id=%s
        """, (data['name'], data.get('description'), group_id))
        
        # Обновляем уровни доступа
        cursor.execute("DELETE FROM group_access_levels WHERE group_id=%s", (group_id,))
        if 'levels' in data and data['levels']:
            for level_id in data['levels']:
                cursor.execute("""
                    INSERT INTO group_access_levels (group_id, access_level_id)
                    VALUES (%s, %s)
                """, (group_id, level_id))
        
        # Обновляем сотрудников
        cursor.execute("DELETE FROM group_employees WHERE group_id=%s", (group_id,))
        if 'employees' in data and data['employees']:
            for employee_id in data['employees']:
                cursor.execute("""
                    INSERT INTO group_employees (group_id, employee_id)
                    VALUES (%s, %s)
                """, (group_id, employee_id))
        
        conn.commit()
        app.logger.info(f"Группа успешно обновлена: ID={group_id}")
        db_operations_total.labels(operation='update', table='employee_groups', status='success').inc()
        cursor.close()
        close_db_connection(conn)
        return jsonify({'success': True})
    except Exception as e:
        conn.rollback()
        error_msg = f"Ошибка при обновлении группы ID={group_id}: {str(e)}"
        app.logger.error(error_msg, exc_info=True)
        db_operations_total.labels(operation='update', table='employee_groups', status='error').inc()
        cursor.close()
        close_db_connection(conn)
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/groups/<int:group_id>', methods=['DELETE'])
@login_required
def delete_group(group_id):
    app.logger.info(f"Попытка удаления группы ID={group_id}")
    conn = get_db_connection()
    
    if not conn:
        error_msg = "Ошибка подключения к базе данных"
        app.logger.error(error_msg)
        return jsonify({'success': False, 'error': error_msg})
    
    try:
        cursor = DictCursor(conn.cursor())
        cursor.execute("DELETE FROM employee_groups WHERE id=%s", (group_id,))
        conn.commit()
        app.logger.info(f"Группа успешно удалена: ID={group_id}")
        db_operations_total.labels(operation='delete', table='employee_groups', status='success').inc()
        cursor.close()
        close_db_connection(conn)
        return jsonify({'success': True})
    except Exception as e:
        conn.rollback()
        error_msg = f"Ошибка при удалении группы ID={group_id}: {str(e)}"
        app.logger.error(error_msg, exc_info=True)
        db_operations_total.labels(operation='delete', table='employee_groups', status='error').inc()
        cursor.close()
        close_db_connection(conn)
        return jsonify({'success': False, 'error': str(e)})

# ======================
# Логи
# ======================

@app.route('/logs')
@login_required
def logs():
    conn = get_db_connection()
    if not conn:
        return render_template('logs.html', logs=[], employees=[], points=[], results=[])
    
    try:
        cursor = DictCursor(conn.cursor())
        
        # Получаем параметры фильтрации
        employee_id = request.args.get('employee_id', '')
        point_id = request.args.get('point_id', '')
        result = request.args.get('result', '')
        date_from = request.args.get('date_from', '')
        date_to = request.args.get('date_to', '')
        
        # Строим запрос
        query = """
            SELECT al.*, e.full_name, ap.name as point_name, ak.key_identifier, alvl.name as level_name
            FROM access_logs al
            JOIN employees e ON al.employee_id = e.id
            JOIN access_points ap ON al.access_point_id = ap.id
            JOIN access_keys ak ON al.access_key_id = ak.id
            JOIN access_levels alvl ON al.access_level_id = alvl.id
            WHERE 1=1
        """
        params = []
        
        if employee_id:
            query += " AND al.employee_id = %s"
            params.append(employee_id)
        if point_id:
            query += " AND al.access_point_id = %s"
            params.append(point_id)
        if result:
            query += " AND al.access_result = %s"
            params.append(result)
        if date_from:
            query += " AND al.access_time >= %s"
            params.append(date_from)
        if date_to:
            query += " AND al.access_time <= %s"
            params.append(date_to)
        
        query += " ORDER BY al.access_time DESC LIMIT 1000"
        
        cursor.execute(query, params)
        logs = cursor.fetchall()
        
        # Для фильтров
        cursor.execute("SELECT id, full_name FROM employees ORDER BY full_name")
        employees = cursor.fetchall()
        
        cursor.execute("SELECT id, name FROM access_points ORDER BY name")
        points = cursor.fetchall()
        
        results = ['granted', 'denied', 'expired', 'inactive']
        
        cursor.close()
        close_db_connection(conn)
        app.logger.info(f"Просмотр логов: фильтры - employee_id={employee_id}, point_id={point_id}, result={result}")
        return render_template('logs.html', logs=logs, employees=employees, 
                             points=points, results=results,
                             filter_employee_id=employee_id, filter_point_id=point_id,
                             filter_result=result, filter_date_from=date_from, 
                             filter_date_to=date_to)
    except Exception as e:
        app.logger.error(f"Ошибка при получении логов: {str(e)}", exc_info=True)
        if 'conn' in locals() and conn:
            close_db_connection(conn)
        return render_template('logs.html', logs=[], employees=[], points=[], results=[])

@app.route('/logs/export')
@login_required
def export_logs():
    conn = get_db_connection()
    
    try:
        cursor = DictCursor(conn.cursor())
        
        # Применяем те же фильтры
        employee_id = request.args.get('employee_id', '')
        point_id = request.args.get('point_id', '')
        result = request.args.get('result', '')
        date_from = request.args.get('date_from', '')
        date_to = request.args.get('date_to', '')
        
        query = """
            SELECT al.access_time, e.full_name as employee, ap.name as point, 
                   ak.key_identifier as key, alvl.name as level,
                   al.access_result as result, al.reason
            FROM access_logs al
            JOIN employees e ON al.employee_id = e.id
            JOIN access_points ap ON al.access_point_id = ap.id
            JOIN access_keys ak ON al.access_key_id = ak.id
            JOIN access_levels alvl ON al.access_level_id = alvl.id
            WHERE 1=1
        """
        params = []
        
        if employee_id:
            query += " AND al.employee_id = %s"
            params.append(employee_id)
        if point_id:
            query += " AND al.access_point_id = %s"
            params.append(point_id)
        if result:
            query += " AND al.access_result = %s"
            params.append(result)
        if date_from:
            query += " AND al.access_time >= %s"
            params.append(date_from)
        if date_to:
            query += " AND al.access_time <= %s"
            params.append(date_to)
        
        query += " ORDER BY al.access_time DESC"
        
        cursor.execute(query, params)
        logs = cursor.fetchall()
        
        # Создаем CSV
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Заголовки
        writer.writerow(['Время', 'Сотрудник', 'Точка доступа', 'Ключ', 'Уровень', 'Результат', 'Причина'])
        
        # Данные
        for log in logs:
            writer.writerow([
                log['access_time'].strftime('%Y-%m-%d %H:%M:%S') if log['access_time'] else '',
                log['employee'],
                log['point'],
                log['key'],
                log['level'],
                log['result'],
                log['reason'] or ''
            ])
        
        response = make_response(output.getvalue())
        response.headers['Content-Type'] = 'text/csv; charset=utf-8'
        response.headers['Content-Disposition'] = f'attachment; filename=logs_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
        
        cursor.close()
        close_db_connection(conn)
        
        app.logger.info(f"Экспорт логов выполнен: {len(logs)} записей")
        return response
    except Exception as e:
        error_msg = f'Ошибка экспорта логов: {str(e)}'
        app.logger.error(error_msg, exc_info=True)
        flash(error_msg, 'error')
        if 'conn' in locals() and conn:
            close_db_connection(conn)
        return redirect(url_for('logs'))

# ======================
# Резервное копирование
# ======================

@app.route('/backup')
@login_required
def backup_index():
    """Главная страница управления резервным копированием"""
    try:
        backups = backup_manager.list_backups()
        stats = backup_manager.get_backup_statistics()
        return render_template('backup/index.html', backups=backups, stats=stats)
    except Exception as e:
        app.logger.error(f"Ошибка при получении списка backup: {str(e)}", exc_info=True)
        flash(f'Ошибка: {str(e)}', 'error')
        return render_template('backup/index.html', backups=[], stats={})

@app.route('/api/backup/create', methods=['POST'])
@login_required
def create_backup():
    """Создание полного backup"""
    try:
        data = request.json or {}
        format_type = data.get('format', 'custom')
        compress = data.get('compress', True)
        
        app.logger.info(f"Запрос на создание backup: format={format_type}, compress={compress}")
        
        result = backup_manager.full_backup(format=format_type, compress=compress)
        
        if result.get('success'):
            flash(f'Backup успешно создан: {result["backup_id"]}', 'success')
            return flask_jsonify(result)
        else:
            flash(f'Ошибка создания backup: {result.get("error", "Неизвестная ошибка")}', 'error')
            return flask_jsonify(result), 400
            
    except Exception as e:
        error_msg = f'Ошибка при создании backup: {str(e)}'
        app.logger.error(error_msg, exc_info=True)
        return flask_jsonify({'success': False, 'error': error_msg}), 500

@app.route('/api/backup/restore', methods=['POST'])
@login_required
def restore_backup():
    """Восстановление из backup"""
    try:
        data = request.json or {}
        backup_id = data.get('backup_id')
        backup_path = data.get('backup_path')  # Для обратной совместимости
        drop_existing = data.get('drop_existing', False)
        
        # Если передан ID, получаем путь из метаданных
        if backup_id:
            backups = backup_manager.list_backups()
            backup_info = None
            for b in backups:
                if b.get('id') == backup_id:
                    backup_info = b
                    break
            
            if backup_info:
                # Используем путь из метаданных или имя файла
                if backup_info.get('exists') and backup_info.get('path'):
                    backup_path = backup_info['path']
                elif backup_info.get('filename'):
                    # Если путь неправильный, используем только имя файла
                    backup_path = backup_info['filename']
                else:
                    # Последняя попытка - используем ID для поиска
                    backup_path = backup_id
                app.logger.info(f"Восстановление backup ID={backup_id}, путь={backup_path}")
            else:
                return flask_jsonify({'success': False, 'error': f'Backup с ID {backup_id} не найден'}), 400
        
        if not backup_path:
            return flask_jsonify({'success': False, 'error': 'Не указан путь к backup или ID backup'}), 400
        
        app.logger.info(f"Запрос на восстановление из: {backup_path}")
        
        result = backup_manager.restore(backup_path, drop_existing=drop_existing)
        
        if result.get('success'):
            flash('Восстановление успешно выполнено', 'success')
            return flask_jsonify(result)
        else:
            flash(f'Ошибка восстановления: {result.get("error", "Неизвестная ошибка")}', 'error')
            return flask_jsonify(result), 400
            
    except Exception as e:
        error_msg = f'Ошибка при восстановлении: {str(e)}'
        app.logger.error(error_msg, exc_info=True)
        return flask_jsonify({'success': False, 'error': error_msg}), 500

@app.route('/api/backup/restore-table', methods=['POST'])
@login_required
def restore_table():
    """Восстановление отдельной таблицы"""
    try:
        data = request.json or {}
        backup_id = data.get('backup_id')
        backup_path = data.get('backup_path')
        table_name = data.get('table_name')
        
        # Если передан ID, получаем путь
        if backup_id and not backup_path:
            backups = backup_manager.list_backups()
            for b in backups:
                if b.get('id') == backup_id:
                    if b.get('exists') and b.get('path'):
                        backup_path = b['path']
                    elif b.get('filename'):
                        backup_path = b['filename']
                    break
        
        if not backup_path or not table_name:
            return flask_jsonify({'success': False, 'error': 'Не указаны backup_path/backup_id или table_name'}), 400
        
        app.logger.info(f"Запрос на восстановление таблицы {table_name} из: {backup_path}")
        
        result = backup_manager.restore_table(backup_path, table_name)
        
        if result.get('success'):
            flash(f'Таблица {table_name} успешно восстановлена', 'success')
            return flask_jsonify(result)
        else:
            flash(f'Ошибка восстановления таблицы: {result.get("error", "Неизвестная ошибка")}', 'error')
            return flask_jsonify(result), 400
            
    except Exception as e:
        error_msg = f'Ошибка при восстановлении таблицы: {str(e)}'
        app.logger.error(error_msg, exc_info=True)
        return flask_jsonify({'success': False, 'error': error_msg}), 500

@app.route('/api/backup/delete', methods=['POST'])
@login_required
def delete_backup():
    """Удаление backup"""
    try:
        data = request.json or {}
        backup_id = data.get('backup_id')
        
        if not backup_id:
            return flask_jsonify({'success': False, 'error': 'Не указан ID backup'}), 400
        
        app.logger.info(f"Запрос на удаление backup: {backup_id}")
        
        result = backup_manager.delete_backup(backup_id)
        
        if result.get('success'):
            flash('Backup успешно удален', 'success')
            return flask_jsonify(result)
        else:
            flash(f'Ошибка удаления: {result.get("error", "Неизвестная ошибка")}', 'error')
            return flask_jsonify(result), 400
            
    except Exception as e:
        error_msg = f'Ошибка при удалении backup: {str(e)}'
        app.logger.error(error_msg, exc_info=True)
        return flask_jsonify({'success': False, 'error': error_msg}), 500

@app.route('/api/backup/list', methods=['GET'])
@login_required
def list_backups():
    """API получения списка backup"""
    try:
        backup_type = request.args.get('type')
        backups = backup_manager.list_backups(backup_type=backup_type)
        return flask_jsonify({'success': True, 'backups': backups})
    except Exception as e:
        return flask_jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/backup/stats', methods=['GET'])
@login_required
def backup_stats():
    """API получения статистики backup"""
    try:
        stats = backup_manager.get_backup_statistics()
        return flask_jsonify({'success': True, 'stats': stats})
    except Exception as e:
        return flask_jsonify({'success': False, 'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5001)


"""
Модуль резервного копирования и восстановления базы данных PostgreSQL
Поддерживает: полный backup, восстановление, WAL архивирование
"""

import os
import subprocess
import shutil
from datetime import datetime
import logging
from pathlib import Path
import json
import re
from prometheus_client import Counter, Histogram, Gauge
import platform

# Логгер для операций backup
backup_logger = logging.getLogger('backup')
backup_logger.setLevel(logging.INFO)

# Prometheus метрики для backup
backup_operations_total = Counter(
    'backup_operations_total',
    'Total backup operations',
    ['operation', 'status', 'type']
)

backup_duration_seconds = Histogram(
    'backup_duration_seconds',
    'Backup operation duration in seconds',
    ['operation', 'type']
)

backup_size_bytes = Gauge(
    'backup_size_bytes',
    'Size of backup files in bytes',
    ['backup_type']
)

backup_last_success_timestamp = Gauge(
    'backup_last_success_timestamp',
    'Timestamp of last successful backup',
    ['backup_type']
)

# Конфигурация путей - папка на рабочем столе OneDrive
# Используем явный путь для пользователя koval
BACKUP_BASE_DIR = Path(r'C:\Users\koval\OneDrive\Desktop\AccessControl_Backups')

# Поддиректории
BACKUP_DIR = BACKUP_BASE_DIR
WAL_ARCHIVE_DIR = BACKUP_BASE_DIR / 'wal_archive'
FULL_BACKUP_DIR = BACKUP_BASE_DIR / 'full'
DIFF_BACKUP_DIR = BACKUP_BASE_DIR / 'differential'
INCR_BACKUP_DIR = BACKUP_BASE_DIR / 'incremental'

# Создание директорий
for dir_path in [BACKUP_DIR, WAL_ARCHIVE_DIR, FULL_BACKUP_DIR, DIFF_BACKUP_DIR, INCR_BACKUP_DIR]:
    try:
        dir_path.mkdir(parents=True, exist_ok=True)
        backup_logger.info(f"Директория backup создана/проверена: {dir_path}")
    except Exception as e:
        backup_logger.error(f"Ошибка создания директории {dir_path}: {e}")


class BackupManager:
    """Менеджер резервного копирования PostgreSQL"""
    
    def __init__(self, db_config):
        """
        Инициализация менеджера backup
        
        Args:
            db_config: словарь с параметрами подключения к БД
                {'host': 'localhost', 'port': 5432, 'database': 'access_control_db',
                 'user': 'postgres', 'password': 'password'}
        """
        self.db_config = db_config
        self.db_name = db_config.get('database', 'access_control_db')
        # Метаданные сохраняем в папке проекта для совместимости
        self.backup_metadata_file = Path('backups') / 'backup_metadata.json'
        # Создаем директорию если нужно
        self.backup_metadata_file.parent.mkdir(parents=True, exist_ok=True)
        self.backup_history = self._load_backup_history()
        
        # Поиск pg_dump и pg_restore
        self.pg_dump_path = self._find_pg_tool('pg_dump')
        self.pg_restore_path = self._find_pg_tool('pg_restore')
        self.psql_path = self._find_pg_tool('psql')
    
    def _find_pg_tool(self, tool_name):
        """
        Поиск утилиты PostgreSQL (pg_dump, pg_restore, psql)
        
        Args:
            tool_name: имя утилиты ('pg_dump', 'pg_restore', 'psql')
            
        Returns:
            str: полный путь к утилите или имя команды если найдена в PATH
        """
        # Сначала проверяем, доступна ли утилита в PATH
        try:
            result = subprocess.run(
                [tool_name, '--version'],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                backup_logger.info(f"Найдена утилита {tool_name} в PATH")
                return tool_name
        except:
            pass
        
        # Если не найдена в PATH, ищем в стандартных местах установки
        if platform.system() == 'Windows':
            # Стандартные пути установки PostgreSQL на Windows
            possible_paths = [
                # Обычные пути установки
                Path('C:/Program Files/PostgreSQL'),
                Path('C:/Program Files (x86)/PostgreSQL'),
                # Пути через переменную окружения
                Path(os.environ.get('ProgramFiles', 'C:/Program Files')) / 'PostgreSQL',
                Path(os.environ.get('ProgramFiles(x86)', 'C:/Program Files (x86)')) / 'PostgreSQL',
            ]
            
            # Проверяем все версии PostgreSQL
            for pg_base in possible_paths:
                if pg_base.exists():
                    # Ищем все поддиректории (версии)
                    for version_dir in pg_base.iterdir():
                        bin_dir = version_dir / 'bin'
                        tool_path = bin_dir / f'{tool_name}.exe'
                        if tool_path.exists():
                            backup_logger.info(f"Найдена утилита {tool_name}: {tool_path}")
                            return str(tool_path)
        else:
            # Для Linux/Mac проверяем стандартные пути
            possible_paths = [
                Path('/usr/bin'),
                Path('/usr/local/bin'),
                Path('/opt/postgresql/bin'),
            ]
            
            for bin_dir in possible_paths:
                tool_path = bin_dir / tool_name
                if tool_path.exists() and tool_path.is_file():
                    backup_logger.info(f"Найдена утилита {tool_name}: {tool_path}")
                    return str(tool_path)
        
        # Если не найдено, возвращаем имя команды (попытка использовать из PATH)
        backup_logger.warning(f"Утилита {tool_name} не найдена в стандартных путях, будет использоваться из PATH")
        return tool_name
    
    def _load_backup_history(self):
        """Загрузка истории backup"""
        if self.backup_metadata_file.exists():
            try:
                with open(self.backup_metadata_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                return {}
        return {}
    
    def _save_backup_history(self):
        """Сохранение истории backup"""
        with open(self.backup_metadata_file, 'w', encoding='utf-8') as f:
            json.dump(self.backup_history, f, indent=2, ensure_ascii=False)
    
    def _get_env_with_password(self):
        """Получить environment variables с паролем для pg_dump"""
        env = os.environ.copy()
        env['PGPASSWORD'] = self.db_config.get('password', '')
        return env
    
    def full_backup(self, format='custom', compress=True):
        """
        Полное резервное копирование базы данных
        
        Args:
            format: формат backup ('custom', 'plain', 'tar')
            compress: использовать ли сжатие
            
        Returns:
            dict: информация о созданном backup
        """
        start_time = datetime.now()
        timestamp = start_time.strftime('%Y%m%d_%H%M%S')
        backup_filename = f"full_backup_{timestamp}"
        
        # Убеждаемся, что директория существует
        FULL_BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        
        if format == 'custom':
            backup_path = FULL_BACKUP_DIR / f"{backup_filename}.dump"
            # Убеждаемся, что путь абсолютный
            backup_path = backup_path.resolve()
            cmd = [
                self.pg_dump_path,
                '-h', self.db_config.get('host', 'localhost'),
                '-p', str(self.db_config.get('port', 5432)),
                '-U', self.db_config.get('user', 'postgres'),
                '-d', self.db_name,
                '-F', 'c',  # custom format
                '-f', str(backup_path)
            ]
            if compress:
                cmd.extend(['-Z', '6'])  # compression level 6 (0-9, 6 = хороший баланс)
        elif format == 'plain':
            backup_path = FULL_BACKUP_DIR / f"{backup_filename}.sql"
            backup_path = backup_path.resolve()
            cmd = [
                self.pg_dump_path,
                '-h', self.db_config.get('host', 'localhost'),
                '-p', str(self.db_config.get('port', 5432)),
                '-U', self.db_config.get('user', 'postgres'),
                '-d', self.db_name,
                '-f', str(backup_path)
            ]
        else:  # tar
            backup_path = FULL_BACKUP_DIR / f"{backup_filename}.tar"
            backup_path = backup_path.resolve()
            cmd = [
                self.pg_dump_path,
                '-h', self.db_config.get('host', 'localhost'),
                '-p', str(self.db_config.get('port', 5432)),
                '-U', self.db_config.get('user', 'postgres'),
                '-d', self.db_name,
                '-F', 't',  # tar format
                '-f', str(backup_path)
            ]
        
        try:
            # Проверка доступности pg_dump
            if not self.pg_dump_path or not Path(self.pg_dump_path).exists() if Path(self.pg_dump_path).is_absolute() else False:
                # Попытка проверить доступность через which/where
                try:
                    check_cmd = 'where' if platform.system() == 'Windows' else 'which'
                    check_result = subprocess.run(
                        [check_cmd, 'pg_dump'] if isinstance(self.pg_dump_path, str) and self.pg_dump_path == 'pg_dump' else [check_cmd, self.pg_dump_path],
                        capture_output=True,
                        text=True,
                        timeout=5
                    )
                    if check_result.returncode != 0:
                        raise FileNotFoundError(f"pg_dump не найден. Установите PostgreSQL или добавьте его в PATH.")
                except:
                    pass
            
            backup_logger.info(f"Начало полного backup: {backup_path}")
            backup_logger.info(f"Используется pg_dump: {self.pg_dump_path}")
            env = self._get_env_with_password()
            
            result = subprocess.run(
                cmd,
                env=env,
                capture_output=True,
                text=True,
                check=True,
                timeout=3600  # Таймаут 1 час
            )
            
            duration = (datetime.now() - start_time).total_seconds()
            file_size = backup_path.stat().st_size if backup_path.exists() else 0
            
            # Сохранение метаданных
            backup_id = f"full_{timestamp}"
            # Используем абсолютный путь для надежности
            absolute_backup_path = backup_path.resolve()
            # Убеждаемся что путь нормализован (Windows стиль)
            backup_path_str = str(absolute_backup_path).replace('/', '\\')
            
            self.backup_history[backup_id] = {
                'type': 'full',
                'format': format,
                'path': backup_path_str,  # Абсолютный путь нормализованный
                'filename': backup_path.name,  # Сохраняем также только имя файла
                'size_bytes': file_size,
                'created_at': start_time.isoformat(),
                'duration_seconds': duration,
                'status': 'success'
            }
            self._save_backup_history()
            backup_logger.info(f"Метаданные сохранены: ID={backup_id}, путь={backup_path_str}")
            
            # Обновление метрик
            backup_operations_total.labels(operation='backup', status='success', type='full').inc()
            backup_duration_seconds.labels(operation='backup', type='full').observe(duration)
            backup_size_bytes.labels(backup_type='full').set(file_size)
            backup_last_success_timestamp.labels(backup_type='full').set(start_time.timestamp())
            
            backup_logger.info(f"Полный backup успешно создан: {backup_path} ({file_size} bytes, {duration:.2f}s)")
            
            return {
                'success': True,
                'backup_id': backup_id,
                'path': str(backup_path),
                'size_bytes': file_size,
                'duration_seconds': duration,
                'created_at': start_time.isoformat()
            }
            
        except FileNotFoundError as e:
            duration = (datetime.now() - start_time).total_seconds()
            error_msg = f"pg_dump не найден. Установите PostgreSQL или добавьте его в PATH. Путь: {self.pg_dump_path}"
            backup_logger.error(error_msg)
            
            backup_operations_total.labels(operation='backup', status='error', type='full').inc()
            
            return {
                'success': False,
                'error': f"Утилита pg_dump не найдена. Убедитесь, что PostgreSQL установлен и добавлен в PATH, или укажите полный путь к pg_dump.exe"
            }
        except subprocess.TimeoutExpired:
            duration = (datetime.now() - start_time).total_seconds()
            error_msg = "Таймаут при создании backup (превышен лимит 1 час)"
            backup_logger.error(error_msg)
            
            backup_operations_total.labels(operation='backup', status='error', type='full').inc()
            
            return {
                'success': False,
                'error': error_msg
            }
        except subprocess.CalledProcessError as e:
            duration = (datetime.now() - start_time).total_seconds()
            error_details = e.stderr if e.stderr else e.stdout if e.stdout else str(e)
            error_msg = f"Ошибка при создании полного backup: {error_details}"
            backup_logger.error(error_msg)
            backup_logger.error(f"Команда: {' '.join(cmd)}")
            
            backup_operations_total.labels(operation='backup', status='error', type='full').inc()
            
            return {
                'success': False,
                'error': error_msg
            }
        except Exception as e:
            duration = (datetime.now() - start_time).total_seconds()
            error_msg = f"Неожиданная ошибка при создании backup: {str(e)}"
            backup_logger.error(error_msg, exc_info=True)
            
            backup_operations_total.labels(operation='backup', status='error', type='full').inc()
            
            return {
                'success': False,
                'error': error_msg
            }
    
    def restore(self, backup_path, drop_existing=False):
        """
        Восстановление базы данных из backup
        
        Args:
            backup_path: путь к файлу backup (может быть абсолютным, относительным или только имя файла)
            drop_existing: удалить существующую БД перед восстановлением
            
        Returns:
            dict: результат операции восстановления
        """
        start_time = datetime.now()
        
        backup_path_str = str(backup_path)
        backup_logger.info(f"Начало восстановления, исходный путь: {backup_path_str}")
        
        # Извлекаем имя файла любым способом
        backup_filename = None
        
        # Метод 1: Регулярное выражение для поиска имени файла
        filename_match = re.search(r'(full_backup_\d{8}_\d{6}\.[a-z]+)', backup_path_str)
        if filename_match:
            backup_filename = filename_match.group(1)
            backup_logger.info(f"Имя файла найдено через regex: {backup_filename}")
        
        # Метод 2: Если не найдено, ищем в метаданных по ID из пути
        if not backup_filename:
            # Пытаемся извлечь ID backup из пути (например full_20251103_092621)
            backup_id_match = re.search(r'(full_\d{8}_\d{6})', backup_path_str)
            if backup_id_match:
                backup_id = backup_id_match.group(1)
                # Ищем в истории backup
                if backup_id in self.backup_history:
                    metadata = self.backup_history[backup_id]
                    backup_filename = metadata.get('filename')
                    if not backup_filename:
                        # Пытаемся извлечь из path в метаданных
                        path_in_meta = metadata.get('path', '')
                        filename_match = re.search(r'(full_backup_\d{8}_\d{6}\.[a-z]+)', path_in_meta)
                        if filename_match:
                            backup_filename = filename_match.group(1)
                    backup_logger.info(f"Имя файла найдено в метаданных: {backup_filename}")
        
        # Метод 3: Парсинг пути
        if not backup_filename:
            # Заменяем все разделители на / и разбиваем
            normalized = backup_path_str.replace('\\', '/').replace('-', '/')
            parts = normalized.split('/')
            for part in reversed(parts):
                if part and (part.endswith('.dump') or part.endswith('.sql') or part.endswith('.tar')):
                    # Убираем лишние символы
                    backup_filename = re.sub(r'[^a-zA-Z0-9._-]', '', part)
                    if backup_filename.endswith(('.dump', '.sql', '.tar')):
                        backup_logger.info(f"Имя файла извлечено из пути: {backup_filename}")
                        break
        
        # Метод 4: Последняя попытка - поиск по всем файлам .dump
        if not backup_filename:
            backup_logger.warning(f"Не удалось извлечь имя файла из: {backup_path_str}")
            # Ищем все .dump файлы и предлагаем первый найденный
            if FULL_BACKUP_DIR.exists():
                dump_files = list(FULL_BACKUP_DIR.glob('*.dump'))
                if dump_files:
                    backup_filename = dump_files[-1].name  # Последний файл
                    backup_logger.info(f"Использован последний найденный файл: {backup_filename}")
        
        if not backup_filename:
            return {
                'success': False,
                'error': f'Не удалось определить имя файла backup из пути: {backup_path_str}\n\nУбедитесь, что файл существует в: {FULL_BACKUP_DIR}'
            }
        
        # Ищем файл в стандартных местах (по приоритету)
        possible_paths = [
            FULL_BACKUP_DIR / backup_filename,  # Приоритет 1
            BACKUP_BASE_DIR / backup_filename,   # Приоритет 2
        ]
        
        # Если исходный путь выглядит валидным
        try:
            test_path = Path(backup_path_str)
            if test_path.exists() and test_path.is_file():
                possible_paths.insert(0, test_path)
        except:
            pass
        
        # Старая директория
        old_backup_dir = Path('backups') / 'full'
        if old_backup_dir.exists():
            possible_paths.append(old_backup_dir / backup_filename)
        
        # Ищем файл
        found_path = None
        for path in possible_paths:
            try:
                if path.exists() and path.is_file():
                    found_path = path.resolve()
                    backup_logger.info(f"Файл найден: {found_path}")
                    break
            except:
                continue
        
        # Последняя попытка - рекурсивный поиск
        if not found_path:
            for search_dir in [FULL_BACKUP_DIR, BACKUP_BASE_DIR, old_backup_dir]:
                if search_dir.exists():
                    try:
                        for file in search_dir.rglob(backup_filename):
                            if file.is_file():
                                found_path = file.resolve()
                                backup_logger.info(f"Файл найден рекурсивно: {found_path}")
                                break
                        if found_path:
                            break
                    except:
                        continue
        
        if not found_path:
            # Формируем список всех .dump файлов для справки
            existing_files = []
            if FULL_BACKUP_DIR.exists():
                existing_files = [f.name for f in FULL_BACKUP_DIR.glob('*.dump')]
            
            error_msg = f'Файл "{backup_filename}" не найден.\n\n'
            error_msg += f'Ожидаемый путь: {FULL_BACKUP_DIR / backup_filename}\n\n'
            if existing_files:
                error_msg += f'Найдены следующие backup файлы:\n'
                for f in existing_files[:5]:
                    error_msg += f'  - {f}\n'
            else:
                error_msg += 'В директории backup файлы не найдены.\n'
            
            return {
                'success': False,
                'error': error_msg
            }
        
        backup_path = found_path
        
        try:
            backup_logger.info(f"Начало восстановления из: {backup_path}")
            
            # Определение формата по расширению
            if backup_path.suffix == '.dump' or backup_path.suffix == '.custom':
                # Custom format - используем pg_restore
                cmd = [
                    self.pg_restore_path,
                    '-h', self.db_config.get('host', 'localhost'),
                    '-p', str(self.db_config.get('port', 5432)),
                    '-U', self.db_config.get('user', 'postgres'),
                    '-d', self.db_name,
                    '--verbose',  # verbose
                ]
                
                # Опции очистки (должны быть перед путем к файлу)
                if drop_existing:
                    cmd.append('--clean')
                    cmd.append('--if-exists')
                
                # Путь к файлу backup (в конце команды)
                cmd.append(str(backup_path))
                    
            elif backup_path.suffix == '.sql':
                # Plain SQL format - используем psql
                cmd = [
                    self.psql_path,
                    '-h', self.db_config.get('host', 'localhost'),
                    '-p', str(self.db_config.get('port', 5432)),
                    '-U', self.db_config.get('user', 'postgres'),
                    '-d', self.db_name,
                    '-f', str(backup_path)
                ]
            else:
                return {
                    'success': False,
                    'error': f'Неподдерживаемый формат backup: {backup_path.suffix}'
                }
            
            env = self._get_env_with_password()
            
            result = subprocess.run(
                cmd,
                env=env,
                capture_output=True,
                text=True,
                check=True
            )
            
            duration = (datetime.now() - start_time).total_seconds()
            
            backup_operations_total.labels(operation='restore', status='success', type='full').inc()
            backup_duration_seconds.labels(operation='restore', type='full').observe(duration)
            
            backup_logger.info(f"Восстановление успешно завершено за {duration:.2f}s")
            
            return {
                'success': True,
                'duration_seconds': duration,
                'restored_at': datetime.now().isoformat()
            }
            
        except subprocess.CalledProcessError as e:
            duration = (datetime.now() - start_time).total_seconds()
            error_msg = f"Ошибка при восстановлении: {e.stderr}"
            backup_logger.error(error_msg)
            
            backup_operations_total.labels(operation='restore', status='error', type='full').inc()
            
            return {
                'success': False,
                'error': error_msg
            }
        except Exception as e:
            duration = (datetime.now() - start_time).total_seconds()
            error_msg = f"Неожиданная ошибка при восстановлении: {str(e)}"
            backup_logger.error(error_msg, exc_info=True)
            
            backup_operations_total.labels(operation='restore', status='error', type='full').inc()
            
            return {
                'success': False,
                'error': error_msg
            }
    
    def restore_table(self, backup_path, table_name):
        """
        Восстановление отдельной таблицы из backup
        
        Args:
            backup_path: путь к файлу backup
            table_name: имя таблицы для восстановления
            
        Returns:
            dict: результат операции
        """
        start_time = datetime.now()
        backup_path = Path(backup_path)
        
        if not backup_path.exists():
            return {
                'success': False,
                'error': f'Файл backup не найден: {backup_path}'
            }
        
        if backup_path.suffix != '.dump' and backup_path.suffix != '.custom':
            return {
                'success': False,
                'error': 'Восстановление отдельных таблиц поддерживается только для custom format'
            }
        
        try:
            backup_logger.info(f"Восстановление таблицы {table_name} из: {backup_path}")
            
            cmd = [
                self.pg_restore_path,
                '-h', self.db_config.get('host', 'localhost'),
                '-p', str(self.db_config.get('port', 5432)),
                '-U', self.db_config.get('user', 'postgres'),
                '-d', self.db_name,
                '-t', table_name,  # только эта таблица
                '-v',
                str(backup_path)
            ]
            
            env = self._get_env_with_password()
            
            result = subprocess.run(
                cmd,
                env=env,
                capture_output=True,
                text=True,
                check=True
            )
            
            duration = (datetime.now() - start_time).total_seconds()
            
            backup_logger.info(f"Таблица {table_name} успешно восстановлена за {duration:.2f}s")
            
            return {
                'success': True,
                'table_name': table_name,
                'duration_seconds': duration
            }
            
        except subprocess.CalledProcessError as e:
            error_msg = f"Ошибка при восстановлении таблицы {table_name}: {e.stderr}"
            backup_logger.error(error_msg)
            return {
                'success': False,
                'error': error_msg
            }
    
    def list_backups(self, backup_type=None):
        """
        Список всех доступных backup
        
        Args:
            backup_type: тип backup ('full', 'differential', 'incremental') или None для всех
            
        Returns:
            list: список backup с метаданными
        """
        backups = []
        
        for backup_id, metadata in self.backup_history.items():
            if backup_type is None or metadata.get('type') == backup_type:
                # Сначала пробуем использовать сохраненное имя файла
                backup_filename = metadata.get('filename')
                backup_path_str = metadata.get('path', '')
                
                # Если нет имени файла, извлекаем из пути
                if not backup_filename and backup_path_str:
                    # Извлекаем имя файла из любого пути
                    filename_match = re.search(r'(full_backup_\d{8}_\d{6}\.[a-z]+)', backup_path_str)
                    if filename_match:
                        backup_filename = filename_match.group(1)
                    else:
                        # Пробуем последнюю часть пути
                        parts = backup_path_str.replace('\\', '/').replace('-', '/').split('/')
                        for part in reversed(parts):
                            if part and (part.endswith('.dump') or part.endswith('.sql') or part.endswith('.tar')):
                                backup_filename = part
                                break
                
                # Если имя файла не найдено, пропускаем этот backup
                if not backup_filename:
                    backup_logger.warning(f"Не удалось извлечь имя файла для backup {backup_id}, путь: {backup_path_str}")
                    continue
                
                # Ищем файл по имени в стандартных местах (по приоритету)
                backup_path = None
                possible_paths = [
                    FULL_BACKUP_DIR / backup_filename,  # Приоритет 1: правильная директория
                    BACKUP_BASE_DIR / backup_filename,   # Приоритет 2: корень backup
                ]
                
                # Если исходный путь выглядит валидным и существует - пробуем его
                if backup_path_str and len(backup_path_str) > 10:
                    try:
                        test_path = Path(backup_path_str)
                        if test_path.exists() and test_path.is_file():
                            possible_paths.insert(0, test_path)  # Высокий приоритет
                    except:
                        pass
                
                # Старая директория для миграции
                old_backup_dir = Path('backups') / 'full'
                if old_backup_dir.exists():
                    possible_paths.append(old_backup_dir / backup_filename)
                
                # Ищем существующий файл
                for path in possible_paths:
                    try:
                        resolved_path = path.resolve()
                        if resolved_path.exists() and resolved_path.is_file():
                            backup_path = resolved_path
                            break
                    except Exception as e:
                        backup_logger.debug(f"Путь не найден: {path}, ошибка: {e}")
                        continue
                
                if backup_path and backup_path.exists():
                    metadata['exists'] = True
                    metadata['size_mb'] = round(backup_path.stat().st_size / (1024 * 1024), 2)
                    # Обновляем путь и имя файла в метаданных на правильные
                    metadata['path'] = str(backup_path.resolve()).replace('/', '\\')
                    metadata['filename'] = backup_path.name
                else:
                    metadata['exists'] = False
                    metadata['size_mb'] = 0
                    
                backups.append({
                    'id': backup_id,
                    **metadata
                })
        
        # Сортировка по дате создания (новые первыми)
        backups.sort(key=lambda x: x.get('created_at', ''), reverse=True)
        
        return backups
    
    def delete_backup(self, backup_id):
        """
        Удаление backup
        
        Args:
            backup_id: идентификатор backup
            
        Returns:
            dict: результат операции
        """
        if backup_id not in self.backup_history:
            return {
                'success': False,
                'error': f'Backup с ID {backup_id} не найден'
            }
        
        metadata = self.backup_history[backup_id]
        backup_path = Path(metadata['path'])
        
        try:
            if backup_path.exists():
                backup_path.unlink()
                backup_logger.info(f"Backup файл удален: {backup_path}")
            
            del self.backup_history[backup_id]
            self._save_backup_history()
            
            return {
                'success': True,
                'message': f'Backup {backup_id} успешно удален'
            }
            
        except Exception as e:
            error_msg = f"Ошибка при удалении backup: {str(e)}"
            backup_logger.error(error_msg)
            return {
                'success': False,
                'error': error_msg
            }
    
    def get_backup_statistics(self):
        """Получить статистику по backup"""
        backups = self.list_backups()
        
        stats = {
            'total_backups': len(backups),
            'total_size_bytes': 0,
            'full_backups': 0,
            'differential_backups': 0,
            'incremental_backups': 0,
            'last_backup': None
        }
        
        for backup in backups:
            stats['total_size_bytes'] += backup.get('size_bytes', 0)
            
            backup_type = backup.get('type', 'unknown')
            if backup_type == 'full':
                stats['full_backups'] += 1
            elif backup_type == 'differential':
                stats['differential_backups'] += 1
            elif backup_type == 'incremental':
                stats['incremental_backups'] += 1
            
            if stats['last_backup'] is None or backup.get('created_at', '') > stats['last_backup']:
                stats['last_backup'] = backup.get('created_at')
        
        stats['total_size_mb'] = round(stats['total_size_bytes'] / (1024 * 1024), 2)
        
        return stats


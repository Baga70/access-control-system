"""
Скрипт автоматического резервного копирования
Можно запускать через cron (Linux) или Task Scheduler (Windows)
"""

import sys
import os
from datetime import datetime
from pathlib import Path

# Добавляем путь к модулю backup_manager
sys.path.insert(0, str(Path(__file__).parent))

from backup_manager import BackupManager

# Конфигурация базы данных
DATABASE_CONFIG = {
    'host': 'localhost',
    'port': 5432,
    'database': 'access_control_db',
    'user': 'postgres',
    'password': '300307',  # ИЗМЕНИТЕ НА ВАШ ПАРОЛЬ
    'client_encoding': 'utf8'
}

# Конфигурация backup
BACKUP_CONFIG = {
    'format': 'custom',  # 'custom', 'plain', 'tar'
    'compress': True,
    'keep_days': 7,  # Сколько дней хранить backup
}

def main():
    """Основная функция автоматического backup"""
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Начало автоматического backup")
    
    try:
        # Инициализация менеджера backup
        backup_manager = BackupManager(DATABASE_CONFIG)
        
        # Создание полного backup
        print("Создание полного backup...")
        result = backup_manager.full_backup(
            format=BACKUP_CONFIG['format'],
            compress=BACKUP_CONFIG['compress']
        )
        
        if result.get('success'):
            print(f"✅ Backup успешно создан: {result['backup_id']}")
            print(f"   Путь: {result['path']}")
            print(f"   Размер: {result['size_bytes'] / (1024*1024):.2f} MB")
            print(f"   Длительность: {result['duration_seconds']:.2f} секунд")
            
            # Очистка старых backup (опционально)
            cleanup_old_backups(backup_manager, BACKUP_CONFIG['keep_days'])
            
            return 0
        else:
            print(f"❌ Ошибка создания backup: {result.get('error', 'Неизвестная ошибка')}")
            return 1
            
    except Exception as e:
        print(f"❌ Критическая ошибка: {str(e)}")
        import traceback
        traceback.print_exc()
        return 1

def cleanup_old_backups(backup_manager, keep_days):
    """Удаление старых backup старше keep_days дней"""
    try:
        from datetime import timedelta
        cutoff_date = datetime.now() - timedelta(days=keep_days)
        
        backups = backup_manager.list_backups()
        deleted_count = 0
        
        for backup in backups:
            created_str = backup.get('created_at', '')
            if created_str:
                try:
                    created_date = datetime.fromisoformat(created_str.replace('Z', '+00:00'))
                    if created_date.replace(tzinfo=None) < cutoff_date:
                        result = backup_manager.delete_backup(backup['id'])
                        if result.get('success'):
                            deleted_count += 1
                            print(f"   Удален старый backup: {backup['id']}")
                except:
                    pass
        
        if deleted_count > 0:
            print(f"   Удалено старых backup: {deleted_count}")
            
    except Exception as e:
        print(f"   Предупреждение: ошибка при очистке старых backup: {str(e)}")

if __name__ == '__main__':
    exit_code = main()
    sys.exit(exit_code)


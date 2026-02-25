"""
Скрипт для исправления метаданных backup
Исправляет некорректные пути и добавляет имена файлов
"""

import json
import re
from pathlib import Path

BACKUP_BASE_DIR = Path(r'C:\Users\koval\OneDrive\Desktop\AccessControl_Backups')
FULL_BACKUP_DIR = BACKUP_BASE_DIR / 'full'
METADATA_FILE = Path('backups') / 'backup_metadata.json'

def extract_filename(path_str):
    """Извлечение имени файла из любого пути"""
    if not path_str:
        return None
    
    # Поиск по паттерну full_backup_YYYYMMDD_HHMMSS.ext
    filename_match = re.search(r'(full_backup_\d{8}_\d{6}\.[a-z]+)', path_str)
    if filename_match:
        return filename_match.group(1)
    
    # Поиск последней части с расширением
    parts = path_str.replace('\\', '/').replace('-', '/').split('/')
    for part in reversed(parts):
        if part and (part.endswith('.dump') or part.endswith('.sql') or part.endswith('.tar')):
            return part
    
    return None

def fix_metadata():
    """Исправление метаданных backup"""
    if not METADATA_FILE.exists():
        print(f"Файл метаданных не найден: {METADATA_FILE}")
        return
    
    print(f"Чтение метаданных из: {METADATA_FILE}")
    with open(METADATA_FILE, 'r', encoding='utf-8') as f:
        metadata = json.load(f)
    
    fixed_count = 0
    
    for backup_id, backup_info in metadata.items():
        path_str = backup_info.get('path', '')
        filename = backup_info.get('filename')
        
        # Извлекаем имя файла если его нет
        if not filename:
            filename = extract_filename(path_str)
            if filename:
                backup_info['filename'] = filename
                fixed_count += 1
                print(f"  Добавлено имя файла для {backup_id}: {filename}")
        
        # Ищем файл по имени
        if filename:
            # Пробуем найти файл
            possible_paths = [
                FULL_BACKUP_DIR / filename,
                BACKUP_BASE_DIR / filename,
            ]
            
            for path in possible_paths:
                if path.exists() and path.is_file():
                    # Обновляем путь на правильный
                    correct_path = str(path.resolve()).replace('/', '\\')
                    if backup_info.get('path') != correct_path:
                        backup_info['path'] = correct_path
                        backup_info['filename'] = filename
                        fixed_count += 1
                        print(f"  Исправлен путь для {backup_id}: {correct_path}")
                    break
    
    # Сохраняем исправленные метаданные
    if fixed_count > 0:
        backup_file = METADATA_FILE.parent / 'backup_metadata.json.backup'
        if backup_file.exists():
            print(f"  Backup файла уже существует: {backup_file}")
        else:
            # Сохраняем backup
            with open(backup_file, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, indent=2, ensure_ascii=False)
            print(f"  Создан backup метаданных: {backup_file}")
        
        # Сохраняем исправленные метаданные
        with open(METADATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)
        
        print(f"\nИсправлено {fixed_count} записей в метаданных")
    else:
        print("  Изменений не требуется")
    
    print(f"\nМетаданные сохранены в: {METADATA_FILE}")

if __name__ == '__main__':
    print("Исправление метаданных backup...")
    fix_metadata()
    print("\nГотово! Перезапустите приложение.")


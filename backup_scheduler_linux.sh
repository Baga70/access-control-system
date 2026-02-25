#!/bin/bash
# Скрипт для автоматического запуска backup через cron (Linux)
# 
# Инструкция по настройке:
# 1. Сделайте скрипт исполняемым: chmod +x backup_scheduler_linux.sh
# 2. Откройте crontab: crontab -e
# 3. Добавьте строку (например, запуск каждый день в 2:00):
#    0 2 * * * /path/to/project/backup_scheduler_linux.sh >> /path/to/project/backups/backup.log 2>&1
#
# Примеры расписания:
#   0 2 * * *     - каждый день в 2:00
#   0 */6 * * *   - каждые 6 часов
#   0 2 * * 0     - каждое воскресенье в 2:00

# Получаем директорию скрипта
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# Запуск скрипта backup
python3 auto_backup.py

# Проверка результата
if [ $? -eq 0 ]; then
    echo "Backup успешно выполнен!"
    exit 0
else
    echo "Ошибка выполнения backup!"
    exit 1
fi


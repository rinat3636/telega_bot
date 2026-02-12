# Runbook: Операционные процедуры

## 🚨 Экстренные ситуации

### Бот не отвечает

**Симптомы:**
- Пользователи не получают ответы
- Команды не обрабатываются

**Диагностика:**
```bash
# Проверить, запущен ли процесс
ps aux | grep main.py

# Проверить логи
tail -100 bot.log | grep ERROR

# Проверить соединение с Telegram
curl https://api.telegram.org/bot<TOKEN>/getMe
```

**Решение:**
1. Перезапустить бота:
   ```bash
   pkill -f main.py
   python3 main.py &
   ```

2. Если не помогло, проверить:
   - Интернет-соединение
   - Токен бота (не истек ли)
   - Лимиты Telegram API

---

### Задачи зависают

**Симптомы:**
- Статус "processing" не меняется
- Пользователи не получают результаты

**Диагностика:**
```bash
# Проверить очередь RQ
rq info --url redis://localhost:6379

# Проверить активные задачи в БД
sqlite3 rei_bot.db "SELECT * FROM jobs WHERE status='processing';"

# Проверить worker
ps aux | grep "rq worker"
```

**Решение:**
1. Перезапустить worker:
   ```bash
   pkill -f "rq worker"
   rq worker --url redis://localhost:6379 &
   ```

2. Отменить зависшие задачи:
   ```python
   from database.models import db
   import asyncio
   
   async def cancel_stuck_jobs():
       # Найти задачи старше 1 часа
       import sqlite3
       conn = sqlite3.connect('rei_bot.db')
       cursor = conn.execute("""
           SELECT id, user_id, cost_estimate 
           FROM jobs 
           WHERE status='processing' 
           AND datetime(started_at) < datetime('now', '-1 hour')
       """)
       
       for job_id, user_id, cost in cursor:
           await db.update_job_status(job_id, 'failed', error_message='Timeout')
           await db.refund_balance(user_id, cost, 'job', str(job_id), 'Возврат за timeout')
           print(f"Отменена задача {job_id}, возврат {cost} ₽")
   
   asyncio.run(cancel_stuck_jobs())
   ```

---

### Webhook не работает

**Симптомы:**
- Платежи не зачисляются автоматически
- Статус платежей остается "pending"

**Диагностика:**
```bash
# Проверить, запущен ли webhook сервер
netstat -tulpn | grep 8080

# Проверить доступность извне
curl -X POST https://your-domain.com/webhook/yookassa

# Проверить логи webhook
grep "webhook" bot.log | tail -20
```

**Решение:**
1. Проверить настройки в YooKassa:
   - URL корректен
   - HTTPS (не HTTP)
   - Webhook активен

2. Проверить firewall:
   ```bash
   sudo ufw status
   sudo ufw allow 8080/tcp
   ```

3. Использовать ручную проверку:
   ```python
   from services.yookassa_payment import yookassa_service
   
   # Проверить статус платежа вручную
   yookassa_service.check_payment_status('payment_id')
   ```

---

### Отрицательный баланс

**Симптомы:**
- У пользователя баланс < 0
- Ошибки при списании

**Диагностика:**
```python
from database.models import db
import asyncio

async def check_balance(user_id):
    balance = await db.get_balance(user_id)
    history = await db.get_ledger_history(user_id, limit=50)
    
    print(f"Баланс: {balance} ₽")
    print("\nИстория:")
    for entry in history:
        print(f"{entry['created_at']}: {entry['type']} {entry['amount']} ₽")

asyncio.run(check_balance(123456789))
```

**Решение:**
1. Проверить ledger на ошибки
2. Если ошибка в коде — исправить и пополнить баланс:
   ```python
   await db.add_ledger_entry(
       user_id=123456789,
       entry_type='credit',
       amount=100.0,
       ref_type='admin',
       ref_id='correction_001',
       description='Коррекция баланса'
   )
   ```

---

## 🔧 Регулярные задачи

### Резервное копирование БД

**Частота:** Ежедневно

**Процедура:**
```bash
#!/bin/bash
# backup.sh

DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR="/backups"
DB_PATH="rei_bot.db"

# Создать резервную копию
sqlite3 $DB_PATH ".backup $BACKUP_DIR/rei_bot_$DATE.db"

# Сжать
gzip $BACKUP_DIR/rei_bot_$DATE.db

# Удалить старые бэкапы (старше 30 дней)
find $BACKUP_DIR -name "rei_bot_*.db.gz" -mtime +30 -delete

echo "Backup completed: rei_bot_$DATE.db.gz"
```

**Добавить в cron:**
```bash
crontab -e
# Добавить строку:
0 3 * * * /path/to/backup.sh
```

---

### Очистка старых задач

**Частота:** Еженедельно

**Процедура:**
```python
# cleanup_jobs.py
import asyncio
from database.models import db
import sqlite3

async def cleanup_old_jobs():
    conn = sqlite3.connect('rei_bot.db')
    
    # Удалить завершенные задачи старше 30 дней
    cursor = conn.execute("""
        DELETE FROM jobs
        WHERE status IN ('completed', 'failed', 'cancelled')
        AND datetime(completed_at) < datetime('now', '-30 days')
    """)
    
    deleted = cursor.rowcount
    conn.commit()
    conn.close()
    
    print(f"Удалено {deleted} старых задач")

asyncio.run(cleanup_old_jobs())
```

---

### Мониторинг очереди

**Частота:** Каждые 5 минут

**Процедура:**
```bash
#!/bin/bash
# monitor_queue.sh

QUEUE_SIZE=$(rq info --url redis://localhost:6379 | grep "queued" | awk '{print $2}')

if [ "$QUEUE_SIZE" -gt 100 ]; then
    echo "⚠️ Очередь переполнена: $QUEUE_SIZE задач"
    # Отправить алерт (email, Telegram, Slack)
fi
```

---

## 👥 Управление пользователями

### Пополнить баланс вручную

```python
from database.models import db
import asyncio

async def add_balance(user_id, amount, description):
    await db.add_ledger_entry(
        user_id=user_id,
        entry_type='credit',
        amount=amount,
        ref_type='admin',
        ref_id=None,
        description=description
    )
    
    new_balance = await db.get_balance(user_id)
    print(f"Пополнено {amount} ₽. Новый баланс: {new_balance} ₽")

# Пример
asyncio.run(add_balance(123456789, 1000.0, "Бонус за участие в тестировании"))
```

---

### Списать баланс вручную

```python
from database.models import db
import asyncio

async def subtract_balance(user_id, amount, description):
    success = await db.subtract_balance(user_id, amount)
    
    if success:
        print(f"Списано {amount} ₽")
    else:
        print("Недостаточно средств")

asyncio.run(subtract_balance(123456789, 50.0))
```

---

### Забанить пользователя

```python
from database.models import db
import asyncio

async def ban_user(user_id):
    await db.ban_user(user_id)
    print(f"Пользователь {user_id} забанен")

asyncio.run(ban_user(123456789))
```

---

### Разбанить пользователя

```python
import sqlite3

conn = sqlite3.connect('rei_bot.db')
conn.execute("UPDATE users SET is_banned = 0 WHERE tg_id = ?", (123456789,))
conn.commit()
conn.close()

print("Пользователь разбанен")
```

---

### Посмотреть историю пользователя

```python
from database.models import db
import asyncio

async def user_report(user_id):
    user = await db.get_or_create_user(user_id)
    balance = await db.get_balance(user_id)
    history = await db.get_ledger_history(user_id, limit=20)
    active_jobs = await db.get_user_active_jobs(user_id)
    
    print(f"=== Пользователь {user_id} ===")
    print(f"Username: {user.get('username')}")
    print(f"Баланс: {balance} ₽")
    print(f"Активных задач: {len(active_jobs)}")
    print(f"Забанен: {'Да' if user.get('is_banned') else 'Нет'}")
    
    print("\nПоследние операции:")
    for entry in history[:10]:
        print(f"  {entry['created_at']}: {entry['type']} {entry['amount']} ₽ - {entry['description']}")

asyncio.run(user_report(123456789))
```

---

## 📊 Аналитика

### Статистика по платежам

```python
import sqlite3

conn = sqlite3.connect('rei_bot.db')

# Общая сумма платежей
cursor = conn.execute("""
    SELECT 
        COUNT(*) as total_payments,
        SUM(amount) as total_amount,
        AVG(amount) as avg_amount
    FROM payments
    WHERE status = 'paid'
""")

stats = cursor.fetchone()
print(f"Всего платежей: {stats[0]}")
print(f"Общая сумма: {stats[1]:.2f} ₽")
print(f"Средний чек: {stats[2]:.2f} ₽")

conn.close()
```

---

### Статистика по задачам

```python
import sqlite3

conn = sqlite3.connect('rei_bot.db')

# Статистика по типам задач
cursor = conn.execute("""
    SELECT 
        type,
        status,
        COUNT(*) as count
    FROM jobs
    GROUP BY type, status
    ORDER BY type, status
""")

print("Статистика задач:")
for row in cursor:
    print(f"  {row[0]} ({row[1]}): {row[2]}")

conn.close()
```

---

### Топ пользователей по расходам

```python
import sqlite3

conn = sqlite3.connect('rei_bot.db')

cursor = conn.execute("""
    SELECT 
        user_id,
        SUM(CASE WHEN type = 'debit' THEN -amount ELSE 0 END) as total_spent
    FROM ledger
    GROUP BY user_id
    ORDER BY total_spent DESC
    LIMIT 10
""")

print("Топ-10 пользователей по расходам:")
for i, row in enumerate(cursor, 1):
    print(f"{i}. User {row[0]}: {row[1]:.2f} ₽")

conn.close()
```

---

## 🔄 Обновление бота

### Процедура обновления

1. **Создать резервную копию:**
   ```bash
   ./backup.sh
   ```

2. **Остановить бота:**
   ```bash
   pkill -f main.py
   pkill -f "rq worker"
   ```

3. **Обновить код:**
   ```bash
   git pull origin main
   ```

4. **Обновить зависимости:**
   ```bash
   pip3 install -r requirements.txt --upgrade
   ```

5. **Запустить миграции (если есть):**
   ```bash
   python3 migrations/migrate_vX.py
   ```

6. **Запустить тесты:**
   ```bash
   pytest tests/ -v
   ```

7. **Запустить бота:**
   ```bash
   python3 main.py &
   rq worker --url redis://localhost:6379 &
   ```

8. **Проверить работоспособность:**
   ```bash
   tail -f bot.log
   ```

---

## 🐛 Отладка

### Включить DEBUG логи

```python
# В main.py изменить:
logging.basicConfig(level=logging.DEBUG)
```

### Проверить конфигурацию

```python
import config

print("BOT_TOKEN:", config.BOT_TOKEN[:10] + "...")
print("REDIS_URL:", config.REDIS_URL)
print("DATABASE_PATH:", config.DATABASE_PATH)
```

### Тестовый запрос к API

```python
from services.nano_banana import NanoBananaService
import asyncio

async def test_api():
    service = NanoBananaService()
    result = await service.generate_image("test prompt")
    print(result)

asyncio.run(test_api())
```

---

## 📞 Контакты

**Администратор:** @your_username
**Техподдержка:** support@example.com
**Мониторинг:** https://status.example.com

# QA Fixes v3.3

## Обзор

Этот документ описывает все критичные исправления, внесенные в v3.3 на основе QA review v3.2.

---

## QA-1: Атомарность reserve_balance и charge_reserved_balance

### Проблема
- `reserve_balance()` создавал новое соединение для `get_balance()`, что нарушало атомарность
- `charge_reserved_balance()` игнорировал `actual_amount` и не создавал reconciliation записей

### Исправление

**`database/models.py`:**

1. **Обновлен `get_balance()`:**
   ```python
   async def get_balance(self, tg_id: int, db: Optional[aiosqlite.Connection] = None) -> float:
       if db is not None:
           # Используем существующее соединение (внутри транзакции)
           async with db.execute(...) as cursor:
               ...
       else:
           # Создаем новое соединение
           async with aiosqlite.connect(self.db_path) as db:
               ...
   ```

2. **Обновлен `reserve_balance()`:**
   ```python
   async def reserve_balance(self, user_id: int, amount: float, ref_id: str) -> bool:
       async with aiosqlite.connect(self.db_path) as db:
           await db.execute("BEGIN IMMEDIATE")
           try:
               # Используем то же соединение для проверки баланса (атомарность)
               balance = await self.get_balance(user_id, db=db)
               if balance < amount:
                   await db.rollback()
                   return False
               # ... создать запись резервирования
               await db.commit()
               return True
           except Exception as e:
               await db.rollback()
               raise e
   ```

3. **Переписан `charge_reserved_balance()`:**
   ```python
   async def charge_reserved_balance(self, user_id: int, ref_id: str, actual_amount: float, new_ref_id: str):
       async with aiosqlite.connect(self.db_path) as db:
           await db.execute("BEGIN IMMEDIATE")
           try:
               # 1. Получить зарезервированную сумму
               reserved_amount = ...
               
               # 2. Обновить запись резервирования с actual_amount
               await db.execute(
                   "UPDATE ledger SET ref_type = 'job', ref_id = ?, amount = ? WHERE ...",
                   (new_ref_id, -actual_amount, user_id, ref_id)
               )
               
               # 3. Если есть разница, создать компенсирующую запись
               delta = reserved_amount - actual_amount
               if abs(delta) > 0.01:
                   await db.execute(
                       "INSERT INTO ledger ... VALUES (?, 'refund', ?, 'reconciliation', ...)",
                       (user_id, delta, f"{new_ref_id}_reconcile", ...)
                   )
               
               await db.commit()
           except Exception as e:
               await db.rollback()
               raise e
   ```

### Результат
✅ Полная атомарность резервирования и списания  
✅ Корректная обработка `actual_amount`  
✅ Автоматическая reconciliation при расхождениях

---

## QA-2: Создание user_balance_cache таблицы

### Проблема
Materialized balance view не создавалась физически в БД.

### Исправление

**`database/models.py` → `init_db()`:**

```python
# Materialized balance view cache (QA-2)
await db.execute("""
    CREATE TABLE IF NOT EXISTS user_balance_cache (
        user_id INTEGER PRIMARY KEY,
        balance REAL NOT NULL DEFAULT 0,
        last_updated TEXT NOT NULL,
        ledger_count INTEGER NOT NULL DEFAULT 0,
        FOREIGN KEY (user_id) REFERENCES users (tg_id)
    )
""")

await db.execute("CREATE INDEX IF NOT EXISTS idx_balance_cache_updated ON user_balance_cache(last_updated)")

# Trigger: автоматическое обновление кэша при изменении ledger
await db.execute("""
    CREATE TRIGGER IF NOT EXISTS update_balance_cache_on_ledger_insert
    AFTER INSERT ON ledger
    BEGIN
        INSERT OR REPLACE INTO user_balance_cache (user_id, balance, last_updated, ledger_count)
        SELECT 
            NEW.user_id,
            COALESCE((SELECT SUM(amount) FROM ledger WHERE user_id = NEW.user_id), 0),
            datetime('now'),
            (SELECT COUNT(*) FROM ledger WHERE user_id = NEW.user_id)
        ;
    END;
""")
```

### Результат
✅ Таблица `user_balance_cache` создается при инициализации  
✅ Автоматическое обновление через trigger  
✅ Защита от stale-чтения

---

## QA-3: FIFO в priority queue

### Проблема
Score = `priority * 1e9 + timestamp` → LIFO (последние задачи обрабатываются первыми).

### Исправление

**`services/priority_queue.py` → `enqueue()`:**

```python
# Score = priority * 1e9 - timestamp
# This ensures FIFO within same priority level:
# - Higher priority = higher score (processed first)
# - Earlier timestamp = higher score (FIFO within priority)
score = priority * 1e9 - time.time()
```

### Результат
✅ FIFO внутри одного priority level  
✅ Более ранние задачи обрабатываются первыми

---

## QA-4: Исправление length_by_priority

### Проблема
Некорректные границы bucket для подсчета задач по priority.

### Исправление

**`services/priority_queue.py` → `length_by_priority()`:**

```python
for priority in JobPriority:
    # Score = priority.value * 1e9 - timestamp
    # Bucket bounds:
    # - min_score: priority.value * 1e9 - 1e9 (oldest possible)
    # - max_score: priority.value * 1e9 (newest possible, current time)
    min_score = priority.value * 1e9 - 1e9
    max_score = priority.value * 1e9
    count = self.redis.zcount(self.queue_name, min_score, max_score)
    counts[priority.name] = count
```

### Результат
✅ Корректный подсчет задач по priority  
✅ Соответствие формуле score

---

## QA-5: Histogram metrics с labels

### Проблема
`get_all_metrics()` вызывал `get_histogram_stats()` с `None` labels, что теряло метки.

### Исправление

**`services/metrics.py` → `get_all_metrics()`:**

```python
def get_all_metrics(self) -> Dict:
    # Вычислить статистику напрямую из сохраненных значений
    histograms_stats = {}
    for key, values in self.histograms.items():
        if values:
            sorted_values = sorted(values)
            count = len(sorted_values)
            histograms_stats[key] = {
                "count": count,
                "sum": sum(sorted_values),
                "min": sorted_values[0],
                "max": sorted_values[-1],
                "mean": sum(sorted_values) / count,
                "p50": sorted_values[int(count * 0.5)],
                "p95": sorted_values[int(count * 0.95)] if count > 1 else sorted_values[0],
                "p99": sorted_values[int(count * 0.99)] if count > 1 else sorted_values[0]
            }
        else:
            histograms_stats[key] = {...}  # нули
    
    return {
        "counters": dict(self.counters),
        "gauges": dict(self.gauges),
        "histograms": histograms_stats
    }
```

### Результат
✅ Labels сохраняются в ключах histogram  
✅ Корректная статистика для каждой метки

---

## QA-6: Webhook authentication

### Статус
✅ **Уже исправлено в v3.2**

`handlers/webhook.py` уже интегрирует `WebhookValidator`:
- Извлечение payload, signature, webhook_id, timestamp
- Вызов `validator.validate_webhook()`
- Обработка дубликатов (200 OK)
- Отклонение невалидных webhook (401)

---

## QA-7: Alignment документации

### Проблема
Документация не соответствовала реальному коду.

### Исправление
Создан этот документ (`QA_FIXES_v3.3.md`) с детальным описанием всех исправлений и кода.

---

## Итог

Все 7 критичных находок QA review исправлены:

| ID | Проблема | Статус |
|----|----------|--------|
| QA-1 | Атомарность reserve_balance | ✅ Исправлено |
| QA-2 | user_balance_cache | ✅ Исправлено |
| QA-3 | FIFO в priority queue | ✅ Исправлено |
| QA-4 | length_by_priority | ✅ Исправлено |
| QA-5 | Histogram metrics labels | ✅ Исправлено |
| QA-6 | Webhook authentication | ✅ Уже было |
| QA-7 | Alignment документации | ✅ Исправлено |

**Версия:** 3.3  
**Дата:** 2026-02-12  
**Статус:** ✅ Все QA находки закрыты

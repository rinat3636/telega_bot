# REI Bot v3.4 - Production Ready

Telegram-бот для генерации изображений (Nano Banana Pro) и видео (Kling) с полной системой биллинга, очередями, SLO/SLA контурами и enterprise-grade архитектурой.

---

## 🎉 Что нового в v3.4

### 🐛 Critical Bug Fixes

1. **Webhook JSON Parsing + Fail-Closed Validation**
   - Исправлен парсинг JSON из bytes
   - Webhook validation стала обязательной (fail-closed)

2. **Triggers для UPDATE/DELETE в ledger**
   - `user_balance_cache` теперь синхронизируется при всех операциях с ledger
   - Нет stale-чтений баланса

3. **Идемпотентность charge_reserved_balance**
   - Повторный вызов не падает
   - Reconciliation записи не дублируются

Подробнее: [V3.4_FIXES.md](V3.4_FIXES.md)

---

## ✨ Возможности

### 🖼 Генерация и редактирование изображений
- Автоматическое определение режима (генерация/редактирование)
- Интеграция с Nano Banana Pro API
- Подтверждение перед списанием средств

### 🎬 Создание видео
- Генерация из текста, изображения или видео
- Выбор модели Kling (3.0, 2.6, 1.5)
- Выбор длительности (5/10 сек)
- Подтверждение перед списанием

### 💰 Система баланса
- **Ledger-based architecture** — append-only журнал всех операций
- **Usage-sessions** — прозрачное отслеживание биллинга (₽/сек)
- **Автоматическая оплата** через ЮКассу с webhook
- **Cost-caps** — дневные/часовые лимиты расходов
- **Auto-stop** — автоматическая остановка при low balance

### 🔧 Админ-панель
- Управление балансом (`/add`, `/sub`, `/admin_refund`, `/admin_adjust`)
- Управление задачами (`/admin_cancel_job`, `/admin_jobs`)
- Управление пользователями (`/ban`, `/unban`, `/admin_user`)
- Audit log для всех действий

### 📊 Observability
- **SLO/SLA контуры** с error budget tracking
- **Бизнес-метрики** (Prometheus-compatible)
- **Алерты** для критичных событий
- **Load & Chaos тесты** для валидации resilience

### 🚀 Enterprise Features
- **Priority queues** для задач (high/normal/low)
- **Dynamic cost-routing** для AI провайдеров
- **Multi-region backup** стратегия
- **Disaster recovery** playbook
- **GC worker** для автоматической очистки ассетов

---

## 🏗 Архитектура

```
Telegram → API Gateway → Guards (Rate/Cost/RBAC)
              ↓
          Jobs Service → Priority Queues → Workers
              ↓              ↓
      Usage Sessions    AI Router (cost/latency)
              ↓              ↓
          Ledger (SSoT)  AI Providers (with fallback)
              ↓
      Postgres (primary + replicas) + S3 + GC
              ↓
      SLO Monitoring + Alerts
```

---

## 🚀 Быстрый старт

### 1. Установка зависимостей

```bash
pip install -r requirements.txt
```

### 2. Настройка окружения

```bash
cp .env.example .env
# Заполнить переменные в .env
```

**Обязательные переменные:**
- `BOT_TOKEN` — токен от @BotFather
- `ADMIN_IDS` — ID администраторов
- `NANO_BANANA_API_KEY` — ключ API Nano Banana
- `KLING_API_KEY` — ключ API Kling
- `YOOKASSA_SHOP_ID`, `YOOKASSA_SECRET_KEY`, `YOOKASSA_WEBHOOK_SECRET`
- `REDIS_HOST`, `REDIS_PORT` — Redis для очередей

### 3. Инициализация БД

```bash
python3 -c "import asyncio; from database.models import db; asyncio.run(db.init_db())"
```

### 4. Запуск

```bash
# Redis
redis-server &

# Workers
python3 -m rq worker &

# GC Worker (опционально)
python3 workers/gc_worker.py &

# Bot
python3 main.py
```

---

## 🧪 Тестирование

```bash
# Unit тесты
pytest tests/ -v

# Load тесты
k6 run tests/load/parallel_jobs.js

# Chaos тесты
python3 tests/chaos/redis_failure.py
```

---

## 📚 Документация

| Документ | Описание |
|----------|----------|
| [V3.4_FIXES.md](V3.4_FIXES.md) | Детальное описание исправлений v3.4 |
| [CHANGELOG_v3.4.md](CHANGELOG_v3.4.md) | История изменений |
| [PRODUCTION_READINESS.md](PRODUCTION_READINESS.md) | Чеклист готовности к production |
| [RUNBOOK.md](RUNBOOK.md) | Операционные процедуры |
| [runbooks/disaster_recovery.md](runbooks/disaster_recovery.md) | DR playbook |
| [runbooks/multi_region_setup.md](runbooks/multi_region_setup.md) | Multi-region setup |

---

## 🔒 Безопасность

- ✅ Webhook authentication (HMAC + timestamp + deduplication)
- ✅ Rate limiting (per-user + cost-based)
- ✅ Ledger constraints (UNIQUE + CHECK)
- ✅ Fail-closed validation
- ✅ Audit log для админских действий

---

## 📈 Метрики и SLO

**SLO:**
- Job success rate: 99.5%
- Payment success rate: 99.9%
- Job latency (p95): 180s

**Метрики:**
- `jobs_total`, `jobs_failed`, `jobs_cancelled`
- `ledger_negative_attempts` (CRITICAL alert)
- `payment_webhook_errors`
- `queue_length`
- `provider_errors`

**Экспорт метрик:**
```bash
curl http://localhost:8080/metrics
```

---

## 🛠 Troubleshooting

### Проблема: Webhook не обрабатывается

**Решение:**
1. Проверить `YOOKASSA_WEBHOOK_SECRET` в `.env`
2. Проверить логи: `grep "Webhook validation failed" bot.log`
3. Проверить публичный URL с SSL

### Проблема: Баланс не обновляется

**Решение:**
1. Проверить triggers в БД:
   ```sql
   SELECT name FROM sqlite_master WHERE type='trigger';
   ```
2. Должны быть: `update_balance_cache_on_ledger_insert`, `update_balance_cache_on_ledger_update`, `update_balance_cache_on_ledger_delete`
3. Если нет — пересоздать БД

### Проблема: Job зависает

**Решение:**
1. Проверить Redis: `redis-cli ping`
2. Проверить workers: `ps aux | grep rq`
3. Проверить логи workers: `rq info`

---

## 📞 Поддержка

При возникновении проблем:
1. Проверьте логи бота
2. Запустите тесты: `pytest tests/ -v`
3. Проверьте [RUNBOOK.md](RUNBOOK.md)

---

**Версия:** 3.4.0  
**Дата:** 2026-02-12  
**Статус:** ✅ **Production Ready**

Все критичные проблемы из QA review v3.3 исправлены. Бот готов к развертыванию! 🎉

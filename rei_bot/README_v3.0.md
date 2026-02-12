# Telegram-бот «РЭИ» v3.0 — Production Ready "Под ключ"

**Версия:** 3.0.0  
**Дата:** 2026-02-12  
**Статус:** ✅ Production Ready

---

## 🚀 О проекте

**Telegram-бот «РЭИ»** — это production-ready бот для генерации и редактирования изображений и видео с использованием AI.

**Основные возможности:**
- 🖼 **Изображения:** Генерация и редактирование (Nano Banana Pro)
- 🎬 **Видео:** Генерация из текста/фото/видео (Kling)
- 💰 **Баланс:** Ledger-based система баланса с защитой от гонок
- 💳 **Оплата:** Автоматическая оплата через YooKassa
- ⚙️ **Очередь:** Асинхронная обработка задач через Redis + RQ
- 🛡️ **Безопасность:** Защита от replay-атак, rate-limiting, cost-capping
- 🛠️ **Админка:** Управление пользователями и задачами

---

## ✨ Новое в v3.0

| Фича | Описание | Статус |
| --- | --- | --- |
| **Инварианты ledger** | Защита от некорректных операций с балансом | ✅ |
| **Глобальный lock** | Защита от параллельного создания job | ✅ |
| **Deadline/cancel/retry** | Задачи не зависают, можно отменить, есть retry | ✅ |
| **Replay protection** | Защита webhook от replay-атак | ✅ |
| **Redis rate-limit** | Централизованный rate-limit для horizontal scaling | ✅ |

---

## 🚀 Быстрый старт

### 1. Требования

- Python 3.11+
- Redis Server
- Публичный URL с SSL (для webhook YooKassa)

### 2. Установка

```bash
# 1. Клонировать репозиторий

# 2. Установить зависимости
pip3 install -r requirements.txt

# 3. Настроить .env
cp .env.example .env
# Заполнить .env
```

### 3. Переменные окружения (.env)

```ini
# Telegram Bot
BOT_TOKEN=your_bot_token_from_botfather
ADMIN_IDS=123456789,987654321

# AI Providers
NANO_BANANA_API_KEY=your_nano_banana_api_key
KLING_API_KEY=your_kling_api_key
KLING_MODELS=kling-3.0:Kling 3.0,kling-2.6:Kling 2.6,kling-1.5:Kling 1.5

# YooKassa Payment
YOOKASSA_SHOP_ID=your_shop_id
YOOKASSA_SECRET_KEY=your_secret_key

# Redis
REDIS_URL=redis://localhost:6379

# Database
DATABASE_PATH=rei_bot.db

# Pricing (in rubles)
IMAGE_GENERATION_PRICE=50
IMAGE_EDIT_PRICE=30
VIDEO_5SEC_PRICE=100
VIDEO_10SEC_MULTIPLIER=2

# Rate Limiting
MAX_ACTIVE_JOBS_PER_USER=3
COST_LIMIT_PER_HOUR=1000

# Webhook Security
WEBHOOK_SECRET_KEY=your_webhook_secret_key
WEBHOOK_TIMESTAMP_WINDOW=300

# Job Settings
JOB_DEFAULT_DEADLINE_MINUTES=30
JOB_MAX_RUNTIME_SECONDS=300
JOB_MAX_RETRIES=3
```

### 4. Запуск

```bash
# 1. Запустить Redis
redis-server

# 2. Запустить workers
python3 -m rq worker -c workers.config

# 3. Запустить бота
python3 main.py
```

---

## 📚 Документация

- **CHANGELOG_v3.0.md:** История изменений v3.0
- **ARCHITECTURE_v3.md:** Архитектура исправлений v3.0
- **YOOKASSA_SETUP.md:** Настройка автоматической оплаты
- **launch_instruction.md:** Инструкция по запуску

---

## ✅ Итог

Бот готов к развертыванию в production с высоким уровнем надежности и безопасности. Все критичные проблемы решены.

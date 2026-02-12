"""
Главный файл бота РЭИ
"""
import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

import config
from database import db
from handlers import common, images, videos, balance, admin, global_commands
from services.webhook_validator import init_webhook_validator


# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def main():
    """Главная функция запуска бота"""
    # Проверка конфигурации
    if not config.BOT_TOKEN:
        logger.error("BOT_TOKEN не установлен в .env файле")
        return
    
    # Инициализация бота и диспетчера
    bot = Bot(token=config.BOT_TOKEN)
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)
    
    # Инициализация базы данных
    logger.info("Инициализация базы данных...")
    await db.init_db()
    
    # Инициализация webhook validator (с Database deduplication)
    if config.YOOKASSA_SECRET_KEY and config.ENABLE_WEBHOOKS:
        logger.info("Инициализация webhook validator...")
        init_webhook_validator(
            secret_key=config.YOOKASSA_SECRET_KEY,
            db_instance=db  # Использовать БД для deduplication
        )
    else:
        if not config.YOOKASSA_SECRET_KEY:
            logger.warning("Webhook validator не инициализирован: YOOKASSA_SECRET_KEY не настроен")
        if not config.ENABLE_WEBHOOKS:
            logger.info("Webhooks отключены (ENABLE_WEBHOOKS=0)")
    
    # Регистрация роутеров (условно по флагам)
    dp.include_router(common.router)
    dp.include_router(admin.router)
    
    if config.ENABLE_PAYMENTS:
        dp.include_router(balance.router)
        logger.info("Платежи включены")
    else:
        logger.info("Платежи выключены (ENABLE_PAYMENTS=0)")
    
    if config.ENABLE_VIDEOS:
        dp.include_router(videos.router)
        logger.info("Генерация видео включена")
    else:
        logger.info("Генерация видео выключена (ENABLE_VIDEOS=0)")
    
    if config.ENABLE_IMAGES:
        dp.include_router(images.router)  # Последним, т.к. обрабатывает текст
        logger.info("Генерация изображений включена")
    else:
        logger.info("Генерация изображений выключена (ENABLE_IMAGES=0)")
    
    # Глобальные команды и fallback (ВСЕГДА последним!)
    dp.include_router(global_commands.router)
    logger.info("Глобальные команды и fallback зарегистрированы")
    
    # Запуск бота
    logger.info("Бот запущен")
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен")

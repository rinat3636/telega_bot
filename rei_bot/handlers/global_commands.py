"""
Обработчики глобальных команд и fallback для непонятных сообщений
"""
import logging
from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import Command

from database import db


logger = logging.getLogger(__name__)
router = Router()


# Глобальные команды (работают всегда, из любого состояния)
@router.message(Command("menu"))
@router.message(F.text.lower().in_(["меню", "menu", "главное меню", "в меню"]))
async def cmd_menu(message: Message):
    """Глобальная команда возврата в главное меню"""
    from handlers.common import cmd_start  # Избегаем циклического импорта
    await cmd_start(message)


@router.message(Command("help"))
@router.message(F.text.lower().in_(["помощь", "help", "справка"]))
async def cmd_help(message: Message):
    """Глобальная команда помощи"""
    user_id = message.from_user.id
    balance = await db.get_balance(user_id)
    
    help_text = (
        "🤖 <b>Справка по боту РЭИ</b>\n\n"
        
        "<b>📌 Основные команды:</b>\n"
        "/start — Главное меню\n"
        "/menu — Вернуться в меню\n"
        "/balance — Проверить баланс\n"
        "/pay — Пополнить баланс\n"
        "/help — Эта справка\n\n"
        
        "<b>🎨 Что умеет бот:</b>\n"
        "• Генерация изображений (NanoBanana)\n"
        "• Редактирование изображений\n"
        "• Создание видео из текста (Kling)\n"
        "• Создание видео из изображения\n\n"
        
        "<b>💰 Ваш баланс:</b> {balance} ₽\n\n"
        
        "<b>💡 Совет:</b>\n"
        "Просто выберите нужную функцию в меню и следуйте подсказкам. "
        "Если что-то непонятно — напишите \"меню\" или \"помощь\"."
    ).format(balance=balance)
    
    await message.answer(help_text, parse_mode="HTML")


@router.message(F.text.lower().in_(["назад", "отмена", "cancel", "back"]))
async def cmd_back(message: Message):
    """Глобальная команда возврата назад"""
    await message.answer(
        "↩️ Возвращаемся в главное меню...",
        parse_mode="HTML"
    )
    from handlers.common import cmd_start
    await cmd_start(message)


@router.message(F.text.lower().in_(["начать заново", "restart", "reset"]))
async def cmd_restart(message: Message):
    """Глобальная команда начать заново"""
    await message.answer(
        "🔄 Начинаем заново...",
        parse_mode="HTML"
    )
    from handlers.common import cmd_start
    await cmd_start(message)


# Fallback для всех остальных сообщений (должен быть последним)
@router.message()
async def fallback_handler(message: Message):
    """
    Fallback-обработчик для непонятных сообщений
    Регистрируется последним, чтобы ловить все необработанные сообщения
    """
    logger.info(f"Fallback: user {message.from_user.id} sent: {message.text[:50]}")
    
    fallback_text = (
        "🤔 Я не понял ваше сообщение.\n\n"
        "Попробуйте:\n"
        "• Нажать на кнопки ниже 👇\n"
        "• Написать \"меню\" для возврата в главное меню\n"
        "• Написать \"помощь\" для справки\n\n"
        "Или просто используйте команды:\n"
        "/start — Главное меню\n"
        "/help — Справка"
    )
    
    await message.answer(fallback_text, parse_mode="HTML")

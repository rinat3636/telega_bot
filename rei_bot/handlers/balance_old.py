"""rei_bot.handlers.balance

Баланс пользователя: команда /balance и кнопка "💰 Баланс".
Автоматическая оплата через ЮКассу.
"""

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from database import db
from services.yookassa_payment import yookassa_service
import logging


router = Router()
logger = logging.getLogger(__name__)


class PaymentStates(StatesGroup):
    waiting_for_amount = State()


async def show_balance_info(message: Message):
    """Показать баланс пользователя"""
    user_id = message.from_user.id
    
    # Получаем или создаем пользователя
    await db.get_or_create_user(user_id)
    
    # Получаем баланс
    balance = await db.get_balance(user_id)
    
    await message.answer(
        f"💰 <b>Ваш баланс</b>\n\n"
        f"Доступно: <b>{balance} ₽</b>\n\n"
        f"Для пополнения: /pay",
        parse_mode="HTML"
    )


@router.message(Command("balance"))
async def show_balance_command(message: Message):
    """Команда /balance"""
    await show_balance_info(message)


@router.message(F.text == "💰 Баланс")
async def show_balance_button(message: Message):
    """Кнопка 💰 Баланс"""
    await show_balance_info(message)


@router.message(Command("pay"))
async def payment_menu(message: Message, state: FSMContext):
    """Меню пополнения баланса"""
    await state.clear()
    
    user_id = message.from_user.id
    balance = await db.get_balance(user_id)
    
    text = (
        f"💳 <b>Пополнение баланса</b>\n\n"
        f"Текущий баланс: <b>{balance} ₽</b>\n\n"
        f"Выберите сумму пополнения или введите свою:"
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="100 ₽", callback_data="pay_100"),
            InlineKeyboardButton(text="500 ₽", callback_data="pay_500")
        ],
        [
            InlineKeyboardButton(text="1000 ₽", callback_data="pay_1000"),
            InlineKeyboardButton(text="2000 ₽", callback_data="pay_2000")
        ],
        [InlineKeyboardButton(text="✏️ Своя сумма", callback_data="pay_custom")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="pay_cancel")]
    ])
    
    await message.answer(text, reply_markup=keyboard, parse_mode="HTML")


@router.callback_query(F.data.startswith("pay_") & ~F.data.in_(["pay_custom", "pay_cancel"]))
async def process_payment_preset(callback: CallbackQuery):
    """Обработка выбора предустановленной суммы"""
    await callback.answer()
    
    # Извлекаем сумму из callback_data
    amount_str = callback.data.split("_")[1]
    amount = int(amount_str)
    
    await create_payment_link(callback.message, callback.from_user.id, amount)


@router.callback_query(F.data == "pay_custom")
async def request_custom_amount(callback: CallbackQuery, state: FSMContext):
    """Запрос пользовательской суммы"""
    await callback.answer()
    
    await state.set_state(PaymentStates.waiting_for_amount)
    
    await callback.message.edit_text(
        "✏️ Введите сумму пополнения (от 100 до 15000 рублей):"
    )


@router.message(PaymentStates.waiting_for_amount)
async def process_custom_amount(message: Message, state: FSMContext):
    """Обработка пользовательской суммы"""
    await state.clear()
    
    try:
        amount = int(message.text)
        
        if amount < 100:
            await message.answer("⚠️ Минимальная сумма пополнения — 100 ₽")
            return
        
        if amount > 15000:
            await message.answer("⚠️ Максимальная сумма пополнения — 15000 ₽")
            return
        
        await create_payment_link(message, message.from_user.id, amount)
        
    except ValueError:
        await message.answer("⚠️ Введите корректную сумму (целое число)")


async def create_payment_link(message: Message, user_id: int, amount: int):
    """Создание ссылки на оплату"""
    
    if not yookassa_service.enabled:
        await message.answer(
            "⚠️ <b>Автоматическая оплата временно недоступна</b>\n\n"
            "Для пополнения баланса свяжитесь с администратором.",
            parse_mode="HTML"
        )
        return
    
    # Создание платежа через YooKassa
    result = yookassa_service.create_payment(
        amount=amount,
        description=f"Пополнение баланса бота РЭИ на {amount} ₽",
        user_id=user_id
    )
    
    if not result["success"]:
        logger.error(f"Ошибка создания платежа для пользователя {user_id}: {result.get('error')}")
        await message.answer(
            "⚠️ Произошла ошибка при создании платежа.\n"
            "Попробуйте позже или свяжитесь с администратором."
        )
        return
    
    payment_id = result["payment_id"]
    confirmation_url = result["confirmation_url"]
    
    # Сохраняем информацию о платеже в БД
    await db.create_payment(
        user_id=user_id,
        provider_payment_id=payment_id,
        amount=amount,
        status="pending"
    )
    
    logger.info(f"Создан платеж {payment_id} для пользователя {user_id} на сумму {amount} ₽")
    
    text = (
        f"💳 <b>Пополнение баланса</b>\n\n"
        f"Сумма: <b>{amount} ₽</b>\n"
        f"Платеж: <code>{payment_id}</code>\n\n"
        f"Нажмите кнопку ниже для оплаты.\n"
        f"После успешной оплаты баланс будет пополнен автоматически."
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Оплатить", url=confirmation_url)],
        [InlineKeyboardButton(text="🔄 Проверить оплату", callback_data=f"check_payment_{payment_id}")]
    ])
    
    await message.answer(text, reply_markup=keyboard, parse_mode="HTML")


@router.callback_query(F.data.startswith("check_payment_"))
async def check_payment_status(callback: CallbackQuery):
    """Проверка статуса платежа"""
    await callback.answer("Проверяем статус платежа...")
    
    payment_id = callback.data.split("check_payment_")[1]
    
    # Проверка платежа через YooKassa
    result = yookassa_service.check_payment(payment_id)
    
    if not result["success"]:
        await callback.message.edit_text(
            f"⚠️ Ошибка проверки платежа\n\n"
            f"Платеж: <code>{payment_id}</code>\n"
            f"Ошибка: {result.get('error')}",
            parse_mode="HTML"
        )
        return
    
    status = result["status"]
    paid = result["paid"]
    amount = result["amount"]
    user_id = result["user_id"]
    
    if paid and status == "succeeded":
        # Платеж успешен - начисляем баланс (идемпотентно)
        # Проверяем, не обработан ли уже платеж
        existing_payment = await db.get_payment_by_provider_id(payment_id)
        if existing_payment and existing_payment['status'] == 'paid':
            # Платеж уже обработан
            new_balance = await db.get_balance(user_id)
            await callback.message.edit_text(
                f"✅ <b>Платеж уже был обработан</b>\n\n"
                f"Сумма: <b>{amount} ₽</b>\n"
                f"Текущий баланс: <b>{new_balance} ₽</b>",
                parse_mode="HTML"
            )
            return
        
        # Начисляем через ledger с уникальным ref_id
        try:
            await db.add_ledger_entry(
                user_id=user_id,
                entry_type='credit',
                amount=amount,
                ref_type='payment',
                ref_id=payment_id,
                description=f'Пополнение через YooKassa'
            )
            await db.update_payment_status(payment_id, "paid")
        except Exception as e:
            # Если UNIQUE constraint - платеж уже обработан
            logger.warning(f"Платеж {payment_id} уже обработан (идемпотентность): {e}")
            await db.update_payment_status(payment_id, "paid")
        
        new_balance = await db.get_balance(user_id)
        
        await callback.message.edit_text(
            f"✅ <b>Платеж успешно выполнен!</b>\n\n"
            f"Зачислено: <b>{amount} ₽</b>\n"
            f"Новый баланс: <b>{new_balance} ₽</b>\n\n"
            f"Спасибо за пополнение!",
            parse_mode="HTML"
        )
        
        logger.info(f"Платеж {payment_id} успешно обработан. Пользователь {user_id} пополнил баланс на {amount} ₽")
        
    elif status == "canceled":
        await db.update_payment_status(payment_id, "canceled")
        
        await callback.message.edit_text(
            f"❌ <b>Платеж отменен</b>\n\n"
            f"Платеж: <code>{payment_id}</code>\n\n"
            f"Для нового пополнения используйте /pay",
            parse_mode="HTML"
        )
        
    elif status == "pending":
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💳 Оплатить", callback_data=f"pay_link_{payment_id}")],
            [InlineKeyboardButton(text="🔄 Проверить снова", callback_data=f"check_payment_{payment_id}")]
        ])
        
        await callback.message.edit_text(
            f"⏳ <b>Ожидание оплаты</b>\n\n"
            f"Платеж: <code>{payment_id}</code>\n"
            f"Сумма: <b>{amount} ₽</b>\n\n"
            f"Статус: ожидание оплаты\n\n"
            f"Нажмите кнопку для оплаты или проверьте статус позже.",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
    
    else:
        await callback.message.edit_text(
            f"⏳ <b>Обработка платежа</b>\n\n"
            f"Платеж: <code>{payment_id}</code>\n"
            f"Статус: {status}\n\n"
            f"Проверьте статус через несколько минут.",
            parse_mode="HTML"
        )


@router.callback_query(F.data.startswith("pay_link_"))
async def get_payment_link(callback: CallbackQuery):
    """Получение ссылки на оплату"""
    await callback.answer()
    
    payment_id = callback.data.split("pay_link_")[1]
    
    # Проверяем платеж через YooKassa
    result = yookassa_service.check_payment(payment_id)
    
    if not result["success"]:
        await callback.message.answer(
            f"⚠️ Ошибка получения ссылки на оплату\n\n"
            f"Используйте /pay для создания нового платежа."
        )
        return
    
    # Получаем ссылку из БД (если сохранена) или из API
    # TODO: Добавить confirmation_url в БД для полной реализации
    await callback.message.answer(
        f"💳 Для оплаты используйте кнопку '💳 Оплатить' выше или создайте новый платеж через /pay"
    )


@router.callback_query(F.data == "pay_cancel")
async def cancel_payment(callback: CallbackQuery, state: FSMContext):
    """Отмена пополнения"""
    await callback.answer()
    await state.clear()
    await callback.message.edit_text("❌ Пополнение отменено")

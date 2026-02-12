"""
Обработчики баланса и платежей (production-ready)

Баланс пользователя: команда /balance и кнопка "💰 Баланс".
Автоматическая оплата через ЮКассу с идемпотентностью.
"""

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from datetime import datetime, timedelta
import logging

from database import db
from services.yookassa_payment import yookassa_service


router = Router()
logger = logging.getLogger(__name__)


# Фиксированные суммы пополнения (₽)
PAYMENT_AMOUNTS = [100, 150, 200, 500, 1000]

# Rate limiting: максимум платежей в час
MAX_PAYMENTS_PER_HOUR = 10


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


@router.message(F.text == "💳 Пополнить баланс")
@router.message(Command("pay"))
async def payment_menu(message: Message, state: FSMContext):
    """Меню пополнения баланса с фиксированными суммами"""
    await state.clear()
    
    # Проверка ENABLE_PAYMENTS
    import config
    if not config.ENABLE_PAYMENTS:
        await message.answer("⚠️ Пополнение баланса временно отключено")
        return
    
    user_id = message.from_user.id
    balance = await db.get_balance(user_id)
    
    text = (
        f"💳 <b>Выбери сумму пополнения</b>\n\n"
        f"💡 100 ₽ ≈ ~10 изображений\n"
        f"💡 500 ₽ выгоднее для видео"
    )
    
    # Создаем кнопки для фиксированных сумм
    keyboard_rows = []
    for i in range(0, len(PAYMENT_AMOUNTS), 2):
        row = []
        for j in range(2):
            if i + j < len(PAYMENT_AMOUNTS):
                amount = PAYMENT_AMOUNTS[i + j]
                row.append(InlineKeyboardButton(
                    text=f"{amount} ₽",
                    callback_data=f"pay_amount_{amount}"
                ))
        keyboard_rows.append(row)
    
    # Добавляем кнопку "Другая сумма" (опционально)
    # keyboard_rows.append([InlineKeyboardButton(text="✏️ Другая сумма", callback_data="pay_custom")])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)
    
    await message.answer(text, reply_markup=keyboard, parse_mode="HTML")


@router.callback_query(F.data.startswith("pay_amount_"))
async def process_payment_amount(callback: CallbackQuery):
    """Обработка выбора суммы пополнения"""
    await callback.answer()
    
    # Извлекаем сумму из callback_data
    try:
        amount = int(callback.data.split("_")[-1])
    except ValueError:
        await callback.message.edit_text("⚠️ Ошибка: неверная сумма")
        return
    
    # Валидация суммы
    if amount not in PAYMENT_AMOUNTS:
        await callback.message.edit_text("⚠️ Ошибка: недопустимая сумма")
        return
    
    user_id = callback.from_user.id
    
    # Rate limiting: проверить количество платежей за последний час
    recent_payments = await db.get_user_payments_since(
        user_id,
        since=datetime.now() - timedelta(hours=1)
    )
    
    if len(recent_payments) >= MAX_PAYMENTS_PER_HOUR:
        await callback.message.edit_text(
            f"⚠️ Превышен лимит создания платежей\n\n"
            f"Максимум {MAX_PAYMENTS_PER_HOUR} платежей в час.\n"
            f"Попробуйте позже."
        )
        return
    
    # Создать платеж
    await create_payment_for_user(callback.message, user_id, amount)


async def create_payment_for_user(message: Message, user_id: int, amount: int):
    """
    Создать платеж для пользователя
    
    Args:
        message: Сообщение для редактирования
        user_id: ID пользователя
        amount: Сумма платежа
    """
    try:
        # Создать платеж у провайдера (YooKassa)
        payment_result = await yookassa_service.create_payment(user_id, amount)
        
        if not payment_result or "error" in payment_result:
            error_msg = payment_result.get("error", "Unknown error") if payment_result else "Payment service unavailable"
            logger.error(f"Payment creation failed for user {user_id}: {error_msg}")
            await message.edit_text(
                f"⚠️ Ошибка создания платежа\n\n"
                f"Попробуйте позже или обратитесь в поддержку."
            )
            return
        
        provider_payment_id = payment_result["id"]
        confirmation_url = payment_result.get("confirmation_url")
        expires_at = payment_result.get("expires_at")
        
        if not confirmation_url:
            logger.error(f"No confirmation_url in payment result: {payment_result}")
            await message.edit_text("⚠️ Ошибка: не получена ссылка на оплату")
            return
        
        # Сохранить платеж в БД
        payment_id = await db.create_payment(
            user_id=user_id,
            provider_payment_id=provider_payment_id,
            amount=amount,
            confirmation_url=confirmation_url,
            status="pending",
            expires_at=expires_at
        )
        
        if payment_id is None:
            # Платеж с таким provider_payment_id уже существует
            logger.warning(f"Payment {provider_payment_id} already exists for user {user_id}")
            await message.edit_text(
                "⚠️ Платеж уже создан\n\n"
                "Проверьте статус существующего платежа."
            )
            return
        
        # Отправить сообщение с кнопкой оплаты
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💳 Оплатить", url=confirmation_url)],
            [InlineKeyboardButton(
                text="✅ Проверить оплату",
                callback_data=f"check_payment_{provider_payment_id}"
            )]
        ])
        
        await message.edit_text(
            f"💳 <b>Платёж создан</b>\n\n"
            f"Сумма: <b>{amount} ₽</b>\n"
            f"Статус: ожидает оплаты\n\n"
            f"После оплаты баланс пополнится автоматически 👇\n"
            f"После оплаты нажмите «Проверить оплату».",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        
        logger.info(f"Payment created: user={user_id}, amount={amount}, provider_id={provider_payment_id}")
    
    except Exception as e:
        logger.error(f"Error creating payment for user {user_id}: {e}", exc_info=True)
        await message.edit_text(
            "⚠️ Произошла ошибка при создании платежа.\n\n"
            "Попробуйте позже."
        )


@router.callback_query(F.data.startswith("check_payment_"))
async def check_payment_status(callback: CallbackQuery):
    """
    Проверить статус платежа (идемпотентно)
    
    Гарантирует, что платеж будет начислен строго один раз,
    даже при повторных нажатиях кнопки.
    """
    await callback.answer()
    
    # Извлечь provider_payment_id из callback_data
    provider_payment_id = callback.data.replace("check_payment_", "")
    user_id = callback.from_user.id
    
    try:
        # Получить платеж из БД
        payment = await db.get_payment_by_provider_id(provider_payment_id)
        
        if not payment:
            await callback.message.edit_text("⚠️ Платеж не найден")
            return
        
        # Проверить, что платеж принадлежит пользователю
        if payment["user_id"] != user_id:
            logger.warning(f"User {user_id} tried to check payment {provider_payment_id} of user {payment['user_id']}")
            await callback.answer("⚠️ Это не ваш платеж", show_alert=True)
            return
        
        # Если платеж уже обработан (paid) - сообщить об этом
        if payment["status"] == "paid":
            await callback.message.edit_text(
                f"✅ <b>Платеж уже обработан</b>\n\n"
                f"Сумма: <b>{payment['amount']} ₽</b>\n"
                f"Баланс начислен ранее.",
                parse_mode="HTML"
            )
            return
        
        # Проверить статус у провайдера
        status_result = await yookassa_service.check_payment_status(provider_payment_id)
        
        if not status_result or "error" in status_result:
            error_msg = status_result.get("error", "Unknown error") if status_result else "Service unavailable"
            await callback.message.edit_text(
                f"⚠️ Ошибка проверки статуса\n\n"
                f"{error_msg}\n\n"
                f"Попробуйте позже."
            )
            return
        
        provider_status = status_result.get("status")
        
        if provider_status in ["succeeded", "paid"]:
            # Платеж оплачен - начислить баланс атомарно
            
            # Использовать атомарный метод process_paid_payment
            # Он выполняет в одной транзакции:
            # 1. Проверку статуса
            # 2. Добавление в ledger
            # 3. Обновление статуса
            result = await db.process_paid_payment(
                provider_payment_id=provider_payment_id,
                user_id=user_id,
                amount=payment["amount"]
            )
            
            if not result.get("success"):
                logger.error(f"Failed to process payment {provider_payment_id}: {result.get('error')}")
                await callback.message.edit_text(
                    "⚠️ Ошибка обработки платежа\n\n"
                    "Обратитесь в поддержку."
                )
                return
            
            if result.get("already_processed"):
                logger.info(f"Payment {provider_payment_id} already processed")
                await callback.message.edit_text(
                    f"✅ <b>Платеж уже обработан</b>\n\n"
                    f"Сумма: <b>{payment['amount']} ₽</b>\n"
                    f"Текущий баланс: <b>{result['new_balance']} ₽</b>",
                    parse_mode="HTML"
                )
            else:
                logger.info(f"Payment processed: user={user_id}, amount={payment['amount']}, provider_id={provider_payment_id}")
                await callback.message.edit_text(
                    f"✅ <b>Оплата прошла успешно</b>\n\n"
                    f"💰 Баланс пополнен на <b>{payment['amount']} ₽</b>\n\n"
                    f"Готовы создать что-нибудь?",
                    parse_mode="HTML"
                )
        
        elif provider_status == "pending":
            await callback.message.edit_text(
                f"⏳ <b>Платеж в обработке</b>\n\n"
                f"Сумма: <b>{payment['amount']} ₽</b>\n"
                f"Статус: <i>ожидает оплаты</i>\n\n"
                f"Попробуйте проверить позже.",
                parse_mode="HTML"
            )
        
        elif provider_status == "canceled":
            await db.update_payment_status(provider_payment_id, "canceled")
            await callback.message.edit_text(
                f"❌ <b>Платеж отменен</b>\n\n"
                f"Сумма: <b>{payment['amount']} ₽</b>\n\n"
                f"Создайте новый платеж: /pay",
                parse_mode="HTML"
            )
        
        else:
            await callback.message.edit_text(
                f"⚠️ Неизвестный статус платежа: {provider_status}\n\n"
                f"Обратитесь в поддержку."
            )
    
    except Exception as e:
        logger.error(f"Error checking payment {provider_payment_id}: {e}", exc_info=True)
        await callback.message.edit_text(
            "⚠️ Произошла ошибка при проверке платежа.\n\n"
            "Попробуйте позже."
        )

"""
Обработчики для работы с изображениями (Nano Banana Pro)
"""
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from database import db
from services.nano_banana import nano_banana_service
from utils.helpers import get_file_for_api
from utils.pricing import get_price, PricingAction
import config
import logging


router = Router()
logger = logging.getLogger(__name__)


class ImageStates(StatesGroup):
    waiting_for_edit_description = State()
    confirming_generation = State()
    confirming_edit = State()


@router.message(F.text == "🖼 Изображения")
async def images_menu(message: Message, state: FSMContext):
    """Главное меню работы с изображениями"""
    await state.clear()
    
    text = (
        "🖼 <b>Nano Banana Pro</b>\n\n"
        "✏️ Чтобы отредактировать изображение —\n"
        "отправьте фото и напишите, что изменить\n\n"
        "🎨 Чтобы создать изображение —\n"
        "просто напишите текст"
    )
    
    await message.answer(text, parse_mode="HTML")


@router.message(F.photo)
async def handle_photo(message: Message, state: FSMContext):
    """Обработка фотографии"""
    # Проверка бана
    if await db.is_banned(message.from_user.id):
        await message.answer("❌ Вы заблокированы")
        return
    
    # Если есть подпись - это редактирование
    if message.caption:
        await show_edit_confirmation(message, message.caption, message.photo[-1].file_id, state)
    else:
        # Запрашиваем описание
        await state.set_state(ImageStates.waiting_for_edit_description)
        await state.update_data(photo_file_id=message.photo[-1].file_id)
        await message.answer(
            "✏️ Отправьте описание того, что нужно изменить на изображении"
        )


@router.message(ImageStates.waiting_for_edit_description)
async def handle_edit_description(message: Message, state: FSMContext):
    """Обработка описания для редактирования"""
    data = await state.get_data()
    photo_file_id = data.get("photo_file_id")
    
    if not photo_file_id:
        await message.answer("⚠️ Ошибка: фото не найдено. Отправьте фото заново.")
        await state.clear()
        return
    
    await show_edit_confirmation(message, message.text, photo_file_id, state)


async def show_edit_confirmation(message: Message, prompt: str, photo_file_id: str, state: FSMContext):
    """Показать экран подтверждения редактирования"""
    user_id = message.from_user.id
    balance = await db.get_balance(user_id)
    
    # Получить цену из БД с fallback на config
    price = await get_price(db, provider="nano_banana", action=PricingAction.IMAGE_EDIT)
    
    # Сохраняем данные в FSM
    await state.set_state(ImageStates.confirming_edit)
    await state.update_data(
        prompt=prompt,
        photo_file_id=photo_file_id
    )
    
    text = (
        f"✏️ <b>Редактирование изображения</b>\n\n"
        f"Описание: {prompt}\n\n"
        f"💰 Стоимость: <b>{price} ₽</b>\n"
        f"💳 Ваш баланс: <b>{balance} ₽</b>\n\n"
    )
    
    if balance < price:
        text += "❌ Недостаточно средств для выполнения операции"
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="image_cancel")]
        ])
    else:
        text += "Подтвердите запуск:"
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="▶️ Запустить", callback_data="image_edit_confirm")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="image_cancel")]
        ])
    
    await message.answer(text, reply_markup=keyboard, parse_mode="HTML")


@router.callback_query(F.data == "image_edit_confirm")
async def confirm_image_edit(callback: CallbackQuery, state: FSMContext):
    """Подтверждение редактирования изображения"""
    await callback.answer()
    
    data = await state.get_data()
    prompt = data.get("prompt")
    photo_file_id = data.get("photo_file_id")
    
    await state.clear()
    
    user_id = callback.from_user.id
    
    # Получить цену из БД с fallback на config
    price = await get_price(db, provider="nano_banana", action=PricingAction.IMAGE_EDIT)
    
    # Резервирование средств (атомарно)
    reserve_ref_id = f"image_edit_{user_id}_{callback.message.message_id}"
    reserved = await db.reserve_balance(
        user_id=user_id,
        amount=price,
        ref_id=reserve_ref_id
    )
    
    if not reserved:
        balance = await db.get_balance(user_id)
        await callback.message.edit_text(
            f"❌ Недостаточно средств\n"
            f"Требуется: {price} ₽\n"
            f"Ваш баланс: {balance} ₽\n\n"
            f"Пополните баланс: /pay"
        )
        return
    
    # Создание задачи
    job_id = await db.create_job(
        user_id=user_id,
        job_type="image",
        params={
            "action": "edit",
            "provider": "nano_banana",
            "prompt": prompt,
            "input_file_id": photo_file_id,
            "reserve_ref_id": reserve_ref_id
        },
        cost_estimate=price
    )
    
    logger.info(f"User {user_id} started image edit, reserved {price} ₽, job_id={job_id}")
    
    # Статус
    await callback.message.edit_text(
        "✏️ <b>Редактирование изображения…</b>\n"
        "⏳ Обычно занимает 1–3 минуты",
        parse_mode="HTML"
    )
    
    # Обновление статуса
    await db.update_job_status(job_id, "processing")
    
    # Скачивание фото
    try:
        image_data = await get_file_for_api(callback.bot, photo_file_id, "image.jpg")
    except Exception as e:
        await db.update_job_status(job_id, "failed", error_message=str(e))
        # Возврат зарезервированных средств
        await db.refund_balance(
            user_id=user_id,
            reserve_ref_id=reserve_ref_id,
            new_ref_id=f"job_{job_id}_refund",
            description="Возврат за ошибку загрузки файла"
        )
        await callback.message.edit_text(
            "⚠️ Не удалось обработать изображение.\n"
            "Средства возвращены."
        )
        logger.error(f"Image edit job {job_id} failed at file download: {e}")
        return
    
    # Вызов API
    result = await nano_banana_service.edit_image(image_data, prompt)
    
    if result["success"]:
        # Успех - списываем зарезервированные средства
        # Получить цену из job params
        job = await db.get_job(job_id)
        actual_price = job['cost_estimate']
        
        await db.charge_reserved_balance(
            user_id=user_id,
            reserve_ref_id=reserve_ref_id,
            actual_amount=actual_price,
            new_ref_id=f"job_{job_id}",
            description=f"Редактирование изображения"
        )
        await db.update_job_status(job_id, "completed", result_url=result["image_url"])
        logger.info(f"Image edit job {job_id} completed successfully")
        
        try:
            await callback.message.answer_photo(
                photo=result["image_url"],
                caption="✅ Изображение готово"
            )
            await callback.message.delete()
        except Exception as e:
            await callback.message.edit_text(
                f"✅ Изображение готово\n\n"
                f"Ссылка: {result['image_url']}"
            )
    else:
        # Ошибка - возвращаем средства
        await db.update_job_status(job_id, "failed", error_message=result.get("error", "Unknown error"))
        await db.refund_balance(
            user_id=user_id,
            reserve_ref_id=reserve_ref_id,
            new_ref_id=f"job_{job_id}_refund",
            description="Возврат за ошибку API"
        )
        await callback.message.edit_text(
            "⚠️ Не удалось обработать изображение.\n"
            "Средства возвращены."
        )
        logger.error(f"Image edit job {job_id} failed: {result.get('error')}")



@router.callback_query(F.data == "image_cancel")
async def cancel_image_operation(callback: CallbackQuery, state: FSMContext):
    """Отмена операции с изображением"""
    await callback.answer()
    await state.clear()
    await callback.message.edit_text("❌ Операция отменена")

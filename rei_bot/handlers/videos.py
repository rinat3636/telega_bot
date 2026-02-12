"""
Обработчики для работы с видео (Kling)
"""
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from database import db
from services.kling import kling_service
from utils.helpers import get_file_for_api
from utils.pricing import get_price, PricingAction
import config


router = Router()


class VideoStates(StatesGroup):
    waiting_for_content_text = State()
    waiting_for_content_image = State()
    waiting_for_content_video = State()


@router.message(F.text == "🎬 Создать видео")
@router.message(F.text == "🎬 Видео")
async def videos_menu(message: Message, state: FSMContext):
    """Главное меню работы с видео"""
    await state.clear()
    
    # Проверка ENABLE_VIDEOS
    if not config.ENABLE_VIDEOS:
        await message.answer("⚠️ Генерация видео временно отключена")
        return
    
    # Проверка бана
    if await db.is_banned(message.from_user.id):
        await message.answer("❌ Вы заблокированы")
        return
    
    text = (
        "🎬 <b>Kling Video</b>\n\n"
        "Выберите, что хотите сделать:"
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 Из текста", callback_data="video_from_text")],
        [InlineKeyboardButton(text="🖼 Из изображения", callback_data="video_from_image")],
        [InlineKeyboardButton(text="🎥 Из видео", callback_data="video_from_video")]
    ])
    
    await message.answer(text, reply_markup=keyboard, parse_mode="HTML")


# === ИЗ ТЕКСТА ===

@router.callback_query(F.data == "video_from_text")
async def video_from_text_choose_model(callback: CallbackQuery, state: FSMContext):
    """Выбор модели для видео из текста"""
    await callback.answer()
    
    text = "🎬 <b>Видео из текста</b>\n\nВыберите модель:"
    
    keyboard_buttons = []
    for model_id, display_name in config.KLING_MODELS.items():
        keyboard_buttons.append([
            InlineKeyboardButton(
                text=display_name,
                callback_data=f"video_model_{model_id}_text"
            )
        ])
    keyboard_buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="video_back_main")])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
    
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")


@router.callback_query(F.data.startswith("video_model_") & F.data.endswith("_text"))
async def video_from_text_choose_duration(callback: CallbackQuery, state: FSMContext):
    """Выбор длительности для видео из текста"""
    await callback.answer()
    
    # Извлекаем model_id
    parts = callback.data.split("_")
    model_id = parts[2]
    
    await state.update_data(model=model_id, mode="text")
    
    # Получить цены из БД с fallback на config
    price_5sec = await get_price(db, provider="kling", action=PricingAction.VIDEO_5SEC)
    price_10sec = await get_price(db, provider="kling", action=PricingAction.VIDEO_10SEC)
    
    text = "⏱ Выберите длительность:"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"▶️ 5 секунд — {price_5sec} ₽",
            callback_data=f"video_duration_5_text_{model_id}"
        )],
        [InlineKeyboardButton(
            text=f"▶️ 10 секунд — {price_10sec} ₽",
            callback_data=f"video_duration_10_text_{model_id}"
        )],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="video_from_text")]
    ])
    
    await callback.message.edit_text(text, reply_markup=keyboard)


@router.callback_query(F.data.startswith("video_duration_") & F.data.contains("_text_"))
async def video_from_text_request_content(callback: CallbackQuery, state: FSMContext):
    """Запрос контента для видео из текста"""
    await callback.answer()
    
    # Извлекаем duration и model
    parts = callback.data.split("_")
    duration = int(parts[2])
    model_id = parts[4]
    
    await state.update_data(duration=duration, model=model_id, mode="text")
    await state.set_state(VideoStates.waiting_for_content_text)
    
    await callback.message.edit_text(
        "📝 Отправьте текстовое описание видео"
    )


@router.message(VideoStates.waiting_for_content_text)
async def video_from_text_show_confirmation(message: Message, state: FSMContext):
    """Показать подтверждение для видео из текста"""
    if await db.is_banned(message.from_user.id):
        await message.answer("❌ Вы заблокированы")
        await state.clear()
        return
    
    data = await state.get_data()
    duration = data.get("duration")
    model_id = data.get("model")
    prompt = message.text
    
    await state.update_data(prompt=prompt)
    
    # Получить цену из БД с fallback на config
    action = PricingAction.VIDEO_5SEC if duration == 5 else PricingAction.VIDEO_10SEC
    price = await get_price(db, provider="kling", action=action)
    balance = await db.get_balance(message.from_user.id)
    
    model_name = config.KLING_MODELS.get(model_id, model_id)
    
    text = (
        f"🎬 <b>Создание видео из текста</b>\n\n"
        f"Модель: {model_name}\n"
        f"Длительность: {duration} сек\n"
        f"Описание: {prompt}\n\n"
        f"💰 Стоимость: <b>{price} ₽</b>\n"
        f"💳 Ваш баланс: <b>{balance} ₽</b>\n\n"
    )
    
    if balance < price:
        text += "❌ Недостаточно средств для выполнения операции"
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="video_cancel")]
        ])
    else:
        text += "Подтвердите запуск:"
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="▶️ Запустить", callback_data="video_confirm_text")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="video_cancel")]
        ])
    
    await message.answer(text, reply_markup=keyboard, parse_mode="HTML")


@router.callback_query(F.data == "video_confirm_text")
async def video_from_text_execute(callback: CallbackQuery, state: FSMContext):
    """Выполнение генерации видео из текста"""
    await callback.answer()
    
    data = await state.get_data()
    duration = data.get("duration")
    model_id = data.get("model")
    prompt = data.get("prompt")
    
    await state.clear()
    
    user_id = callback.from_user.id
    
    # Получить цену из БД с fallback на config
    action = PricingAction.VIDEO_5SEC if duration == 5 else PricingAction.VIDEO_10SEC
    price = await get_price(db, provider="kling", action=action)
    
    # Проверка баланса
    balance = await db.get_balance(user_id)
    if balance < price:
        await callback.message.edit_text(
            f"❌ Недостаточно средств\n"
            f"Требуется: {price} ₽\n"
            f"Ваш баланс: {balance} ₽\n\n"
            f"Пополните баланс: /pay"
        )
        return
    
    # Списание средств
    success = await db.subtract_balance(user_id, price)
    if not success:
        await callback.message.edit_text("⚠️ Ошибка списания средств")
        return
    
    # Создание задачи
    job_id = await db.create_job(
        user_id=user_id,
        job_type="video",
        params={
            "action": "generate",
            "provider": "kling",
            "model": model_id,
            "duration_seconds": duration,
            "prompt": prompt
        },
        cost_estimate=price
    )
    
    # Статус
    await callback.message.edit_text(
        "🎬 <b>Создание видео…</b>\n"
        "⏳ Обычно занимает 1–3 минуты",
        parse_mode="HTML"
    )
    
    await db.update_job_status(job_id, "processing")
    
    # Вызов API
    result = await kling_service.generate_video_from_text(prompt, duration, model_id)
    
    if result["success"]:
        await db.update_job_status(job_id, "completed", result_url=result["video_url"])
        
        try:
            await callback.message.answer_video(
                video=result["video_url"],
                caption="✅ Видео готово"
            )
            await callback.message.delete()
        except Exception as e:
            await callback.message.edit_text(
                f"✅ Видео готово\n\n"
                f"Ссылка: {result['video_url']}"
            )
    else:
        await db.update_job_status(job_id, "failed", error_message=result.get("error", "Unknown error"))
        await db.add_balance(user_id, price)
        await callback.message.edit_text(
            "⚠️ Не удалось создать видео.\n"
            "Средства не списаны."
        )


# === ИЗ ИЗОБРАЖЕНИЯ ===

@router.callback_query(F.data == "video_from_image")
async def video_from_image_choose_model(callback: CallbackQuery, state: FSMContext):
    """Выбор модели для видео из изображения"""
    await callback.answer()
    
    text = "🎬 <b>Видео из изображения</b>\n\nВыберите модель:"
    
    keyboard_buttons = []
    for model_id, display_name in config.KLING_MODELS.items():
        keyboard_buttons.append([
            InlineKeyboardButton(
                text=display_name,
                callback_data=f"video_model_{model_id}_image"
            )
        ])
    keyboard_buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="video_back_main")])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
    
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")


@router.callback_query(F.data.startswith("video_model_") & F.data.endswith("_image"))
async def video_from_image_choose_duration(callback: CallbackQuery, state: FSMContext):
    """Выбор длительности для видео из изображения"""
    await callback.answer()
    
    parts = callback.data.split("_")
    model_id = parts[2]
    
    await state.update_data(model=model_id, mode="image")
    
    # Получить цены из БД с fallback на config
    price_5sec = await get_price(db, provider="kling", action=PricingAction.VIDEO_5SEC)
    price_10sec = await get_price(db, provider="kling", action=PricingAction.VIDEO_10SEC)
    
    text = "⏱ Выберите длительность:"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"▶️ 5 секунд — {price_5sec} ₽",
            callback_data=f"video_duration_5_image_{model_id}"
        )],
        [InlineKeyboardButton(
            text=f"▶️ 10 секунд — {price_10sec} ₽",
            callback_data=f"video_duration_10_image_{model_id}"
        )],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="video_from_image")]
    ])
    
    await callback.message.edit_text(text, reply_markup=keyboard)


@router.callback_query(F.data.startswith("video_duration_") & F.data.contains("_image_"))
async def video_from_image_request_content(callback: CallbackQuery, state: FSMContext):
    """Запрос контента для видео из изображения"""
    await callback.answer()
    
    parts = callback.data.split("_")
    duration = int(parts[2])
    model_id = parts[4]
    
    await state.update_data(duration=duration, model=model_id, mode="image")
    await state.set_state(VideoStates.waiting_for_content_image)
    
    await callback.message.edit_text(
        "🖼 Отправьте изображение и описание (подпись к фото)"
    )


@router.message(VideoStates.waiting_for_content_image, F.photo)
async def video_from_image_show_confirmation(message: Message, state: FSMContext):
    """Показать подтверждение для видео из изображения"""
    if await db.is_banned(message.from_user.id):
        await message.answer("❌ Вы заблокированы")
        await state.clear()
        return
    
    if not message.caption:
        await message.answer("⚠️ Добавьте описание к изображению")
        return
    
    data = await state.get_data()
    duration = data.get("duration")
    model_id = data.get("model")
    prompt = message.caption
    photo_file_id = message.photo[-1].file_id
    
    await state.update_data(prompt=prompt, photo_file_id=photo_file_id)
    
    # Получить цену из БД с fallback на config
    action = PricingAction.VIDEO_5SEC if duration == 5 else PricingAction.VIDEO_10SEC
    price = await get_price(db, provider="kling", action=action)
    balance = await db.get_balance(message.from_user.id)
    
    model_name = config.KLING_MODELS.get(model_id, model_id)
    
    text = (
        f"🎬 <b>Создание видео из изображения</b>\n\n"
        f"Модель: {model_name}\n"
        f"Длительность: {duration} сек\n"
        f"Описание: {prompt}\n\n"
        f"💰 Стоимость: <b>{price} ₽</b>\n"
        f"💳 Ваш баланс: <b>{balance} ₽</b>\n\n"
    )
    
    if balance < price:
        text += "❌ Недостаточно средств для выполнения операции"
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="video_cancel")]
        ])
    else:
        text += "Подтвердите запуск:"
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="▶️ Запустить", callback_data="video_confirm_image")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="video_cancel")]
        ])
    
    await message.answer(text, reply_markup=keyboard, parse_mode="HTML")


@router.callback_query(F.data == "video_confirm_image")
async def video_from_image_execute(callback: CallbackQuery, state: FSMContext):
    """Выполнение генерации видео из изображения"""
    await callback.answer()
    
    data = await state.get_data()
    duration = data.get("duration")
    model_id = data.get("model")
    prompt = data.get("prompt")
    photo_file_id = data.get("photo_file_id")
    
    await state.clear()
    
    user_id = callback.from_user.id
    
    # Получить цену из БД с fallback на config
    action = PricingAction.VIDEO_5SEC if duration == 5 else PricingAction.VIDEO_10SEC
    price = await get_price(db, provider="kling", action=action)
    
    balance = await db.get_balance(user_id)
    if balance < price:
        await callback.message.edit_text(
            f"❌ Недостаточно средств\n"
            f"Требуется: {price} ₽\n"
            f"Ваш баланс: {balance} ₽\n\n"
            f"Пополните баланс: /pay"
        )
        return
    
    success = await db.subtract_balance(user_id, price)
    if not success:
        await callback.message.edit_text("⚠️ Ошибка списания средств")
        return
    
    job_id = await db.create_job(
        user_id=user_id,
        job_type="video",
        params={
            "action": "generate",
            "provider": "kling",
            "model": model_id,
            "duration_seconds": duration,
            "prompt": prompt
        },
        cost_estimate=price
    )
    
    await callback.message.edit_text(
        "🎬 <b>Создание видео…</b>\n"
        "⏳ Обычно занимает 1–3 минуты",
        parse_mode="HTML"
    )
    
    await db.update_job_status(job_id, "processing")
    
    try:
        image_data = await get_file_for_api(callback.bot, photo_file_id, "image.jpg")
    except Exception as e:
        await db.update_job_status(job_id, "failed", error_message=str(e))
        await db.add_balance(user_id, price)
        await callback.message.edit_text(
            "⚠️ Не удалось создать видео.\n"
            "Средства не списаны."
        )
        return
    
    result = await kling_service.generate_video_from_image(image_data, prompt, duration, model_id)
    
    if result["success"]:
        await db.update_job_status(job_id, "completed", result_url=result["video_url"])
        
        try:
            await callback.message.answer_video(
                video=result["video_url"],
                caption="✅ Видео готово"
            )
            await callback.message.delete()
        except Exception as e:
            await callback.message.edit_text(
                f"✅ Видео готово\n\n"
                f"Ссылка: {result['video_url']}"
            )
    else:
        await db.update_job_status(job_id, "failed", error_message=result.get("error", "Unknown error"))
        await db.add_balance(user_id, price)
        await callback.message.edit_text(
            "⚠️ Не удалось создать видео.\n"
            "Средства не списаны."
        )


# === ИЗ ВИДЕО ===

@router.callback_query(F.data == "video_from_video")
async def video_from_video_choose_model(callback: CallbackQuery, state: FSMContext):
    """Выбор модели для видео из видео"""
    await callback.answer()
    
    text = "🎬 <b>Видео из видео</b>\n\nВыберите модель:"
    
    keyboard_buttons = []
    for model_id, display_name in config.KLING_MODELS.items():
        keyboard_buttons.append([
            InlineKeyboardButton(
                text=display_name,
                callback_data=f"video_model_{model_id}_video"
            )
        ])
    keyboard_buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="video_back_main")])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
    
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")


@router.callback_query(F.data.startswith("video_model_") & F.data.endswith("_video"))
async def video_from_video_choose_duration(callback: CallbackQuery, state: FSMContext):
    """Выбор длительности для видео из видео"""
    await callback.answer()
    
    parts = callback.data.split("_")
    model_id = parts[2]
    
    await state.update_data(model=model_id, mode="video")
    
    # Получить цены из БД с fallback на config
    price_5sec = await get_price(db, provider="kling", action=PricingAction.VIDEO_5SEC)
    price_10sec = await get_price(db, provider="kling", action=PricingAction.VIDEO_10SEC)
    
    text = "⏱ Выберите длительность:"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"▶️ 5 секунд — {price_5sec} ₽",
            callback_data=f"video_duration_5_video_{model_id}"
        )],
        [InlineKeyboardButton(
            text=f"▶️ 10 секунд — {price_10sec} ₽",
            callback_data=f"video_duration_10_video_{model_id}"
        )],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="video_from_video")]
    ])
    
    await callback.message.edit_text(text, reply_markup=keyboard)


@router.callback_query(F.data.startswith("video_duration_") & F.data.contains("_video_"))
async def video_from_video_request_content(callback: CallbackQuery, state: FSMContext):
    """Запрос контента для видео из видео"""
    await callback.answer()
    
    parts = callback.data.split("_")
    duration = int(parts[2])
    model_id = parts[4]
    
    await state.update_data(duration=duration, model=model_id, mode="video")
    await state.set_state(VideoStates.waiting_for_content_video)
    
    await callback.message.edit_text(
        "🎥 Отправьте видео и описание (подпись к видео)"
    )


@router.message(VideoStates.waiting_for_content_video, F.video)
async def video_from_video_show_confirmation(message: Message, state: FSMContext):
    """Показать подтверждение для видео из видео"""
    if await db.is_banned(message.from_user.id):
        await message.answer("❌ Вы заблокированы")
        await state.clear()
        return
    
    if not message.caption:
        await message.answer("⚠️ Добавьте описание к видео")
        return
    
    data = await state.get_data()
    duration = data.get("duration")
    model_id = data.get("model")
    prompt = message.caption
    video_file_id = message.video.file_id
    
    await state.update_data(prompt=prompt, video_file_id=video_file_id)
    
    # Получить цену из БД с fallback на config
    action = PricingAction.VIDEO_5SEC if duration == 5 else PricingAction.VIDEO_10SEC
    price = await get_price(db, provider="kling", action=action)
    balance = await db.get_balance(message.from_user.id)
    
    model_name = config.KLING_MODELS.get(model_id, model_id)
    
    text = (
        f"🎬 <b>Создание видео из видео</b>\n\n"
        f"Модель: {model_name}\n"
        f"Длительность: {duration} сек\n"
        f"Описание: {prompt}\n\n"
        f"💰 Стоимость: <b>{price} ₽</b>\n"
        f"💳 Ваш баланс: <b>{balance} ₽</b>\n\n"
    )
    
    if balance < price:
        text += "❌ Недостаточно средств для выполнения операции"
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="video_cancel")]
        ])
    else:
        text += "Подтвердите запуск:"
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="▶️ Запустить", callback_data="video_confirm_video")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="video_cancel")]
        ])
    
    await message.answer(text, reply_markup=keyboard, parse_mode="HTML")


@router.callback_query(F.data == "video_confirm_video")
async def video_from_video_execute(callback: CallbackQuery, state: FSMContext):
    """Выполнение генерации видео из видео"""
    await callback.answer()
    
    data = await state.get_data()
    duration = data.get("duration")
    model_id = data.get("model")
    prompt = data.get("prompt")
    video_file_id = data.get("video_file_id")
    
    await state.clear()
    
    user_id = callback.from_user.id
    
    # Получить цену из БД с fallback на config
    action = PricingAction.VIDEO_5SEC if duration == 5 else PricingAction.VIDEO_10SEC
    price = await get_price(db, provider="kling", action=action)
    
    balance = await db.get_balance(user_id)
    if balance < price:
        await callback.message.edit_text(
            f"❌ Недостаточно средств\n"
            f"Требуется: {price} ₽\n"
            f"Ваш баланс: {balance} ₽\n\n"
            f"Пополните баланс: /pay"
        )
        return
    
    success = await db.subtract_balance(user_id, price)
    if not success:
        await callback.message.edit_text("⚠️ Ошибка списания средств")
        return
    
    job_id = await db.create_job(
        user_id=user_id,
        job_type="video",
        params={
            "action": "generate",
            "provider": "kling",
            "model": model_id,
            "duration_seconds": duration,
            "prompt": prompt
        },
        cost_estimate=price
    )
    
    await callback.message.edit_text(
        "🎬 <b>Создание видео…</b>\n"
        "⏳ Обычно занимает 1–3 минуты",
        parse_mode="HTML"
    )
    
    await db.update_job_status(job_id, "processing")
    
    try:
        video_data = await get_file_for_api(callback.bot, video_file_id, "video.mp4")
    except Exception as e:
        await db.update_job_status(job_id, "failed", error_message=str(e))
        await db.add_balance(user_id, price)
        await callback.message.edit_text(
            "⚠️ Не удалось создать видео.\n"
            "Средства не списаны."
        )
        return
    
    result = await kling_service.generate_video_from_video(video_data, prompt, duration, model_id)
    
    if result["success"]:
        await db.update_job_status(job_id, "completed", result_url=result["video_url"])
        
        try:
            await callback.message.answer_video(
                video=result["video_url"],
                caption="✅ Видео готово"
            )
            await callback.message.delete()
        except Exception as e:
            await callback.message.edit_text(
                f"✅ Видео готово\n\n"
                f"Ссылка: {result['video_url']}"
            )
    else:
        await db.update_job_status(job_id, "failed", error_message=result.get("error", "Unknown error"))
        await db.add_balance(user_id, price)
        await callback.message.edit_text(
            "⚠️ Не удалось создать видео.\n"
            "Средства не списаны."
        )


# === ОБЩИЕ ОБРАБОТЧИКИ ===

@router.callback_query(F.data == "video_cancel")
async def cancel_video_operation(callback: CallbackQuery, state: FSMContext):
    """Отмена операции с видео"""
    await callback.answer()
    await state.clear()
    await callback.message.edit_text("❌ Операция отменена")


@router.callback_query(F.data == "video_back_main")
async def back_to_video_main(callback: CallbackQuery, state: FSMContext):
    """Возврат в главное меню видео"""
    await callback.answer()
    await state.clear()
    
    text = (
        "🎬 <b>Kling Video</b>\n\n"
        "Выберите, что хотите сделать:"
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 Из текста", callback_data="video_from_text")],
        [InlineKeyboardButton(text="🖼 Из изображения", callback_data="video_from_image")],
        [InlineKeyboardButton(text="🎥 Из видео", callback_data="video_from_video")]
    ])
    
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")

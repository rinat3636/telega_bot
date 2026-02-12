@router.callback_query(F.data == "image_edit_confirm")
async def confirm_image_edit(callback: CallbackQuery, state: FSMContext):
    """Подтверждение редактирования изображения"""
    await callback.answer()
    
    data = await state.get_data()
    prompt = data.get("prompt")
    photo_file_id = data.get("photo_file_id")
    
    await state.clear()
    
    user_id = callback.from_user.id
    
    # Резервирование средств (атомарно)
    reserve_ref_id = f"image_edit_{user_id}_{callback.message.message_id}"
    reserved = await db.reserve_balance(
        user_id=user_id,
        amount=config.IMAGE_EDIT_PRICE,
        ref_id=reserve_ref_id
    )
    
    if not reserved:
        balance = await db.get_balance(user_id)
        await callback.message.edit_text(
            f"❌ Недостаточно средств\n"
            f"Требуется: {config.IMAGE_EDIT_PRICE} ₽\n"
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
        cost_estimate=config.IMAGE_EDIT_PRICE
    )
    
    logger.info(f"User {user_id} started image edit, reserved {config.IMAGE_EDIT_PRICE} ₽, job_id={job_id}")
    
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
        await db.charge_reserved_balance(
            user_id=user_id,
            reserve_ref_id=reserve_ref_id,
            actual_amount=config.IMAGE_EDIT_PRICE,
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

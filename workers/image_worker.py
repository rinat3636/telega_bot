"""
Worker для обработки задач с изображениями
"""
import asyncio
import sys
import os

# Добавить корневую директорию в путь
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.models import db
from services.nano_banana import NanoBananaService
import config


async def generate_image(job_id: int, user_id: int, prompt: str):
    """
    Worker для генерации изображения
    
    Args:
        job_id: ID задачи в БД
        user_id: ID пользователя
        prompt: Текстовое описание
    """
    nano_service = NanoBananaService()
    
    try:
        # Обновить статус на "processing"
        await db.update_job_status(job_id, 'processing', progress=10)
        
        # Генерация изображения
        result = await nano_service.generate_image(prompt)
        
        if result.get('success'):
            # Сохранить результат
            image_url = result.get('image_url')
            await db.update_job_status(
                job_id,
                'completed',
                progress=100,
                result_url=image_url,
                cost_actual=config.IMAGE_GENERATION_PRICE
            )
            
            # Отправить результат пользователю
            await notify_user(user_id, job_id, image_url)
        else:
            # Ошибка генерации
            error_msg = result.get('error', 'Неизвестная ошибка')
            await db.update_job_status(
                job_id,
                'failed',
                error_message=error_msg
            )
            
            # Вернуть деньги
            await db.refund_balance(
                user_id,
                config.IMAGE_GENERATION_PRICE,
                'job',
                str(job_id),
                f'Возврат за неудачную генерацию изображения (job #{job_id})'
            )
            
            # Уведомить пользователя об ошибке
            await notify_user_error(user_id, job_id, error_msg)
    
    except Exception as e:
        # Критическая ошибка
        await db.update_job_status(
            job_id,
            'failed',
            error_message=str(e)
        )
        
        # Вернуть деньги
        await db.refund_balance(
            user_id,
            config.IMAGE_GENERATION_PRICE,
            'job',
            str(job_id),
            f'Возврат за ошибку генерации изображения (job #{job_id})'
        )
        
        await notify_user_error(user_id, job_id, str(e))


async def edit_image(job_id: int, user_id: int, image_path: str, prompt: str):
    """
    Worker для редактирования изображения
    
    Args:
        job_id: ID задачи в БД
        user_id: ID пользователя
        image_path: Путь к изображению
        prompt: Описание изменений
    """
    nano_service = NanoBananaService()
    
    try:
        # Обновить статус на "processing"
        await db.update_job_status(job_id, 'processing', progress=10)
        
        # Редактирование изображения
        result = await nano_service.edit_image(image_path, prompt)
        
        if result.get('success'):
            # Сохранить результат
            image_url = result.get('image_url')
            await db.update_job_status(
                job_id,
                'completed',
                progress=100,
                result_url=image_url,
                cost_actual=config.IMAGE_EDIT_PRICE
            )
            
            # Отправить результат пользователю
            await notify_user(user_id, job_id, image_url)
        else:
            # Ошибка редактирования
            error_msg = result.get('error', 'Неизвестная ошибка')
            await db.update_job_status(
                job_id,
                'failed',
                error_message=error_msg
            )
            
            # Вернуть деньги
            await db.refund_balance(
                user_id,
                config.IMAGE_EDIT_PRICE,
                'job',
                str(job_id),
                f'Возврат за неудачное редактирование изображения (job #{job_id})'
            )
            
            # Уведомить пользователя об ошибке
            await notify_user_error(user_id, job_id, error_msg)
    
    except Exception as e:
        # Критическая ошибка
        await db.update_job_status(
            job_id,
            'failed',
            error_message=str(e)
        )
        
        # Вернуть деньги
        await db.refund_balance(
            user_id,
            config.IMAGE_EDIT_PRICE,
            'job',
            str(job_id),
            f'Возврат за ошибку редактирования изображения (job #{job_id})'
        )
        
        await notify_user_error(user_id, job_id, str(e))


async def notify_user(user_id: int, job_id: int, image_url: str):
    """Отправить результат пользователю"""
    # TODO: Реализовать отправку через бота
    # Можно использовать aiogram Bot.send_photo()
    print(f"✅ Задача #{job_id} завершена для пользователя {user_id}")
    print(f"📷 Результат: {image_url}")


async def notify_user_error(user_id: int, job_id: int, error: str):
    """Уведомить пользователя об ошибке"""
    # TODO: Реализовать отправку через бота
    print(f"❌ Задача #{job_id} завершилась с ошибкой для пользователя {user_id}")
    print(f"⚠️ Ошибка: {error}")


# Для запуска worker через RQ
def run_generate_image(job_id: int, user_id: int, prompt: str):
    """Обертка для синхронного запуска"""
    asyncio.run(generate_image(job_id, user_id, prompt))


def run_edit_image(job_id: int, user_id: int, image_path: str, prompt: str):
    """Обертка для синхронного запуска"""
    asyncio.run(edit_image(job_id, user_id, image_path, prompt))

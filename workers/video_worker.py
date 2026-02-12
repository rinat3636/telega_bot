"""
Worker для обработки задач с видео
"""
import asyncio
import sys
import os

# Добавить корневую директорию в путь
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.models import db
from services.kling import KlingService
from services.pricing import video_price
import config


async def generate_video(
    job_id: int,
    user_id: int,
    mode: str,
    model: str,
    duration: int,
    content: str
):
    """
    Worker для генерации видео
    
    Args:
        job_id: ID задачи в БД
        user_id: ID пользователя
        mode: Режим ('text', 'image', 'video')
        model: Модель Kling
        duration: Длительность (5 или 10 сек)
        content: Контент (текст, путь к файлу)
    """
    kling_service = KlingService()
    cost = video_price(duration)
    
    try:
        # Обновить статус на "processing"
        await db.update_job_status(job_id, 'processing', progress=10)
        
        # Генерация видео
        if mode == 'text':
            result = await kling_service.generate_video_from_text(content, model, duration)
        elif mode == 'image':
            result = await kling_service.generate_video_from_image(content, model, duration)
        elif mode == 'video':
            result = await kling_service.generate_video_from_video(content, model, duration)
        else:
            raise ValueError(f"Неизвестный режим: {mode}")
        
        if result.get('success'):
            # Сохранить результат
            video_url = result.get('video_url')
            await db.update_job_status(
                job_id,
                'completed',
                progress=100,
                result_url=video_url,
                cost_actual=cost
            )
            
            # Отправить результат пользователю
            await notify_user(user_id, job_id, video_url)
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
                cost,
                'job',
                str(job_id),
                f'Возврат за неудачную генерацию видео (job #{job_id})'
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
            cost,
            'job',
            str(job_id),
            f'Возврат за ошибку генерации видео (job #{job_id})'
        )
        
        await notify_user_error(user_id, job_id, str(e))


async def notify_user(user_id: int, job_id: int, video_url: str):
    """Отправить результат пользователю"""
    # TODO: Реализовать отправку через бота
    print(f"✅ Задача #{job_id} завершена для пользователя {user_id}")
    print(f"🎬 Результат: {video_url}")


async def notify_user_error(user_id: int, job_id: int, error: str):
    """Уведомить пользователя об ошибке"""
    # TODO: Реализовать отправку через бота
    print(f"❌ Задача #{job_id} завершилась с ошибкой для пользователя {user_id}")
    print(f"⚠️ Ошибка: {error}")


# Для запуска worker через RQ
def run_generate_video(
    job_id: int,
    user_id: int,
    mode: str,
    model: str,
    duration: int,
    content: str
):
    """Обертка для синхронного запуска"""
    asyncio.run(generate_video(job_id, user_id, mode, model, duration, content))

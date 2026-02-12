"""
Вспомогательные функции
"""
import os
import io
import logging
from aiogram import Bot
from typing import Union
import config

logger = logging.getLogger(__name__)


async def download_photo(bot: Bot, file_id: str) -> bytes:
    """
    Скачать фото и вернуть bytes
    
    Args:
        bot: Aiogram Bot instance
        file_id: Telegram file_id
    
    Returns:
        bytes: Содержимое файла
    
    Raises:
        Exception: Если не удалось скачать файл
    """
    try:
        # Получаем информацию о файле
        file = await bot.get_file(file_id)
        file_path = file.file_path
        
        # Скачиваем файл в BytesIO
        file_io = io.BytesIO()
        await bot.download_file(file_path, file_io)
        
        # Возвращаем bytes
        return file_io.getvalue()
    
    except Exception as e:
        logger.error(f"Failed to download photo {file_id}: {e}")
        raise


async def download_video(bot: Bot, file_id: str) -> bytes:
    """
    Скачать видео и вернуть bytes
    
    Args:
        bot: Aiogram Bot instance
        file_id: Telegram file_id
    
    Returns:
        bytes: Содержимое файла
    
    Raises:
        Exception: Если не удалось скачать файл
    """
    try:
        # Получаем информацию о файле
        file = await bot.get_file(file_id)
        file_path = file.file_path
        
        # Скачиваем файл в BytesIO
        file_io = io.BytesIO()
        await bot.download_file(file_path, file_io)
        
        # Возвращаем bytes
        return file_io.getvalue()
    
    except Exception as e:
        logger.error(f"Failed to download video {file_id}: {e}")
        raise


async def upload_to_s3(file_data: bytes, filename: str) -> str:
    """
    Загрузить файл в S3 и вернуть pre-signed URL
    
    Args:
        file_data: Содержимое файла (bytes)
        filename: Имя файла
    
    Returns:
        str: Pre-signed URL (временный публичный URL)
    
    Raises:
        Exception: Если не удалось загрузить файл
    """
    if not config.S3_BUCKET:
        raise ValueError("S3_BUCKET not configured")
    
    try:
        # Lazy import boto3
        try:
            import boto3
            from datetime import datetime
        except ImportError:
            raise RuntimeError(
                "boto3 is required for S3 uploads. "
                "Install it with: pip install boto3"
            )
        
        # Создаем S3 клиент
        s3_client = boto3.client(
            's3',
            region_name=config.S3_REGION,
            aws_access_key_id=config.S3_ACCESS_KEY,
            aws_secret_access_key=config.S3_SECRET_KEY
        )
        
        # Генерируем уникальное имя файла
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        s3_key = f"uploads/{timestamp}_{filename}"
        
        # Загружаем файл
        s3_client.put_object(
            Bucket=config.S3_BUCKET,
            Key=s3_key,
            Body=file_data,
            ContentType=_get_content_type(filename)
        )
        
        # Генерируем pre-signed URL
        presigned_url = s3_client.generate_presigned_url(
            'get_object',
            Params={
                'Bucket': config.S3_BUCKET,
                'Key': s3_key
            },
            ExpiresIn=config.S3_PRESIGNED_URL_EXPIRY
        )
        
        logger.info(f"Uploaded {filename} to S3: {s3_key}")
        return presigned_url
    
    except Exception as e:
        logger.error(f"Failed to upload {filename} to S3: {e}")
        raise


def _get_content_type(filename: str) -> str:
    """
    Определить Content-Type по расширению файла
    
    Args:
        filename: Имя файла
    
    Returns:
        str: Content-Type
    """
    ext = os.path.splitext(filename)[1].lower()
    
    content_types = {
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.png': 'image/png',
        '.gif': 'image/gif',
        '.webp': 'image/webp',
        '.mp4': 'video/mp4',
        '.mov': 'video/quicktime',
        '.avi': 'video/x-msvideo',
        '.webm': 'video/webm'
    }
    
    return content_types.get(ext, 'application/octet-stream')


async def get_file_for_api(bot: Bot, file_id: str, filename: str = "file") -> Union[bytes, str]:
    """
    Получить файл для передачи в API (bytes или S3 URL)
    
    Args:
        bot: Aiogram Bot instance
        file_id: Telegram file_id
        filename: Имя файла (для S3)
    
    Returns:
        Union[bytes, str]: bytes (если FILE_UPLOAD_METHOD=multipart) или S3 URL (если FILE_UPLOAD_METHOD=s3)
    
    Raises:
        Exception: Если не удалось получить файл
    """
    # Скачиваем файл
    if filename.endswith(('.mp4', '.mov', '.avi', '.webm')):
        file_data = await download_video(bot, file_id)
    else:
        file_data = await download_photo(bot, file_id)
    
    # Выбираем метод передачи
    if config.FILE_UPLOAD_METHOD == "s3":
        # Загружаем в S3 и возвращаем URL
        return await upload_to_s3(file_data, filename)
    else:
        # Возвращаем bytes для multipart
        return file_data

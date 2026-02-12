"""
Базовый интерфейс для AI провайдеров
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
import logging


logger = logging.getLogger(__name__)


class BaseAIProvider(ABC):
    """Базовый класс для всех AI провайдеров"""
    
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.provider_name = self.__class__.__name__
    
    @abstractmethod
    async def generate(self, **kwargs) -> Dict[str, Any]:
        """
        Основной метод генерации
        
        Returns:
            {
                'success': bool,
                'result_url': str,  # URL результата
                'error': str,  # Сообщение об ошибке (если success=False)
                'metadata': dict  # Дополнительные данные
            }
        """
        pass
    
    async def generate_with_retry(
        self,
        max_retries: int = 3,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Генерация с повторными попытками
        
        Args:
            max_retries: Максимальное количество попыток
            **kwargs: Параметры для generate()
        
        Returns:
            Результат generate()
        """
        last_error = None
        
        for attempt in range(max_retries):
            try:
                logger.info(f"{self.provider_name}: Попытка {attempt + 1}/{max_retries}")
                result = await self.generate(**kwargs)
                
                if result.get('success'):
                    return result
                
                last_error = result.get('error', 'Unknown error')
                logger.warning(f"{self.provider_name}: Попытка {attempt + 1} неудачна: {last_error}")
                
            except Exception as e:
                last_error = str(e)
                logger.error(f"{self.provider_name}: Ошибка на попытке {attempt + 1}: {e}", exc_info=True)
        
        return {
            'success': False,
            'error': f'Не удалось выполнить после {max_retries} попыток. Последняя ошибка: {last_error}'
        }
    
    def _handle_error(self, error: Exception) -> Dict[str, Any]:
        """Обработка ошибок"""
        logger.error(f"{self.provider_name}: {error}", exc_info=True)
        return {
            'success': False,
            'error': str(error)
        }


class ImageProvider(BaseAIProvider):
    """Базовый класс для провайдеров изображений"""
    
    @abstractmethod
    async def generate_image(self, prompt: str, **kwargs) -> Dict[str, Any]:
        """Генерация изображения по текстовому описанию"""
        pass
    
    @abstractmethod
    async def edit_image(self, image_path: str, prompt: str, **kwargs) -> Dict[str, Any]:
        """Редактирование изображения"""
        pass


class VideoProvider(BaseAIProvider):
    """Базовый класс для провайдеров видео"""
    
    @abstractmethod
    async def generate_video_from_text(
        self,
        prompt: str,
        model: str,
        duration: int,
        **kwargs
    ) -> Dict[str, Any]:
        """Генерация видео из текста"""
        pass
    
    @abstractmethod
    async def generate_video_from_image(
        self,
        image_path: str,
        model: str,
        duration: int,
        **kwargs
    ) -> Dict[str, Any]:
        """Генерация видео из изображения"""
        pass
    
    @abstractmethod
    async def generate_video_from_video(
        self,
        video_path: str,
        model: str,
        duration: int,
        **kwargs
    ) -> Dict[str, Any]:
        """Генерация видео из видео"""
        pass

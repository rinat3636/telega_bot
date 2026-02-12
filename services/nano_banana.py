"""
Сервис для работы с Nano Banana Pro API
"""
import aiohttp
import asyncio
import random
from typing import Optional, Dict, Any, Union
import logging
import config

logger = logging.getLogger(__name__)


class NanoBananaService:
    def __init__(self):
        self.api_key = config.NANO_BANANA_API_KEY
        self.base_url = config.NANO_BANANA_BASE_URL
        self.timeout = config.NANO_BANANA_TIMEOUT
        self.retry_attempts = config.API_RETRY_ATTEMPTS
        self.retry_base_delay = config.API_RETRY_BASE_DELAY
        self.retry_max_delay = config.API_RETRY_MAX_DELAY
    
    async def _make_request_with_retry(
        self,
        method: str,
        url: str,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Выполнить HTTP запрос с retry логикой для 429/5xx
        
        Args:
            method: HTTP метод (GET, POST)
            url: URL для запроса
            **kwargs: Дополнительные параметры для aiohttp
        
        Returns:
            {
                "success": bool,
                "data": dict (если success=True),
                "status": int,
                "error": str (если success=False)
            }
        """
        for attempt in range(self.retry_attempts):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.request(method, url, **kwargs) as response:
                        status = response.status
                        
                        # Успешный ответ
                        if 200 <= status < 300:
                            data = await response.json()
                            return {
                                "success": True,
                                "data": data,
                                "status": status
                            }
                        
                        # Retry на 429 (rate limit) и 5xx (server errors)
                        if status == 429 or 500 <= status < 600:
                            error_text = await response.text()
                            
                            if attempt < self.retry_attempts - 1:
                                # Exponential backoff с джиттером
                                delay = min(
                                    self.retry_base_delay * (2 ** attempt) + random.uniform(0, 1),
                                    self.retry_max_delay
                                )
                                logger.warning(
                                    f"NanoBanana API {status} error, retrying in {delay:.2f}s "
                                    f"(attempt {attempt + 1}/{self.retry_attempts}): {error_text}"
                                )
                                await asyncio.sleep(delay)
                                continue
                            else:
                                return {
                                    "success": False,
                                    "status": status,
                                    "error": f"API error after {self.retry_attempts} attempts: {status} - {error_text}"
                                }
                        
                        # Другие ошибки (4xx кроме 429) - не retry
                        error_text = await response.text()
                        return {
                            "success": False,
                            "status": status,
                            "error": f"API error: {status} - {error_text}"
                        }
            
            except asyncio.TimeoutError:
                if attempt < self.retry_attempts - 1:
                    delay = min(
                        self.retry_base_delay * (2 ** attempt) + random.uniform(0, 1),
                        self.retry_max_delay
                    )
                    logger.warning(f"Timeout, retrying in {delay:.2f}s (attempt {attempt + 1}/{self.retry_attempts})")
                    await asyncio.sleep(delay)
                    continue
                else:
                    return {
                        "success": False,
                        "status": 0,
                        "error": f"Timeout after {self.retry_attempts} attempts"
                    }
            
            except Exception as e:
                if attempt < self.retry_attempts - 1:
                    delay = min(
                        self.retry_base_delay * (2 ** attempt) + random.uniform(0, 1),
                        self.retry_max_delay
                    )
                    logger.warning(f"Exception: {e}, retrying in {delay:.2f}s (attempt {attempt + 1}/{self.retry_attempts})")
                    await asyncio.sleep(delay)
                    continue
                else:
                    return {
                        "success": False,
                        "status": 0,
                        "error": f"Exception after {self.retry_attempts} attempts: {str(e)}"
                    }
        
        return {
            "success": False,
            "status": 0,
            "error": "Unexpected error in retry loop"
        }
    
    async def generate_image(self, prompt: str) -> Dict[str, Any]:
        """
        Генерация изображения по текстовому описанию
        
        Args:
            prompt: Текстовое описание
        
        Returns:
            {
                "success": bool,
                "image_url": str (если success=True),
                "error": str (если success=False)
            }
        """
        url = f"{self.base_url}{config.NANO_BANANA_ENDPOINT_GENERATE}"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "prompt": prompt,
            "model": "nano-banana-pro"
        }
        
        result = await self._make_request_with_retry(
            "POST",
            url,
            json=payload,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=self.timeout)
        )
        
        if not result["success"]:
            return {
                "success": False,
                "error": result["error"]
            }
        
        data = result["data"]
        image_url = data.get("image_url") or data.get("url") or data.get("result", {}).get("image_url")
        
        if not image_url:
            return {
                "success": False,
                "error": "Image URL not found in response"
            }
        
        return {
            "success": True,
            "image_url": image_url
        }
    
    async def edit_image(self, image_data: Union[str, bytes], prompt: str) -> Dict[str, Any]:
        """
        Редактирование изображения по текстовому описанию
        
        Args:
            image_data: URL изображения (str) или bytes (для multipart)
            prompt: Текстовое описание
        
        Returns:
            {
                "success": bool,
                "image_url": str (если success=True),
                "error": str (если success=False)
            }
        """
        url = f"{self.base_url}{config.NANO_BANANA_ENDPOINT_EDIT}"
        headers = {
            "Authorization": f"Bearer {self.api_key}"
        }
        
        # Если image_data — bytes, используем multipart
        if isinstance(image_data, bytes):
            data = aiohttp.FormData()
            data.add_field('image', image_data, filename='image.jpg', content_type='image/jpeg')
            data.add_field('prompt', prompt)
            data.add_field('model', 'nano-banana-pro')
            
            result = await self._make_request_with_retry(
                "POST",
                url,
                data=data,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=self.timeout)
            )
        else:
            # Если image_data — URL, используем JSON
            headers["Content-Type"] = "application/json"
            payload = {
                "image_url": image_data,
                "prompt": prompt,
                "model": "nano-banana-pro"
            }
            
            result = await self._make_request_with_retry(
                "POST",
                url,
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=self.timeout)
            )
        
        if not result["success"]:
            return {
                "success": False,
                "error": result["error"]
            }
        
        data = result["data"]
        image_url = data.get("image_url") or data.get("url") or data.get("result", {}).get("image_url")
        
        if not image_url:
            return {
                "success": False,
                "error": "Image URL not found in response"
            }
        
        return {
            "success": True,
            "image_url": image_url
        }


# Глобальный экземпляр сервиса
nano_banana_service = NanoBananaService()

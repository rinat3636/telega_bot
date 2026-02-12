"""
Сервис для работы с Kling API
"""
import aiohttp
import asyncio
import random
from typing import Optional, Dict, Any, Union
import logging
import config

logger = logging.getLogger(__name__)


class KlingService:
    def __init__(self):
        self.api_key = config.KLING_API_KEY
        self.base_url = config.KLING_BASE_URL
        self.timeout = config.KLING_TIMEOUT
        self.poll_interval = config.KLING_POLL_INTERVAL
        self.max_poll_attempts = config.KLING_MAX_POLL_ATTEMPTS
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
                                    f"Kling API {status} error, retrying in {delay:.2f}s "
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
    
    async def _poll_task_status(self, task_id: str) -> Dict[str, Any]:
        """
        Опрашивать статус задачи до готовности
        
        Args:
            task_id: ID задачи
        
        Returns:
            {
                "success": bool,
                "video_url": str (если success=True),
                "status": str (queued/running/succeeded/failed),
                "error": str (если success=False)
            }
        """
        url = f"{self.base_url}{config.KLING_ENDPOINT_STATUS}/{task_id}"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        for attempt in range(self.max_poll_attempts):
            result = await self._make_request_with_retry(
                "GET",
                url,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=30)
            )
            
            if not result["success"]:
                return {
                    "success": False,
                    "status": "error",
                    "error": result["error"]
                }
            
            data = result["data"]
            status = data.get("status", "unknown")
            
            if status == "succeeded":
                video_url = data.get("video_url") or data.get("result", {}).get("video_url")
                if video_url:
                    return {
                        "success": True,
                        "video_url": video_url,
                        "status": "succeeded"
                    }
                else:
                    return {
                        "success": False,
                        "status": "succeeded",
                        "error": "Video URL not found in response"
                    }
            
            elif status == "failed":
                error_message = data.get("error") or data.get("message", "Unknown error")
                return {
                    "success": False,
                    "status": "failed",
                    "error": f"Task failed: {error_message}"
                }
            
            elif status in ["queued", "running", "processing"]:
                logger.info(f"Task {task_id} status: {status}, polling again in {self.poll_interval}s...")
                await asyncio.sleep(self.poll_interval)
                continue
            
            else:
                logger.warning(f"Unknown task status: {status}")
                await asyncio.sleep(self.poll_interval)
                continue
        
        return {
            "success": False,
            "status": "timeout",
            "error": f"Task did not complete after {self.max_poll_attempts * self.poll_interval}s"
        }
    
    async def generate_video_from_text(
        self,
        prompt: str,
        duration_seconds: int,
        model: str = "kling-3.0"
    ) -> Dict[str, Any]:
        """
        Генерация видео из текста (job-based протокол)
        
        Args:
            prompt: Текстовое описание
            duration_seconds: Длительность (5 или 10)
            model: Модель Kling
        
        Returns:
            {
                "success": bool,
                "video_url": str (если success=True),
                "error": str (если success=False)
            }
        """
        # Добавляем информацию о длительности в промпт
        if duration_seconds == 5:
            enhanced_prompt = f"Create a short 5-second video. {prompt}"
        else:
            enhanced_prompt = f"Create a 10-second video with more detailed motion. {prompt}"
        
        url = f"{self.base_url}{config.KLING_ENDPOINT_T2V}"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "prompt": enhanced_prompt,
            "duration_seconds": duration_seconds,
            "model": model
        }
        
        # Создать задачу
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
        task_id = data.get("task_id") or data.get("id")
        
        if not task_id:
            return {
                "success": False,
                "error": "Task ID not found in response"
            }
        
        logger.info(f"Text-to-video task created: {task_id}")
        
        # Опрашивать статус
        return await self._poll_task_status(task_id)
    
    async def generate_video_from_image(
        self,
        image_data: Union[str, bytes],
        prompt: str,
        duration_seconds: int,
        model: str = "kling-3.0"
    ) -> Dict[str, Any]:
        """
        Генерация видео из изображения (job-based протокол)
        
        Args:
            image_data: URL изображения (str) или bytes (для multipart)
            prompt: Текстовое описание
            duration_seconds: Длительность (5 или 10)
            model: Модель Kling
        
        Returns:
            {
                "success": bool,
                "video_url": str (если success=True),
                "error": str (если success=False)
            }
        """
        # Добавляем информацию о длительности в промпт
        if duration_seconds == 5:
            enhanced_prompt = f"Create a short 5-second video. {prompt}"
        else:
            enhanced_prompt = f"Create a 10-second video with more detailed motion. {prompt}"
        
        url = f"{self.base_url}{config.KLING_ENDPOINT_I2V}"
        headers = {
            "Authorization": f"Bearer {self.api_key}"
        }
        
        # Если image_data — bytes, используем multipart
        if isinstance(image_data, bytes):
            data = aiohttp.FormData()
            data.add_field('image', image_data, filename='image.jpg', content_type='image/jpeg')
            data.add_field('prompt', enhanced_prompt)
            data.add_field('duration_seconds', str(duration_seconds))
            data.add_field('model', model)
            
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
                "prompt": enhanced_prompt,
                "duration_seconds": duration_seconds,
                "model": model
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
        task_id = data.get("task_id") or data.get("id")
        
        if not task_id:
            return {
                "success": False,
                "error": "Task ID not found in response"
            }
        
        logger.info(f"Image-to-video task created: {task_id}")
        
        # Опрашивать статус
        return await self._poll_task_status(task_id)
    
    async def generate_video_from_video(
        self,
        video_data: Union[str, bytes],
        prompt: str,
        duration_seconds: int,
        model: str = "kling-3.0"
    ) -> Dict[str, Any]:
        """
        Генерация видео из видео (job-based протокол)
        
        Args:
            video_data: URL видео (str) или bytes (для multipart)
            prompt: Текстовое описание
            duration_seconds: Длительность (5 или 10)
            model: Модель Kling
        
        Returns:
            {
                "success": bool,
                "video_url": str (если success=True),
                "error": str (если success=False)
            }
        """
        # Добавляем информацию о длительности в промпт
        if duration_seconds == 5:
            enhanced_prompt = f"Create a short 5-second video. {prompt}"
        else:
            enhanced_prompt = f"Create a 10-second video with more detailed motion. {prompt}"
        
        url = f"{self.base_url}{config.KLING_ENDPOINT_V2V}"
        headers = {
            "Authorization": f"Bearer {self.api_key}"
        }
        
        # Если video_data — bytes, используем multipart
        if isinstance(video_data, bytes):
            data = aiohttp.FormData()
            data.add_field('video', video_data, filename='video.mp4', content_type='video/mp4')
            data.add_field('prompt', enhanced_prompt)
            data.add_field('duration_seconds', str(duration_seconds))
            data.add_field('model', model)
            
            result = await self._make_request_with_retry(
                "POST",
                url,
                data=data,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=self.timeout)
            )
        else:
            # Если video_data — URL, используем JSON
            headers["Content-Type"] = "application/json"
            payload = {
                "video_url": video_data,
                "prompt": enhanced_prompt,
                "duration_seconds": duration_seconds,
                "model": model
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
        task_id = data.get("task_id") or data.get("id")
        
        if not task_id:
            return {
                "success": False,
                "error": "Task ID not found in response"
            }
        
        logger.info(f"Video-to-video task created: {task_id}")
        
        # Опрашивать статус
        return await self._poll_task_status(task_id)


# Глобальный экземпляр сервиса
kling_service = KlingService()

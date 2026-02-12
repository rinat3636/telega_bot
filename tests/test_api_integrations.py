"""
Unit-тесты для API интеграций (NanoBanana и Kling)
"""
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from services.nano_banana import NanoBananaService
from services.kling import KlingService


class TestNanoBananaService:
    """Тесты для NanoBananaService"""
    
    @pytest.mark.asyncio
    async def test_generate_image_success(self):
        """Тест успешной генерации изображения"""
        service = NanoBananaService()
        
        with patch.object(service, '_make_request_with_retry', new_callable=AsyncMock) as mock_request:
            mock_request.return_value = {
                "success": True,
                "data": {"image_url": "https://example.com/image.jpg"},
                "status": 200
            }
            
            result = await service.generate_image("test prompt")
            
            assert result["success"] is True
            assert result["image_url"] == "https://example.com/image.jpg"
            mock_request.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_generate_image_retry_on_429(self):
        """Тест retry при 429 ошибке"""
        service = NanoBananaService()
        service.retry_attempts = 2
        service.retry_base_delay = 0.1
        
        with patch('aiohttp.ClientSession') as mock_session:
            mock_response = AsyncMock()
            mock_response.status = 429
            mock_response.text = AsyncMock(return_value="Rate limit exceeded")
            
            mock_session.return_value.__aenter__.return_value.request.return_value.__aenter__.return_value = mock_response
            
            result = await service._make_request_with_retry("POST", "https://example.com")
            
            assert result["success"] is False
            assert "429" in result["error"] or "Rate limit" in result["error"]
    
    @pytest.mark.asyncio
    async def test_edit_image_with_bytes(self):
        """Тест редактирования изображения с bytes"""
        service = NanoBananaService()
        
        with patch.object(service, '_make_request_with_retry', new_callable=AsyncMock) as mock_request:
            mock_request.return_value = {
                "success": True,
                "data": {"image_url": "https://example.com/edited.jpg"},
                "status": 200
            }
            
            image_bytes = b"fake_image_data"
            result = await service.edit_image(image_bytes, "edit prompt")
            
            assert result["success"] is True
            assert result["image_url"] == "https://example.com/edited.jpg"
    
    @pytest.mark.asyncio
    async def test_edit_image_with_url(self):
        """Тест редактирования изображения с URL"""
        service = NanoBananaService()
        
        with patch.object(service, '_make_request_with_retry', new_callable=AsyncMock) as mock_request:
            mock_request.return_value = {
                "success": True,
                "data": {"image_url": "https://example.com/edited.jpg"},
                "status": 200
            }
            
            result = await service.edit_image("https://example.com/original.jpg", "edit prompt")
            
            assert result["success"] is True
            assert result["image_url"] == "https://example.com/edited.jpg"


class TestKlingService:
    """Тесты для KlingService"""
    
    @pytest.mark.asyncio
    async def test_generate_video_from_text_success(self):
        """Тест успешной генерации видео из текста"""
        service = KlingService()
        service.max_poll_attempts = 2
        service.poll_interval = 0.1
        
        with patch.object(service, '_make_request_with_retry', new_callable=AsyncMock) as mock_request:
            # Первый вызов — создание задачи
            mock_request.return_value = {
                "success": True,
                "data": {"task_id": "test_task_123"},
                "status": 200
            }
            
            with patch.object(service, '_poll_task_status', new_callable=AsyncMock) as mock_poll:
                mock_poll.return_value = {
                    "success": True,
                    "video_url": "https://example.com/video.mp4",
                    "status": "succeeded"
                }
                
                result = await service.generate_video_from_text("test prompt", 5, "kling-3.0")
                
                assert result["success"] is True
                assert result["video_url"] == "https://example.com/video.mp4"
                mock_poll.assert_called_once_with("test_task_123")
    
    @pytest.mark.asyncio
    async def test_poll_task_status_queued_then_succeeded(self):
        """Тест polling задачи: queued → succeeded"""
        service = KlingService()
        service.max_poll_attempts = 3
        service.poll_interval = 0.1
        
        with patch.object(service, '_make_request_with_retry', new_callable=AsyncMock) as mock_request:
            # Первый вызов — queued
            # Второй вызов — succeeded
            mock_request.side_effect = [
                {
                    "success": True,
                    "data": {"status": "queued"},
                    "status": 200
                },
                {
                    "success": True,
                    "data": {"status": "succeeded", "video_url": "https://example.com/video.mp4"},
                    "status": 200
                }
            ]
            
            result = await service._poll_task_status("test_task_123")
            
            assert result["success"] is True
            assert result["video_url"] == "https://example.com/video.mp4"
            assert mock_request.call_count == 2
    
    @pytest.mark.asyncio
    async def test_poll_task_status_failed(self):
        """Тест polling задачи: failed"""
        service = KlingService()
        
        with patch.object(service, '_make_request_with_retry', new_callable=AsyncMock) as mock_request:
            mock_request.return_value = {
                "success": True,
                "data": {"status": "failed", "error": "Processing error"},
                "status": 200
            }
            
            result = await service._poll_task_status("test_task_123")
            
            assert result["success"] is False
            assert "failed" in result["error"].lower()
    
    @pytest.mark.asyncio
    async def test_poll_task_status_timeout(self):
        """Тест polling задачи: timeout"""
        service = KlingService()
        service.max_poll_attempts = 2
        service.poll_interval = 0.1
        
        with patch.object(service, '_make_request_with_retry', new_callable=AsyncMock) as mock_request:
            # Всегда возвращаем queued
            mock_request.return_value = {
                "success": True,
                "data": {"status": "queued"},
                "status": 200
            }
            
            result = await service._poll_task_status("test_task_123")
            
            assert result["success"] is False
            assert "timeout" in result["error"].lower()
    
    @pytest.mark.asyncio
    async def test_generate_video_from_image_with_bytes(self):
        """Тест генерации видео из изображения (bytes)"""
        service = KlingService()
        
        with patch.object(service, '_make_request_with_retry', new_callable=AsyncMock) as mock_request:
            mock_request.return_value = {
                "success": True,
                "data": {"task_id": "test_task_123"},
                "status": 200
            }
            
            with patch.object(service, '_poll_task_status', new_callable=AsyncMock) as mock_poll:
                mock_poll.return_value = {
                    "success": True,
                    "video_url": "https://example.com/video.mp4",
                    "status": "succeeded"
                }
                
                image_bytes = b"fake_image_data"
                result = await service.generate_video_from_image(image_bytes, "test prompt", 10, "kling-3.0")
                
                assert result["success"] is True
                assert result["video_url"] == "https://example.com/video.mp4"
    
    @pytest.mark.asyncio
    async def test_retry_with_exponential_backoff(self):
        """Тест exponential backoff с джиттером"""
        service = KlingService()
        service.retry_attempts = 3
        service.retry_base_delay = 0.1
        service.retry_max_delay = 1.0
        
        with patch('aiohttp.ClientSession') as mock_session:
            mock_response = AsyncMock()
            mock_response.status = 500
            mock_response.text = AsyncMock(return_value="Internal server error")
            
            mock_session.return_value.__aenter__.return_value.request.return_value.__aenter__.return_value = mock_response
            
            result = await service._make_request_with_retry("POST", "https://example.com")
            
            assert result["success"] is False
            assert "500" in result["error"] or "server error" in result["error"].lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

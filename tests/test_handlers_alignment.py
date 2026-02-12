"""
Unit-тесты для проверки выравнивания handlers с DB API
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.mark.asyncio
async def test_image_edit_creates_job_with_correct_params():
    """Тест что image edit создает job с правильными параметрами"""
    from handlers.images import confirm_edit
    from aiogram.types import CallbackQuery, Message, User
    from aiogram.fsm.context import FSMContext
    
    # Mock objects
    callback = MagicMock(spec=CallbackQuery)
    callback.from_user = MagicMock(spec=User)
    callback.from_user.id = 12345
    callback.message = MagicMock(spec=Message)
    callback.message.edit_text = AsyncMock()
    callback.answer = AsyncMock()
    
    state = MagicMock(spec=FSMContext)
    state.get_data = AsyncMock(return_value={
        "prompt": "test prompt",
        "photo_file_id": "test_file_id"
    })
    state.clear = AsyncMock()
    
    # Mock database
    with patch("handlers.images.db") as mock_db:
        mock_db.get_user_balance = AsyncMock(return_value=100)
        mock_db.charge_reserved_balance = AsyncMock(return_value=True)
        mock_db.create_job = AsyncMock(return_value=1)
        mock_db.update_job_status = AsyncMock()
        mock_db.complete_job = AsyncMock()
        
        # Mock NanoBanana API
        with patch("handlers.images.nano_banana") as mock_api:
            mock_api.edit_image = AsyncMock(return_value={
                "status": "completed",
                "result_url": "https://example.com/result.jpg"
            })
            
            # Call handler
            await confirm_edit(callback, state)
            
            # Verify create_job was called with correct params
            mock_db.create_job.assert_called_once()
            call_args = mock_db.create_job.call_args
            
            assert call_args[1]["user_id"] == 12345
            assert call_args[1]["job_type"] == "image"
            assert "params" in call_args[1]
            assert call_args[1]["params"]["action"] == "edit"
            assert call_args[1]["params"]["provider"] == "nano_banana"
            assert call_args[1]["params"]["prompt"] == "test prompt"
            assert "cost_estimate" in call_args[1]


@pytest.mark.asyncio
async def test_image_generate_creates_job_with_correct_params():
    """Тест что image generate создает job с правильными параметрами"""
    from handlers.images import confirm_generation
    from aiogram.types import CallbackQuery, Message, User
    from aiogram.fsm.context import FSMContext
    
    # Mock objects
    callback = MagicMock(spec=CallbackQuery)
    callback.from_user = MagicMock(spec=User)
    callback.from_user.id = 12345
    callback.message = MagicMock(spec=Message)
    callback.message.edit_text = AsyncMock()
    callback.answer = AsyncMock()
    
    state = MagicMock(spec=FSMContext)
    state.get_data = AsyncMock(return_value={
        "prompt": "test prompt"
    })
    state.clear = AsyncMock()
    
    # Mock database
    with patch("handlers.images.db") as mock_db:
        mock_db.get_user_balance = AsyncMock(return_value=100)
        mock_db.charge_reserved_balance = AsyncMock(return_value=True)
        mock_db.create_job = AsyncMock(return_value=1)
        mock_db.update_job_status = AsyncMock()
        mock_db.complete_job = AsyncMock()
        
        # Mock NanoBanana API
        with patch("handlers.images.nano_banana") as mock_api:
            mock_api.generate_image = AsyncMock(return_value={
                "status": "completed",
                "result_url": "https://example.com/result.jpg"
            })
            
            # Call handler
            await confirm_generation(callback, state)
            
            # Verify create_job was called with correct params
            mock_db.create_job.assert_called_once()
            call_args = mock_db.create_job.call_args
            
            assert call_args[1]["user_id"] == 12345
            assert call_args[1]["job_type"] == "image"
            assert "params" in call_args[1]
            assert call_args[1]["params"]["action"] == "generate"
            assert call_args[1]["params"]["provider"] == "nano_banana"
            assert call_args[1]["params"]["prompt"] == "test prompt"
            assert "cost_estimate" in call_args[1]


@pytest.mark.asyncio
async def test_video_generate_creates_job_with_correct_params():
    """Тест что video generate создает job с правильными параметрами"""
    from handlers.videos import confirm_video_generation
    from aiogram.types import CallbackQuery, Message, User
    from aiogram.fsm.context import FSMContext
    
    # Mock objects
    callback = MagicMock(spec=CallbackQuery)
    callback.from_user = MagicMock(spec=User)
    callback.from_user.id = 12345
    callback.data = "confirm_video:kling-3.0:5"
    callback.message = MagicMock(spec=Message)
    callback.message.edit_text = AsyncMock()
    callback.answer = AsyncMock()
    
    state = MagicMock(spec=FSMContext)
    state.get_data = AsyncMock(return_value={
        "prompt": "test video prompt"
    })
    state.clear = AsyncMock()
    
    # Mock database
    with patch("handlers.videos.db") as mock_db:
        mock_db.get_user_balance = AsyncMock(return_value=200)
        mock_db.charge_reserved_balance = AsyncMock(return_value=True)
        mock_db.create_job = AsyncMock(return_value=1)
        mock_db.update_job_status = AsyncMock()
        mock_db.complete_job = AsyncMock()
        
        # Mock Kling API
        with patch("handlers.videos.kling") as mock_api:
            mock_api.generate_video = AsyncMock(return_value={
                "status": "completed",
                "result_url": "https://example.com/result.mp4"
            })
            
            # Call handler
            await confirm_video_generation(callback, state)
            
            # Verify create_job was called with correct params
            mock_db.create_job.assert_called_once()
            call_args = mock_db.create_job.call_args
            
            assert call_args[1]["user_id"] == 12345
            assert call_args[1]["job_type"] == "video"
            assert "params" in call_args[1]
            assert call_args[1]["params"]["action"] == "generate"
            assert call_args[1]["params"]["provider"] == "kling"
            assert call_args[1]["params"]["model"] == "kling-3.0"
            assert call_args[1]["params"]["duration_seconds"] == 5
            assert call_args[1]["params"]["prompt"] == "test video prompt"
            assert "cost_estimate" in call_args[1]


@pytest.mark.asyncio
async def test_job_completion_uses_correct_status():
    """Тест что handlers используют правильные статусы (completed/failed)"""
    from handlers.images import confirm_generation
    from aiogram.types import CallbackQuery, Message, User
    from aiogram.fsm.context import FSMContext
    
    # Mock objects
    callback = MagicMock(spec=CallbackQuery)
    callback.from_user = MagicMock(spec=User)
    callback.from_user.id = 12345
    callback.message = MagicMock(spec=Message)
    callback.message.edit_text = AsyncMock()
    callback.answer = AsyncMock()
    
    state = MagicMock(spec=FSMContext)
    state.get_data = AsyncMock(return_value={"prompt": "test"})
    state.clear = AsyncMock()
    
    # Mock database
    with patch("handlers.images.db") as mock_db:
        mock_db.get_user_balance = AsyncMock(return_value=100)
        mock_db.charge_reserved_balance = AsyncMock(return_value=True)
        mock_db.create_job = AsyncMock(return_value=1)
        mock_db.update_job_status = AsyncMock()
        mock_db.complete_job = AsyncMock()
        
        # Mock NanoBanana API - success
        with patch("handlers.images.nano_banana") as mock_api:
            mock_api.generate_image = AsyncMock(return_value={
                "status": "completed",
                "result_url": "https://example.com/result.jpg"
            })
            
            await confirm_generation(callback, state)
            
            # Verify complete_job was called with "completed" status
            mock_db.complete_job.assert_called_once()
            call_args = mock_db.complete_job.call_args
            assert call_args[1]["status"] == "completed"
            assert "result_url" in call_args[1]


@pytest.mark.asyncio
async def test_job_failure_uses_correct_status():
    """Тест что handlers используют статус 'failed' при ошибках"""
    from handlers.images import confirm_generation
    from aiogram.types import CallbackQuery, Message, User
    from aiogram.fsm.context import FSMContext
    
    # Mock objects
    callback = MagicMock(spec=CallbackQuery)
    callback.from_user = MagicMock(spec=User)
    callback.from_user.id = 12345
    callback.message = MagicMock(spec=Message)
    callback.message.edit_text = AsyncMock()
    callback.answer = AsyncMock()
    
    state = MagicMock(spec=FSMContext)
    state.get_data = AsyncMock(return_value={"prompt": "test"})
    state.clear = AsyncMock()
    
    # Mock database
    with patch("handlers.images.db") as mock_db:
        mock_db.get_user_balance = AsyncMock(return_value=100)
        mock_db.charge_reserved_balance = AsyncMock(return_value=True)
        mock_db.create_job = AsyncMock(return_value=1)
        mock_db.update_job_status = AsyncMock()
        mock_db.complete_job = AsyncMock()
        
        # Mock NanoBanana API - failure
        with patch("handlers.images.nano_banana") as mock_api:
            mock_api.generate_image = AsyncMock(return_value={
                "status": "failed",
                "error": "API error"
            })
            
            await confirm_generation(callback, state)
            
            # Verify complete_job was called with "failed" status
            mock_db.complete_job.assert_called_once()
            call_args = mock_db.complete_job.call_args
            assert call_args[1]["status"] == "failed"
            assert "error_message" in call_args[1]

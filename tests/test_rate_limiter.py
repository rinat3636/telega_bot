"""
Тесты для rate limiter
"""
import pytest
import time
import os
import sys

# Добавить корневую директорию в путь
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.rate_limiter import RateLimiter


@pytest.fixture
def rate_limiter():
    """Фикстура для rate limiter"""
    return RateLimiter()


def test_rate_limit_basic(rate_limiter):
    """Тест базового rate limiting"""
    user_id = 12345
    action = 'test_action'
    
    # Первые 5 запросов должны пройти
    for i in range(5):
        allowed, remaining = rate_limiter.check_rate_limit(
            user_id=user_id,
            action=action,
            limit=5,
            window=60
        )
        assert allowed is True
        assert remaining == 4 - i
    
    # 6-й запрос должен быть заблокирован
    allowed, remaining = rate_limiter.check_rate_limit(
        user_id=user_id,
        action=action,
        limit=5,
        window=60
    )
    assert allowed is False
    assert remaining == 0


def test_rate_limit_window_expiry(rate_limiter):
    """Тест истечения окна rate limit"""
    user_id = 12345
    action = 'test_action'
    
    # Сделать 3 запроса
    for _ in range(3):
        rate_limiter.check_rate_limit(
            user_id=user_id,
            action=action,
            limit=3,
            window=1  # 1 секунда
        )
    
    # 4-й запрос должен быть заблокирован
    allowed, _ = rate_limiter.check_rate_limit(
        user_id=user_id,
        action=action,
        limit=3,
        window=1
    )
    assert allowed is False
    
    # Подождать 1.1 секунды
    time.sleep(1.1)
    
    # Теперь запрос должен пройти (окно истекло)
    allowed, remaining = rate_limiter.check_rate_limit(
        user_id=user_id,
        action=action,
        limit=3,
        window=1
    )
    assert allowed is True
    assert remaining == 2


def test_rate_limit_different_users(rate_limiter):
    """Тест изоляции лимитов между пользователями"""
    user1 = 12345
    user2 = 67890
    action = 'test_action'
    
    # User1 делает 5 запросов
    for _ in range(5):
        rate_limiter.check_rate_limit(
            user_id=user1,
            action=action,
            limit=5,
            window=60
        )
    
    # User1 заблокирован
    allowed, _ = rate_limiter.check_rate_limit(
        user_id=user1,
        action=action,
        limit=5,
        window=60
    )
    assert allowed is False
    
    # User2 может делать запросы
    allowed, remaining = rate_limiter.check_rate_limit(
        user_id=user2,
        action=action,
        limit=5,
        window=60
    )
    assert allowed is True
    assert remaining == 4


def test_rate_limit_different_actions(rate_limiter):
    """Тест изоляции лимитов между действиями"""
    user_id = 12345
    action1 = 'image_generation'
    action2 = 'video_generation'
    
    # Сделать 5 запросов для action1
    for _ in range(5):
        rate_limiter.check_rate_limit(
            user_id=user_id,
            action=action1,
            limit=5,
            window=60
        )
    
    # action1 заблокирован
    allowed, _ = rate_limiter.check_rate_limit(
        user_id=user_id,
        action=action1,
        limit=5,
        window=60
    )
    assert allowed is False
    
    # action2 доступен
    allowed, remaining = rate_limiter.check_rate_limit(
        user_id=user_id,
        action=action2,
        limit=5,
        window=60
    )
    assert allowed is True
    assert remaining == 4


def test_rate_limit_reset(rate_limiter):
    """Тест сброса лимитов"""
    user_id = 12345
    action = 'test_action'
    
    # Сделать 5 запросов
    for _ in range(5):
        rate_limiter.check_rate_limit(
            user_id=user_id,
            action=action,
            limit=5,
            window=60
        )
    
    # Заблокирован
    allowed, _ = rate_limiter.check_rate_limit(
        user_id=user_id,
        action=action,
        limit=5,
        window=60
    )
    assert allowed is False
    
    # Сбросить лимиты
    rate_limiter.reset_user(user_id)
    
    # Теперь запросы проходят
    allowed, remaining = rate_limiter.check_rate_limit(
        user_id=user_id,
        action=action,
        limit=5,
        window=60
    )
    assert allowed is True
    assert remaining == 4


def test_wait_time_calculation(rate_limiter):
    """Тест расчета времени ожидания"""
    user_id = 12345
    action = 'test_action'
    
    # Сделать 3 запроса
    for _ in range(3):
        rate_limiter.check_rate_limit(
            user_id=user_id,
            action=action,
            limit=3,
            window=10
        )
    
    # Получить время ожидания
    wait_time = rate_limiter.get_wait_time(user_id, action, window=10)
    
    # Должно быть около 10 секунд
    assert 9 <= wait_time <= 10


if __name__ == '__main__':
    pytest.main([__file__, '-v'])

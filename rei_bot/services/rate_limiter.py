"""
Rate limiter с поддержкой Redis (централизованный)
Решение F-205: Redis-based rate limiting для horizontal scaling
"""
import time
import asyncio
from typing import Dict, Tuple, Optional
from collections import defaultdict
import logging
import config

logger = logging.getLogger(__name__)


class RedisRateLimiter:
    """
    Централизованный rate limiter с поддержкой Redis
    
    Использует Redis для хранения счетчиков (для production)
    Fallback на in-memory для dev/testing
    """
    
    def __init__(self, redis_client=None):
        """
        Args:
            redis_client: Redis клиент (опционально, fallback на in-memory)
        """
        self.redis = redis_client
        self.local_requests: Dict[int, Dict[str, list]] = defaultdict(lambda: defaultdict(list))
        
        # Максимальное количество активных задач на пользователя
        self.max_active_jobs = getattr(config, 'MAX_ACTIVE_JOBS_PER_USER', 3)
    
    async def check_rate_limit(
        self,
        user_id: int,
        action: str,
        limit: int = 10,
        window: int = 60
    ) -> Tuple[bool, int]:
        """
        Проверить rate limit (sliding window)
        
        Args:
            user_id: ID пользователя
            action: Действие (например, 'message', 'image_generation')
            limit: Максимум действий в окне
            window: Окно в секундах
        
        Returns:
            (allowed, remaining): (разрешено ли действие, сколько осталось попыток)
        """
        if self.redis:
            return await self._check_redis_rate_limit(user_id, action, limit, window)
        else:
            return self._check_local_rate_limit(user_id, action, limit, window)
    
    async def _check_redis_rate_limit(
        self,
        user_id: int,
        action: str,
        limit: int,
        window: int
    ) -> Tuple[bool, int]:
        """Redis-based rate limiting (sliding window с sorted set)"""
        key = f"rate_limit:{user_id}:{action}"
        now = time.time()
        
        try:
            pipe = self.redis.pipeline()
            
            # 1. Удалить старые записи (за пределами окна)
            pipe.zremrangebyscore(key, 0, now - window)
            
            # 2. Получить текущее количество
            pipe.zcard(key)
            
            # 3. Добавить новую запись
            pipe.zadd(key, {str(now): now})
            
            # 4. Установить TTL
            pipe.expire(key, window)
            
            results = await pipe.execute()
            current_count = results[1]
            
            if current_count >= limit:
                # Удалить только что добавленную запись
                await self.redis.zrem(key, str(now))
                return False, 0
            
            remaining = limit - current_count - 1
            return True, remaining
        
        except Exception as e:
            logger.error(f"Redis rate limit error: {e}")
            # Fallback на local
            return self._check_local_rate_limit(user_id, action, limit, window)
    
    def _check_local_rate_limit(
        self,
        user_id: int,
        action: str,
        limit: int,
        window: int
    ) -> Tuple[bool, int]:
        """In-memory rate limiting (fallback)"""
        current_time = time.time()
        
        # Очистить старые записи
        self.local_requests[user_id][action] = [
            ts for ts in self.local_requests[user_id][action]
            if current_time - ts < window
        ]
        
        # Проверить лимит
        count = len(self.local_requests[user_id][action])
        
        if count >= limit:
            return False, 0
        
        # Добавить новую запись
        self.local_requests[user_id][action].append(current_time)
        
        return True, limit - count - 1
    
    async def check_cost_limit(
        self,
        user_id: int,
        cost: float,
        limit_per_hour: float = 1000.0
    ) -> Tuple[bool, float]:
        """
        Проверка лимита по стоимости (₽/час)
        
        Args:
            user_id: ID пользователя
            cost: Стоимость операции
            limit_per_hour: Лимит в рублях за час
        
        Returns:
            (allowed, remaining_budget): (разрешено ли, остаток бюджета)
        """
        if not self.redis:
            # Без Redis не проверяем cost limit
            return True, limit_per_hour
        
        key = f"cost_limit:{user_id}"
        now = time.time()
        window = 3600  # 1 час
        
        try:
            pipe = self.redis.pipeline()
            
            # 1. Удалить старые записи
            pipe.zremrangebyscore(key, 0, now - window)
            
            # 2. Получить все записи за последний час
            pipe.zrange(key, 0, -1)
            
            results = await pipe.execute()
            recent_costs = results[1]
            
            # Суммировать стоимость
            total_cost = sum(float(c) for c in recent_costs)
            
            if total_cost + cost > limit_per_hour:
                remaining = limit_per_hour - total_cost
                return False, max(0, remaining)
            
            # Добавить новую запись
            await self.redis.zadd(key, {str(cost): now})
            await self.redis.expire(key, window)
            
            remaining = limit_per_hour - total_cost - cost
            return True, remaining
        
        except Exception as e:
            logger.error(f"Redis cost limit error: {e}")
            return True, limit_per_hour
    
    async def get_wait_time(self, user_id: int, action: str, window: int = 60) -> int:
        """
        Получить время ожидания до следующей попытки
        
        Returns:
            Секунды до следующей попытки
        """
        if self.redis:
            key = f"rate_limit:{user_id}:{action}"
            now = time.time()
            
            try:
                # Получить самую старую запись в окне
                oldest = await self.redis.zrange(key, 0, 0, withscores=True)
                
                if not oldest:
                    return 0
                
                oldest_time = oldest[0][1]
                wait_time = window - (now - oldest_time)
                return max(0, int(wait_time))
            
            except Exception as e:
                logger.error(f"Redis wait time error: {e}")
                return 0
        else:
            # Local fallback
            if not self.local_requests[user_id][action]:
                return 0
            
            current_time = time.time()
            oldest_request = min(self.local_requests[user_id][action])
            
            wait_time = window - (current_time - oldest_request)
            return max(0, int(wait_time))
    
    async def reset_user(self, user_id: int):
        """Сбросить лимиты для пользователя (для админов)"""
        if self.redis:
            # Удалить все ключи пользователя
            pattern = f"rate_limit:{user_id}:*"
            keys = await self.redis.keys(pattern)
            if keys:
                await self.redis.delete(*keys)
            
            # Удалить cost limit
            cost_key = f"cost_limit:{user_id}"
            await self.redis.delete(cost_key)
        else:
            # Local fallback
            if user_id in self.local_requests:
                del self.local_requests[user_id]


# Глобальный экземпляр rate limiter
rate_limiter: Optional[RedisRateLimiter] = None


def init_rate_limiter(redis_client=None):
    """
    Инициализировать глобальный rate limiter
    
    Args:
        redis_client: Redis клиент (опционально)
    """
    global rate_limiter
    rate_limiter = RedisRateLimiter(redis_client)
    logger.info("Rate limiter initialized")


def get_rate_limiter() -> RedisRateLimiter:
    """Получить глобальный rate limiter"""
    if rate_limiter is None:
        raise RuntimeError("Rate limiter not initialized. Call init_rate_limiter() first.")
    return rate_limiter


# ==================== MIDDLEWARE ДЛЯ AIOGRAM ====================

from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery
from typing import Callable, Any, Awaitable


class RateLimitMiddleware(BaseMiddleware):
    """
    Middleware для проверки rate limit
    """
    
    def __init__(self, rate_limiter: RedisRateLimiter):
        super().__init__()
        self.rate_limiter = rate_limiter
    
    async def __call__(
        self,
        handler: Callable[[Message, Dict[str, Any]], Awaitable[Any]],
        event: Message | CallbackQuery,
        data: Dict[str, Any]
    ) -> Any:
        user_id = event.from_user.id
        
        # Определить действие
        if isinstance(event, Message):
            if event.text:
                action = 'message'
            elif event.photo:
                action = 'photo'
            else:
                action = 'other'
        elif isinstance(event, CallbackQuery):
            action = 'callback'
        else:
            action = 'unknown'
        
        # Проверить rate limit (10 действий в минуту)
        allowed, remaining = await self.rate_limiter.check_rate_limit(
            user_id=user_id,
            action=action,
            limit=10,
            window=60
        )
        
        if not allowed:
            wait_time = await self.rate_limiter.get_wait_time(user_id, action, 60)
            
            if isinstance(event, Message):
                await event.answer(
                    f"⚠️ Слишком много запросов. Подождите {wait_time} секунд."
                )
            elif isinstance(event, CallbackQuery):
                await event.answer(
                    f"⚠️ Слишком много запросов. Подождите {wait_time} секунд.",
                    show_alert=True
                )
            
            return
        
        # Продолжить обработку
        return await handler(event, data)


# ==================== УТИЛИТЫ ====================

async def can_create_job(user_id: int, db) -> Tuple[bool, str]:
    """
    Проверить, может ли пользователь создать задачу
    
    Returns:
        (allowed, message): (разрешено ли, сообщение об ошибке)
    """
    # Проверить количество активных задач
    active_jobs = await db.get_user_active_jobs(user_id)
    max_jobs = get_rate_limiter().max_active_jobs
    
    if len(active_jobs) >= max_jobs:
        return False, f"⚠️ У вас уже {len(active_jobs)} активных задач. Дождитесь завершения."
    
    return True, ""


async def check_balance_and_reserve(user_id: int, amount: float, db) -> Tuple[bool, str]:
    """
    Проверить баланс и зарезервировать средства
    
    Returns:
        (success, message): (успешно ли, сообщение об ошибке)
    """
    balance = await db.get_balance(user_id)
    
    if balance < amount:
        return False, f"⚠️ Недостаточно средств. Ваш баланс: {balance:.2f} ₽, требуется: {amount:.2f} ₽"
    
    # Зарезервировать средства
    ref_id = f"temp_{user_id}_{int(time.time())}"
    success = await db.reserve_balance(user_id, amount, ref_id)
    
    if not success:
        return False, "⚠️ Не удалось зарезервировать средства. Попробуйте еще раз."
    
    return True, ref_id

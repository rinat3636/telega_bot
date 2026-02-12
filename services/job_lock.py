"""
Job Lock Manager - глобальный lock для параллельных job пользователя
Решение F-202: защита от двойного списания при параллельных генерациях
"""
import uuid
import asyncio
from contextlib import asynccontextmanager
from typing import Optional
import logging

logger = logging.getLogger(__name__)


class JobLockError(Exception):
    """Ошибка при попытке получить lock"""
    pass


class JobLockManager:
    """
    Менеджер блокировок для job пользователей
    
    Политика: 1 активная paid-job на пользователя
    """
    
    def __init__(self, redis_client=None):
        """
        Args:
            redis_client: Redis клиент (опционально, fallback на in-memory)
        """
        self.redis = redis_client
        self.local_locks = {}  # Fallback для in-memory
    
    @asynccontextmanager
    async def acquire_user_job_lock(self, user_id: int, timeout: int = 300):
        """
        Получить lock для создания job пользователя
        
        Args:
            user_id: ID пользователя
            timeout: Таймаут lock в секундах (по умолчанию 5 минут)
        
        Raises:
            JobLockError: Если у пользователя уже есть активная job
        
        Example:
            async with job_lock_manager.acquire_user_job_lock(user_id):
                # Создать и запустить job
                pass
        """
        lock_key = f"job_lock:user:{user_id}"
        lock_id = str(uuid.uuid4())
        
        if self.redis:
            # Redis distributed lock
            acquired = await self._acquire_redis_lock(lock_key, lock_id, timeout)
        else:
            # In-memory lock (fallback)
            acquired = await self._acquire_local_lock(lock_key, lock_id, timeout)
        
        if not acquired:
            raise JobLockError(
                f"У пользователя {user_id} уже есть активная задача. "
                "Дождитесь завершения или отмените текущую задачу."
            )
        
        try:
            yield
        finally:
            # Release lock
            if self.redis:
                await self._release_redis_lock(lock_key, lock_id)
            else:
                await self._release_local_lock(lock_key, lock_id)
    
    async def _acquire_redis_lock(self, key: str, lock_id: str, timeout: int) -> bool:
        """Получить Redis lock"""
        try:
            # SET key value NX EX timeout
            result = await self.redis.set(
                key, 
                lock_id, 
                nx=True,  # Only if not exists
                ex=timeout  # Expire after timeout
            )
            return result is not None
        except Exception as e:
            logger.error(f"Failed to acquire Redis lock: {e}")
            return False
    
    async def _release_redis_lock(self, key: str, lock_id: str):
        """Освободить Redis lock (только если это наш lock)"""
        try:
            # Lua script для атомарной проверки и удаления
            script = """
            if redis.call("get", KEYS[1]) == ARGV[1] then
                return redis.call("del", KEYS[1])
            else
                return 0
            end
            """
            await self.redis.eval(script, 1, key, lock_id)
        except Exception as e:
            logger.error(f"Failed to release Redis lock: {e}")
    
    async def _acquire_local_lock(self, key: str, lock_id: str, timeout: int) -> bool:
        """Получить in-memory lock (fallback)"""
        if key in self.local_locks:
            # Проверить, не истек ли lock
            lock_data = self.local_locks[key]
            if asyncio.get_event_loop().time() < lock_data['expires_at']:
                return False  # Lock еще активен
        
        # Создать lock
        self.local_locks[key] = {
            'lock_id': lock_id,
            'expires_at': asyncio.get_event_loop().time() + timeout
        }
        
        return True
    
    async def _release_local_lock(self, key: str, lock_id: str):
        """Освободить in-memory lock"""
        if key in self.local_locks:
            lock_data = self.local_locks[key]
            if lock_data['lock_id'] == lock_id:
                del self.local_locks[key]
    
    async def is_locked(self, user_id: int) -> bool:
        """
        Проверить, заблокирован ли пользователь
        
        Returns:
            True если у пользователя есть активная job
        """
        lock_key = f"job_lock:user:{user_id}"
        
        if self.redis:
            exists = await self.redis.exists(lock_key)
            return exists > 0
        else:
            if lock_key in self.local_locks:
                lock_data = self.local_locks[lock_key]
                return asyncio.get_event_loop().time() < lock_data['expires_at']
            return False
    
    async def force_release(self, user_id: int):
        """
        Принудительно освободить lock (для админов)
        
        Args:
            user_id: ID пользователя
        """
        lock_key = f"job_lock:user:{user_id}"
        
        if self.redis:
            await self.redis.delete(lock_key)
        else:
            if lock_key in self.local_locks:
                del self.local_locks[lock_key]
        
        logger.info(f"Force released job lock for user {user_id}")


# Глобальный экземпляр
job_lock_manager: Optional[JobLockManager] = None


def init_job_lock_manager(redis_client=None):
    """
    Инициализировать глобальный job lock manager
    
    Args:
        redis_client: Redis клиент (опционально)
    """
    global job_lock_manager
    job_lock_manager = JobLockManager(redis_client)
    logger.info("Job lock manager initialized")


def get_job_lock_manager() -> JobLockManager:
    """Получить глобальный job lock manager"""
    if job_lock_manager is None:
        raise RuntimeError("Job lock manager not initialized. Call init_job_lock_manager() first.")
    return job_lock_manager

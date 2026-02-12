"""
Webhook Validator - защита от replay-атак и подделки webhook
Решение F-204: проверка подписи, timestamp и дубликатов
"""
import hmac
import hashlib
from datetime import datetime, timedelta
from typing import Optional
import logging

logger = logging.getLogger(__name__)


class WebhookValidator:
    """
    Валидатор webhook с защитой от replay-атак
    
    Проверки:
    1. HMAC подпись (защита от подделки)
    2. Timestamp window (защита от старых replay)
    3. Дубликаты webhook_id (защита от повторной обработки)
    """
    
    def __init__(self, secret_key: str, db_instance=None, redis_client=None):
        """
        Args:
            secret_key: Секретный ключ для HMAC
            db_instance: Database instance для хранения webhook events
            redis_client: Redis клиент (опционально)
        """
        self.secret_key = secret_key
        self.db = db_instance
        self.redis = redis_client
        self.processed_webhooks = set()  # Fallback для in-memory
    
    def validate_signature(self, payload: bytes, signature: str) -> bool:
        """
        Проверка HMAC подписи webhook
        
        Args:
            payload: Тело запроса (bytes)
            signature: Подпись из заголовка
        
        Returns:
            True если подпись валидна
        """
        expected_signature = hmac.new(
            self.secret_key.encode(),
            payload,
            hashlib.sha256
        ).hexdigest()
        
        # Constant-time comparison для защиты от timing attacks
        return hmac.compare_digest(signature, expected_signature)
    
    def validate_timestamp(self, timestamp: str, window_seconds: int = 300) -> bool:
        """
        Проверка timestamp webhook (защита от replay старых событий)
        
        Args:
            timestamp: ISO timestamp из webhook
            window_seconds: Допустимое окно (по умолчанию 5 минут)
        
        Returns:
            True если timestamp в допустимом окне
        """
        try:
            webhook_time = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
            now = datetime.now(webhook_time.tzinfo)
            
            # Webhook не должен быть старше window_seconds
            if now - webhook_time > timedelta(seconds=window_seconds):
                logger.warning(f"Webhook timestamp too old: {timestamp}")
                return False
            
            # Webhook не должен быть из будущего (допуск 60 сек на clock skew)
            if webhook_time > now + timedelta(seconds=60):
                logger.warning(f"Webhook timestamp from future: {timestamp}")
                return False
            
            return True
        except Exception as e:
            logger.error(f"Failed to parse timestamp {timestamp}: {e}")
            return False
    
    async def is_duplicate(self, webhook_id: str, ttl: int = 86400) -> bool:
        """
        Проверка на дубликат webhook (защита от повторной обработки)
        
        Args:
            webhook_id: Уникальный ID webhook
            ttl: Время хранения (по умолчанию 24 часа)
        
        Returns:
            True если webhook уже был обработан
        """
        # Приоритет: Redis > Database > In-memory
        if self.redis:
            # Redis-based deduplication (лучший вариант для production)
            key = f"webhook:processed:{webhook_id}"
            
            exists = await self.redis.exists(key)
            if exists:
                logger.info(f"Duplicate webhook detected (Redis): {webhook_id}")
                return True
            
            await self.redis.setex(key, ttl, "1")
            return False
        
        elif self.db:
            # Database-based deduplication (хорошо для production без Redis)
            if await self.db.is_webhook_processed(webhook_id):
                logger.info(f"Duplicate webhook detected (DB): {webhook_id}")
                return True
            
            ttl_hours = ttl // 3600  # Конвертировать секунды в часы
            success = await self.db.mark_webhook_processed(webhook_id, ttl_hours)
            return not success  # False = успешно помечен, True = уже существовал
        
        else:
            # In-memory fallback (НЕ рекомендуется для production!)
            logger.warning("Using in-memory webhook deduplication - NOT recommended for production")
            
            if webhook_id in self.processed_webhooks:
                logger.info(f"Duplicate webhook detected (in-memory): {webhook_id}")
                return True
            
            self.processed_webhooks.add(webhook_id)
            return False
    
    async def validate_webhook(
        self,
        payload: bytes,
        signature: str,
        webhook_id: str,
        timestamp: str,
        window_seconds: int = 300
    ) -> tuple[bool, Optional[str]]:
        """
        Полная валидация webhook
        
        Args:
            payload: Тело запроса
            signature: HMAC подпись
            webhook_id: Уникальный ID webhook
            timestamp: Timestamp события
            window_seconds: Допустимое окно времени
        
        Returns:
            (is_valid, error_message)
        """
        # 1. Проверка подписи
        if not self.validate_signature(payload, signature):
            return False, "Invalid signature"
        
        # 2. Проверка timestamp
        if not self.validate_timestamp(timestamp, window_seconds):
            return False, "Timestamp out of window"
        
        # 3. Проверка дубликата
        if await self.is_duplicate(webhook_id):
            return False, "Duplicate webhook"
        
        return True, None


# Глобальный экземпляр
webhook_validator: Optional[WebhookValidator] = None


def init_webhook_validator(secret_key: str, db_instance=None, redis_client=None):
    """
    Инициализировать глобальный webhook validator
    
    Args:
        secret_key: Секретный ключ для HMAC
        db_instance: Database instance (опционально)
        redis_client: Redis клиент (опционально)
    """
    global webhook_validator
    webhook_validator = WebhookValidator(secret_key, db_instance, redis_client)
    
    if redis_client:
        logger.info("Webhook validator initialized with Redis deduplication")
    elif db_instance:
        logger.info("Webhook validator initialized with Database deduplication")
    else:
        logger.warning("Webhook validator initialized with in-memory deduplication (NOT recommended for production)")
    
    return webhook_validator


def get_webhook_validator() -> WebhookValidator:
    """Получить глобальный webhook validator"""
    if webhook_validator is None:
        raise RuntimeError("Webhook validator not initialized. Call init_webhook_validator() first.")
    return webhook_validator

"""
Сервис для работы с платежами через ЮКассу (YooKassa)
Production-ready: async-обертки через asyncio.to_thread, унифицированный API
"""
import uuid
import asyncio
from typing import Dict, Any, Optional
from datetime import datetime
import logging

try:
    from yookassa import Configuration, Payment
except ImportError:
    Payment = None
    Configuration = None

import config


logger = logging.getLogger(__name__)


class YooKassaService:
    """Сервис для работы с ЮКассой (async-ready)"""
    
    def __init__(self):
        """Инициализация сервиса"""
        if Configuration is None or Payment is None:
            logger.warning("YooKassa SDK не установлен. Установите: pip install yookassa")
            self.enabled = False
            return
        
        if not config.YOOKASSA_SHOP_ID or not config.YOOKASSA_SECRET_KEY:
            logger.warning("YooKassa credentials не настроены в .env")
            self.enabled = False
            return
        
        # Настройка конфигурации YooKassa
        Configuration.account_id = config.YOOKASSA_SHOP_ID
        Configuration.secret_key = config.YOOKASSA_SECRET_KEY
        
        self.enabled = True
        logger.info("YooKassa сервис инициализирован")
    
    def _create_payment_sync(
        self,
        amount: float,
        description: str,
        user_id: int,
        return_url: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Синхронное создание платежа (внутренний метод)
        
        Returns:
            {
                "id": str,
                "confirmation_url": str,
                "status": str,
                "expires_at": str,
                "error": str (если ошибка)
            }
        """
        if not self.enabled:
            return {
                "error": "YooKassa не настроена. Проверьте .env и установите библиотеку yookassa"
            }
        
        try:
            # Генерация уникального ключа идемпотентности
            idempotence_key = str(uuid.uuid4())
            
            # Создание платежа
            payment = Payment.create({
                "amount": {
                    "value": f"{amount:.2f}",
                    "currency": "RUB"
                },
                "confirmation": {
                    "type": "redirect",
                    "return_url": return_url or config.YOOKASSA_RETURN_URL
                },
                "capture": True,  # Автоматическое подтверждение платежа
                "description": description,
                "metadata": {
                    "user_id": str(user_id)
                }
            }, idempotence_key)
            
            # Получение URL для оплаты
            confirmation_url = payment.confirmation.confirmation_url
            
            # Получение expires_at
            expires_at = None
            if hasattr(payment, 'expires_at') and payment.expires_at:
                expires_at = payment.expires_at
            
            logger.info(f"Создан платеж {payment.id} для пользователя {user_id} на сумму {amount} ₽")
            
            return {
                "id": payment.id,  # УНИФИЦИРОВАНО: "id" вместо "payment_id"
                "confirmation_url": confirmation_url,
                "status": payment.status,
                "expires_at": expires_at
            }
            
        except Exception as e:
            logger.error(f"Ошибка создания платежа: {e}", exc_info=True)
            return {
                "error": str(e)
            }
    
    async def create_payment(
        self,
        user_id: int,
        amount: int
    ) -> Dict[str, Any]:
        """
        Создание платежа (async, унифицированный API)
        
        Args:
            user_id: ID пользователя Telegram
            amount: Сумма платежа в рублях (int)
        
        Returns:
            {
                "id": str,
                "confirmation_url": str,
                "status": str,
                "expires_at": str,
                "error": str (если ошибка)
            }
        """
        description = f"Пополнение баланса на {amount} ₽"
        
        # Вызов синхронного метода в отдельном потоке
        return await asyncio.to_thread(
            self._create_payment_sync,
            amount=float(amount),
            description=description,
            user_id=user_id,
            return_url=None
        )
    
    def _check_payment_sync(self, payment_id: str) -> Dict[str, Any]:
        """
        Синхронная проверка статуса платежа (внутренний метод)
        
        Returns:
            {
                "status": str,
                "paid": bool,
                "amount": float,
                "user_id": int,
                "error": str (если ошибка)
            }
        """
        if not self.enabled:
            return {
                "error": "YooKassa не настроена"
            }
        
        try:
            payment = Payment.find_one(payment_id)
            
            user_id = None
            if payment.metadata and "user_id" in payment.metadata:
                user_id = int(payment.metadata["user_id"])
            
            return {
                "status": payment.status,
                "paid": payment.paid,
                "amount": float(payment.amount.value),
                "user_id": user_id
            }
            
        except Exception as e:
            logger.error(f"Ошибка проверки платежа {payment_id}: {e}", exc_info=True)
            return {
                "error": str(e)
            }
    
    async def check_payment_status(self, provider_payment_id: str) -> Dict[str, Any]:
        """
        Проверка статуса платежа (async, унифицированный API)
        
        Args:
            provider_payment_id: ID платежа в YooKassa
        
        Returns:
            {
                "status": str,
                "paid": bool,
                "amount": float,
                "user_id": int,
                "error": str (если ошибка)
            }
        """
        # Вызов синхронного метода в отдельном потоке
        return await asyncio.to_thread(
            self._check_payment_sync,
            payment_id=provider_payment_id
        )
    
    def verify_webhook(self, notification_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Обработка webhook уведомления от YooKassa (синхронный, быстрый)
        
        Args:
            notification_data: Данные из webhook
        
        Returns:
            {
                "success": bool,
                "event": str,
                "status": str,
                "amount": float,
                "user_id": int,
                "error": str (если ошибка)
            }
        """
        if not self.enabled:
            return {
                "success": False,
                "error": "YooKassa не настроена"
            }
        
        try:
            event = notification_data.get("event")
            payment_obj = notification_data.get("object")
            
            if not payment_obj:
                return {
                    "success": False,
                    "error": "Нет данных о платеже в webhook"
                }
            
            user_id = None
            if payment_obj.get("metadata") and "user_id" in payment_obj["metadata"]:
                user_id = int(payment_obj["metadata"]["user_id"])
            
            return {
                "success": True,
                "event": event,
                "status": payment_obj.get("status"),
                "amount": float(payment_obj.get("amount", {}).get("value", 0)),
                "user_id": user_id
            }
            
        except Exception as e:
            logger.error(f"Ошибка обработки webhook: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e)
            }


# Глобальный экземпляр сервиса
yookassa_service = YooKassaService()

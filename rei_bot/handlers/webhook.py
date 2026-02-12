"""
Обработчик webhook уведомлений от YooKassa (идемпотентный + replay protection)
"""
from aiohttp import web
import logging
import json

from database.models import db
from services.yookassa_payment import yookassa_service


logger = logging.getLogger(__name__)


async def handle_yookassa_webhook(request: web.Request) -> web.Response:
    """
    Обработка webhook уведомлений от YooKassa (идемпотентный + replay protection)
    
    Этот эндпоинт должен быть доступен по URL, который вы укажете в настройках YooKassa.
    Например: https://your-domain.com/webhook/yookassa
    
    Защита:
    - HMAC подпись (защита от подделки)
    - Timestamp window (защита от старых replay)
    - Deduplication по webhook_id (защита от повторной обработки)
    - Идемпотентность по payment_id
    """
    try:
        # ===== REPLAY PROTECTION: Валидация webhook =====
        from services.webhook_validator import get_webhook_validator
        
        # 1. Получить payload и подпись
        payload = await request.read()
        signature = request.headers.get('X-YooKassa-Signature', '')
        
        # 2. Парсить JSON (payload — bytes, нужна декодировка)
        data = json.loads(payload.decode('utf-8'))
        
        # 3. Извлечь webhook_id и timestamp
        webhook_id = data.get('id')
        timestamp = data.get('created_at')
        
        if not webhook_id or not timestamp:
            logger.error("Webhook не содержит id или created_at")
            return web.Response(status=400, text="Missing webhook id or timestamp")
        
        # 4. Валидация
        try:
            validator = get_webhook_validator()
            is_valid, error = await validator.validate_webhook(
                payload=payload,
                signature=signature,
                webhook_id=webhook_id,
                timestamp=timestamp
            )
            
            if not is_valid:
                logger.warning(f"Webhook validation failed: {error}")
                if error == "Duplicate webhook":
                    # Дубликат - возвращаем 200 OK
                    return web.Response(status=200, text="OK - duplicate")
                else:
                    # Невалидный webhook - отклоняем
                    return web.Response(status=401, text=f"Validation failed: {error}")
        except RuntimeError as e:
            # Validator не инициализирован - FAIL CLOSED (отклоняем webhook)
            logger.error(f"Webhook validator not initialized: {e}")
            return web.Response(status=503, text="Webhook validation service unavailable")
        
        logger.info(f"Получен webhook от YooKassa: {json.dumps(data, ensure_ascii=False)}")
        
        # Извлекаем payment_id
        payment_object = data.get('object', {})
        provider_payment_id = payment_object.get('id')
        
        if not provider_payment_id:
            logger.error("Webhook не содержит payment ID")
            return web.Response(status=400, text="Missing payment ID")
        
        # ===== ИДЕМПОТЕНТНОСТЬ: Проверяем, обработан ли уже этот платеж =====
        existing_payment = await db.get_payment_by_provider_id(provider_payment_id)
        
        if existing_payment:
            if existing_payment['status'] == 'paid':
                logger.info(f"✅ Платеж {provider_payment_id} уже обработан (status=paid). Возвращаем 200 OK.")
                return web.Response(status=200, text="OK - already processed")
            
            # Если статус pending, продолжаем обработку
            logger.info(f"Платеж {provider_payment_id} существует со статусом {existing_payment['status']}, обновляем...")
        
        # Обрабатываем уведомление
        result = yookassa_service.verify_webhook(data)
        
        if not result["success"]:
            logger.error(f"Ошибка обработки webhook: {result.get('error')}")
            return web.Response(status=400, text="Invalid webhook data")
        
        event = result["event"]
        status = result["status"]
        amount = result["amount"]
        user_id = result.get("user_id")
        
        logger.info(f"Webhook обработан: event={event}, payment_id={provider_payment_id}, status={status}, user_id={user_id}")
        
        # ===== ОБРАБОТКА УСПЕШНОЙ ОПЛАТЫ =====
        if event == "payment.succeeded" and status == "succeeded":
            # Создать платеж если не существует
            if not existing_payment:
                payment_id = await db.create_payment(
                    user_id=user_id,
                    provider_payment_id=provider_payment_id,
                    amount=amount,
                    status='pending'
                )
                
                if payment_id is None:
                    # Платеж уже существует (race condition)
                    logger.warning(f"Платеж {provider_payment_id} уже существует (race condition)")
                    existing_payment = await db.get_payment_by_provider_id(provider_payment_id)
                    
                    if existing_payment['status'] == 'paid':
                        logger.info(f"✅ Платеж уже обработан. Возвращаем 200 OK.")
                        return web.Response(status=200, text="OK - already processed")
            
            # Атомарная обработка платежа (идемпотентно)
            result = await db.process_paid_payment(
                provider_payment_id=provider_payment_id,
                user_id=user_id,
                amount=amount
            )
            
            if not result.get("success"):
                logger.error(f"❌ Ошибка обработки платежа {provider_payment_id}: {result.get('error')}")
                return web.Response(status=500, text=f"Error: {result.get('error')}")
            
            if result.get("already_processed"):
                logger.info(f"✅ Платеж {provider_payment_id} уже обработан (идемпотентность). Возвращаем 200 OK.")
                return web.Response(status=200, text="OK - already credited")
            
            logger.info(f"✅ Платеж {provider_payment_id} успешно обработан. Зачислено {amount} ₽ пользователю {user_id}. Новый баланс: {result['new_balance']} ₽")
        
        # ===== ОБРАБОТКА ОТМЕНЫ/ВОЗВРАТА =====
        elif event in ("payment.canceled", "refund.succeeded"):
            # Обновить статус платежа
            await db.update_payment_status(provider_payment_id, 'refunded')
            
            # Списать средства (если были зачислены) - идемпотентно
            if existing_payment and existing_payment['status'] == 'paid':
                try:
                    await db.add_ledger_entry(
                        user_id=user_id,
                        entry_type='debit',
                        amount=-amount,
                        ref_type='refund',
                        ref_id=provider_payment_id,
                        description=f'Возврат платежа {provider_payment_id}'
                    )
                    logger.info(f"⚠️ Платеж {provider_payment_id} возвращен. Списано {amount} ₽ у пользователя {user_id}")
                except Exception as e:
                    # Идемпотентность: если UNIQUE - возврат уже обработан
                    if "UNIQUE constraint failed" in str(e) or "IntegrityError" in str(type(e)):
                        logger.info(f"✅ Возврат {provider_payment_id} уже обработан (идемпотентность). Возвращаем 200 OK.")
                    else:
                        logger.error(f"❌ Ошибка обработки возврата {provider_payment_id}: {e}", exc_info=True)
                        return web.Response(status=500, text=f"Error processing refund: {e}")
        
        return web.Response(status=200, text="OK")
    
    except json.JSONDecodeError as e:
        logger.error(f"Ошибка парсинга JSON: {e}")
        return web.Response(status=400, text="Invalid JSON")
    
    except Exception as e:
        logger.error(f"Ошибка обработки webhook: {e}", exc_info=True)
        return web.Response(status=500, text="Internal server error")


async def setup_webhook_routes(app: web.Application):
    """Настроить маршруты для webhook"""
    app.router.add_post('/webhook/yookassa', handle_yookassa_webhook)
    logger.info("Webhook routes configured")

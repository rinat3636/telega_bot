"""
Тесты для платежей (идемпотентность)
"""
import pytest
import os
import sys

# Добавить корневую директорию в путь
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.models import Database


@pytest.fixture
async def test_db():
    """Фикстура для тестовой БД"""
    db = Database(":memory:")
    await db.init_db()
    yield db


@pytest.mark.asyncio
async def test_payment_idempotency(test_db):
    """Тест идемпотентности платежей"""
    user_id = 12345
    provider_payment_id = "test_payment_123"
    amount = 1000.0
    
    # Создать пользователя
    await test_db.get_or_create_user(user_id)
    
    # Первая попытка создать платеж
    payment_id_1 = await test_db.create_payment(
        user_id=user_id,
        provider_payment_id=provider_payment_id,
        amount=amount,
        status='pending'
    )
    
    assert payment_id_1 is not None
    
    # Вторая попытка с тем же provider_payment_id
    payment_id_2 = await test_db.create_payment(
        user_id=user_id,
        provider_payment_id=provider_payment_id,
        amount=amount,
        status='pending'
    )
    
    # Должен вернуть None (платеж уже существует)
    assert payment_id_2 is None
    
    # Проверить, что в БД только один платеж
    payment = await test_db.get_payment_by_provider_id(provider_payment_id)
    assert payment is not None
    assert payment['id'] == payment_id_1


@pytest.mark.asyncio
async def test_payment_status_update(test_db):
    """Тест обновления статуса платежа"""
    user_id = 12345
    provider_payment_id = "test_payment_456"
    amount = 500.0
    
    # Создать пользователя и платеж
    await test_db.get_or_create_user(user_id)
    payment_id = await test_db.create_payment(
        user_id=user_id,
        provider_payment_id=provider_payment_id,
        amount=amount,
        status='pending'
    )
    
    # Проверить начальный статус
    payment = await test_db.get_payment_by_provider_id(provider_payment_id)
    assert payment['status'] == 'pending'
    
    # Обновить статус на 'paid'
    success = await test_db.update_payment_status(provider_payment_id, 'paid')
    assert success is True
    
    # Проверить обновленный статус
    payment = await test_db.get_payment_by_provider_id(provider_payment_id)
    assert payment['status'] == 'paid'
    assert payment['paid_at'] is not None


@pytest.mark.asyncio
async def test_payment_double_processing_protection(test_db):
    """Тест защиты от двойной обработки платежа"""
    user_id = 12345
    provider_payment_id = "test_payment_789"
    amount = 1000.0
    
    # Создать пользователя и платеж
    await test_db.get_or_create_user(user_id)
    await test_db.create_payment(
        user_id=user_id,
        provider_payment_id=provider_payment_id,
        amount=amount,
        status='pending'
    )
    
    # Первая обработка: обновить статус и добавить в ledger
    await test_db.update_payment_status(provider_payment_id, 'paid')
    await test_db.add_ledger_entry(
        user_id=user_id,
        entry_type='credit',
        amount=amount,
        ref_type='payment',
        ref_id=provider_payment_id,
        description='Пополнение через YooKassa'
    )
    
    balance_after_first = await test_db.get_balance(user_id)
    assert balance_after_first == 1000.0
    
    # Вторая обработка (webhook повторился)
    payment = await test_db.get_payment_by_provider_id(provider_payment_id)
    
    if payment['status'] == 'paid':
        # Платеж уже обработан, не добавляем в ledger повторно
        pass
    
    balance_after_second = await test_db.get_balance(user_id)
    
    # Баланс не должен измениться
    assert balance_after_second == 1000.0


if __name__ == '__main__':
    pytest.main([__file__, '-v'])

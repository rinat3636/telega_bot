"""
Тесты для ledger (баланс)
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
    db = Database(":memory:")  # In-memory БД для тестов
    await db.init_db()
    yield db


@pytest.mark.asyncio
async def test_ledger_balance_calculation(test_db):
    """Тест расчета баланса через ledger"""
    user_id = 12345
    
    # Создать пользователя
    await test_db.get_or_create_user(user_id)
    
    # Начальный баланс должен быть 0
    balance = await test_db.get_balance(user_id)
    assert balance == 0.0
    
    # Добавить credit
    await test_db.add_ledger_entry(
        user_id=user_id,
        entry_type='credit',
        amount=1000.0,
        ref_type='payment',
        ref_id='test_payment_1',
        description='Тестовое пополнение'
    )
    
    balance = await test_db.get_balance(user_id)
    assert balance == 1000.0
    
    # Добавить debit
    await test_db.add_ledger_entry(
        user_id=user_id,
        entry_type='debit',
        amount=-50.0,
        ref_type='job',
        ref_id='test_job_1',
        description='Тестовое списание'
    )
    
    balance = await test_db.get_balance(user_id)
    assert balance == 950.0
    
    # Добавить refund
    await test_db.add_ledger_entry(
        user_id=user_id,
        entry_type='refund',
        amount=50.0,
        ref_type='job',
        ref_id='test_job_1',
        description='Тестовый возврат'
    )
    
    balance = await test_db.get_balance(user_id)
    assert balance == 1000.0


@pytest.mark.asyncio
async def test_reserve_balance_success(test_db):
    """Тест успешного резервирования баланса"""
    user_id = 12345
    
    # Создать пользователя и пополнить баланс
    await test_db.get_or_create_user(user_id)
    await test_db.add_ledger_entry(
        user_id=user_id,
        entry_type='credit',
        amount=1000.0,
        ref_type='admin',
        ref_id=None,
        description='Начальный баланс'
    )
    
    # Зарезервировать средства
    success = await test_db.reserve_balance(user_id, 100.0, 'test_reservation_1')
    assert success is True
    
    # Баланс должен уменьшиться
    balance = await test_db.get_balance(user_id)
    assert balance == 900.0


@pytest.mark.asyncio
async def test_reserve_balance_insufficient_funds(test_db):
    """Тест резервирования при недостаточных средствах"""
    user_id = 12345
    
    # Создать пользователя с малым балансом
    await test_db.get_or_create_user(user_id)
    await test_db.add_ledger_entry(
        user_id=user_id,
        entry_type='credit',
        amount=50.0,
        ref_type='admin',
        ref_id=None,
        description='Начальный баланс'
    )
    
    # Попытка зарезервировать больше, чем есть
    success = await test_db.reserve_balance(user_id, 100.0, 'test_reservation_1')
    assert success is False
    
    # Баланс не должен измениться
    balance = await test_db.get_balance(user_id)
    assert balance == 50.0


@pytest.mark.asyncio
async def test_ledger_history(test_db):
    """Тест получения истории операций"""
    user_id = 12345
    
    # Создать пользователя
    await test_db.get_or_create_user(user_id)
    
    # Добавить несколько операций
    await test_db.add_ledger_entry(
        user_id=user_id,
        entry_type='credit',
        amount=1000.0,
        ref_type='payment',
        ref_id='payment_1',
        description='Пополнение 1'
    )
    
    await test_db.add_ledger_entry(
        user_id=user_id,
        entry_type='debit',
        amount=-50.0,
        ref_type='job',
        ref_id='job_1',
        description='Списание 1'
    )
    
    await test_db.add_ledger_entry(
        user_id=user_id,
        entry_type='credit',
        amount=500.0,
        ref_type='payment',
        ref_id='payment_2',
        description='Пополнение 2'
    )
    
    # Получить историю
    history = await test_db.get_ledger_history(user_id, limit=10)
    
    assert len(history) == 3
    assert history[0]['description'] == 'Пополнение 2'  # Последняя операция первая
    assert history[1]['description'] == 'Списание 1'
    assert history[2]['description'] == 'Пополнение 1'


@pytest.mark.asyncio
async def test_no_negative_balance(test_db):
    """Тест защиты от отрицательного баланса"""
    user_id = 12345
    
    # Создать пользователя с балансом 100
    await test_db.get_or_create_user(user_id)
    await test_db.add_ledger_entry(
        user_id=user_id,
        entry_type='credit',
        amount=100.0,
        ref_type='admin',
        ref_id=None,
        description='Начальный баланс'
    )
    
    # Попытка зарезервировать 150 (больше чем есть)
    success = await test_db.reserve_balance(user_id, 150.0, 'test_reservation_1')
    assert success is False
    
    # Баланс должен остаться 100
    balance = await test_db.get_balance(user_id)
    assert balance == 100.0


if __name__ == '__main__':
    pytest.main([__file__, '-v'])

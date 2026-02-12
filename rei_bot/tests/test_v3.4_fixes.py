"""
Unit тесты для v3.4 fixes
"""
import pytest
import asyncio
from database.models import Database


# ==================== Triggers для UPDATE/DELETE ====================

@pytest.mark.asyncio
async def test_balance_cache_updates_on_ledger_update():
    """
    Тест: user_balance_cache обновляется при UPDATE ledger
    
    Проверяем, что charge_reserved_balance() (который делает UPDATE) обновляет кэш
    """
    db = Database(db_path=":memory:")
    await db.init_db()
    
    # Создать пользователя
    await db.create_user(tg_id=123, username="test_user")
    
    # Добавить баланс 100₽
    await db.add_ledger_entry(
        user_id=123,
        entry_type='credit',
        amount=100.0,
        ref_type='test',
        ref_id='initial',
        description='Initial balance'
    )
    
    # Проверить кэш
    async with db.get_connection() as conn:
        async with conn.execute(
            "SELECT balance, ledger_count FROM user_balance_cache WHERE user_id = ?",
            (123,)
        ) as cursor:
            row = await cursor.fetchone()
            assert row is not None
            assert abs(row[0] - 100.0) < 0.01
            assert row[1] == 1
    
    # Зарезервировать 50₽
    await db.reserve_balance(user_id=123, amount=50.0, ref_id='reservation1')
    
    # Проверить кэш после резервирования
    async with db.get_connection() as conn:
        async with conn.execute(
            "SELECT balance, ledger_count FROM user_balance_cache WHERE user_id = ?",
            (123,)
        ) as cursor:
            row = await cursor.fetchone()
            assert abs(row[0] - 50.0) < 0.01  # 100 - 50 = 50
            assert row[1] == 2  # initial + reservation
    
    # Списать зарезервированные средства (UPDATE ledger)
    await db.charge_reserved_balance(
        user_id=123,
        ref_id='reservation1',
        actual_amount=30.0,
        new_ref_id='job1'
    )
    
    # Проверить кэш после charge_reserved_balance (должен обновиться через trigger UPDATE)
    async with db.get_connection() as conn:
        async with conn.execute(
            "SELECT balance, ledger_count FROM user_balance_cache WHERE user_id = ?",
            (123,)
        ) as cursor:
            row = await cursor.fetchone()
            # Баланс: 100 - 30 = 70 (+ 20 reconciliation)
            assert abs(row[0] - 70.0) < 0.01
            # Записей: initial + reservation->job + reconciliation = 3
            assert row[1] == 3


@pytest.mark.asyncio
async def test_balance_cache_updates_on_ledger_delete():
    """
    Тест: user_balance_cache обновляется при DELETE ledger
    """
    db = Database(db_path=":memory:")
    await db.init_db()
    
    # Создать пользователя
    await db.create_user(tg_id=123, username="test_user")
    
    # Добавить баланс 100₽
    await db.add_ledger_entry(
        user_id=123,
        entry_type='credit',
        amount=100.0,
        ref_type='test',
        ref_id='initial',
        description='Initial balance'
    )
    
    # Проверить кэш
    async with db.get_connection() as conn:
        async with conn.execute(
            "SELECT balance FROM user_balance_cache WHERE user_id = ?",
            (123,)
        ) as cursor:
            row = await cursor.fetchone()
            assert abs(row[0] - 100.0) < 0.01
    
    # Удалить запись из ledger
    async with db.get_connection() as conn:
        await conn.execute(
            "DELETE FROM ledger WHERE user_id = ? AND ref_id = ?",
            (123, 'initial')
        )
        await conn.commit()
    
    # Проверить кэш после DELETE (должен обновиться через trigger DELETE)
    async with db.get_connection() as conn:
        async with conn.execute(
            "SELECT balance, ledger_count FROM user_balance_cache WHERE user_id = ?",
            (123,)
        ) as cursor:
            row = await cursor.fetchone()
            assert abs(row[0] - 0.0) < 0.01  # Баланс = 0
            assert row[1] == 0  # Записей = 0


# ==================== Идемпотентность charge_reserved_balance ====================

@pytest.mark.asyncio
async def test_charge_reserved_balance_idempotent():
    """
    Тест: charge_reserved_balance идемпотентен
    
    Проверяем, что повторный вызов не падает и не изменяет баланс
    """
    db = Database(db_path=":memory:")
    await db.init_db()
    
    # Создать пользователя
    await db.create_user(tg_id=123, username="test_user")
    
    # Добавить баланс 100₽
    await db.add_ledger_entry(
        user_id=123,
        entry_type='credit',
        amount=100.0,
        ref_type='test',
        ref_id='initial',
        description='Initial balance'
    )
    
    # Зарезервировать 50₽
    await db.reserve_balance(user_id=123, amount=50.0, ref_id='reservation1')
    
    # Первый вызов charge_reserved_balance
    await db.charge_reserved_balance(
        user_id=123,
        ref_id='reservation1',
        actual_amount=30.0,
        new_ref_id='job1'
    )
    
    # Баланс после первого вызова
    balance1 = await db.get_balance(123)
    assert abs(balance1 - 70.0) < 0.01  # 100 - 30 = 70
    
    # Повторный вызов charge_reserved_balance (идемпотентность)
    await db.charge_reserved_balance(
        user_id=123,
        ref_id='reservation1',
        actual_amount=30.0,
        new_ref_id='job1'
    )
    
    # Баланс не должен измениться
    balance2 = await db.get_balance(123)
    assert abs(balance2 - 70.0) < 0.01
    
    # Количество записей в ledger не должно увеличиться
    history = await db.get_ledger_history(123, limit=10)
    # initial + reservation->job + reconciliation = 3 записи
    assert len(history) == 3


@pytest.mark.asyncio
async def test_charge_reserved_balance_reconciliation_idempotent():
    """
    Тест: reconciliation запись не дублируется при повторном вызове
    """
    db = Database(db_path=":memory:")
    await db.init_db()
    
    # Создать пользователя
    await db.create_user(tg_id=123, username="test_user")
    
    # Добавить баланс 100₽
    await db.add_ledger_entry(
        user_id=123,
        entry_type='credit',
        amount=100.0,
        ref_type='test',
        ref_id='initial',
        description='Initial balance'
    )
    
    # Зарезервировать 50₽
    await db.reserve_balance(user_id=123, amount=50.0, ref_id='reservation1')
    
    # Первый вызов charge_reserved_balance (с reconciliation)
    await db.charge_reserved_balance(
        user_id=123,
        ref_id='reservation1',
        actual_amount=30.0,
        new_ref_id='job1'
    )
    
    # Проверить, что reconciliation создана
    history = await db.get_ledger_history(123, limit=10)
    reconciliation_entries = [e for e in history if e['ref_type'] == 'reconciliation']
    assert len(reconciliation_entries) == 1
    assert abs(reconciliation_entries[0]['amount'] - 20.0) < 0.01
    
    # Повторный вызов (идемпотентность)
    await db.charge_reserved_balance(
        user_id=123,
        ref_id='reservation1',
        actual_amount=30.0,
        new_ref_id='job1'
    )
    
    # Reconciliation не должна дублироваться
    history2 = await db.get_ledger_history(123, limit=10)
    reconciliation_entries2 = [e for e in history2 if e['ref_type'] == 'reconciliation']
    assert len(reconciliation_entries2) == 1  # Все еще 1 запись


# ==================== Запуск тестов ====================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])

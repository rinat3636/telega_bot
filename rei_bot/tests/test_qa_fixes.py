"""
Unit тесты для QA fixes v3.3
"""
import pytest
import asyncio
import time
from database.models import Database
from services.priority_queue import PriorityQueue, JobPriority
from services.metrics import MetricsCollector


# ==================== QA-1: Атомарность reserve_balance ====================

@pytest.mark.asyncio
async def test_reserve_balance_atomicity():
    """
    Тест QA-1: reserve_balance должен быть атомарным
    
    Проверяем, что проверка баланса и создание записи происходят в одной транзакции
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
    
    # Попытка зарезервировать 50₽ - должно пройти
    result1 = await db.reserve_balance(user_id=123, amount=50.0, ref_id='job1')
    assert result1 is True
    
    # Баланс теперь 50₽
    balance = await db.get_balance(123)
    assert balance == 50.0
    
    # Попытка зарезервировать еще 60₽ - должно провалиться
    result2 = await db.reserve_balance(user_id=123, amount=60.0, ref_id='job2')
    assert result2 is False
    
    # Баланс не изменился
    balance = await db.get_balance(123)
    assert balance == 50.0


@pytest.mark.asyncio
async def test_charge_reserved_balance_reconciliation():
    """
    Тест QA-1: charge_reserved_balance должен создавать reconciliation записи
    
    Проверяем, что если actual_amount != reserved_amount, создается компенсирующая запись
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
    
    # Списать только 30₽ (меньше, чем зарезервировано)
    await db.charge_reserved_balance(
        user_id=123,
        ref_id='reservation1',
        actual_amount=30.0,
        new_ref_id='job1'
    )
    
    # Баланс должен быть 70₽ (100 - 30)
    balance = await db.get_balance(123)
    assert abs(balance - 70.0) < 0.01
    
    # Проверить, что создана reconciliation запись
    history = await db.get_ledger_history(123, limit=10)
    reconciliation_entries = [e for e in history if e['ref_type'] == 'reconciliation']
    assert len(reconciliation_entries) == 1
    assert abs(reconciliation_entries[0]['amount'] - 20.0) < 0.01  # возврат 20₽


# ==================== QA-2: user_balance_cache ====================

@pytest.mark.asyncio
async def test_user_balance_cache_creation():
    """
    Тест QA-2: user_balance_cache таблица должна создаваться
    """
    db = Database(db_path=":memory:")
    await db.init_db()
    
    # Проверить, что таблица существует
    async with db.get_connection() as conn:
        async with conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='user_balance_cache'"
        ) as cursor:
            row = await cursor.fetchone()
            assert row is not None


@pytest.mark.asyncio
async def test_user_balance_cache_trigger():
    """
    Тест QA-2: trigger должен автоматически обновлять кэш
    """
    db = Database(db_path=":memory:")
    await db.init_db()
    
    # Создать пользователя
    await db.create_user(tg_id=123, username="test_user")
    
    # Добавить баланс
    await db.add_ledger_entry(
        user_id=123,
        entry_type='credit',
        amount=100.0,
        ref_type='test',
        ref_id='initial',
        description='Initial balance'
    )
    
    # Проверить, что кэш обновился
    async with db.get_connection() as conn:
        async with conn.execute(
            "SELECT balance, ledger_count FROM user_balance_cache WHERE user_id = ?",
            (123,)
        ) as cursor:
            row = await cursor.fetchone()
            assert row is not None
            assert abs(row[0] - 100.0) < 0.01
            assert row[1] == 1


# ==================== QA-3: FIFO в priority queue ====================

def test_priority_queue_fifo():
    """
    Тест QA-3: priority queue должен быть FIFO внутри одного priority level
    """
    # Mock Redis
    class MockRedis:
        def __init__(self):
            self.data = []
        
        def zadd(self, key, mapping):
            for job_id, score in mapping.items():
                self.data.append((job_id, score))
        
        def zpopmax(self, key):
            if not self.data:
                return None
            self.data.sort(key=lambda x: x[1], reverse=True)
            return [self.data.pop(0)]
        
        def zcount(self, key, min_score, max_score):
            return len([x for x in self.data if min_score <= x[1] <= max_score])
    
    redis_mock = MockRedis()
    queue = PriorityQueue(redis_client=redis_mock, queue_name="test_queue")
    
    # Добавить 3 задачи с одинаковым priority
    time1 = time.time()
    queue.enqueue(job_id=1, priority=JobPriority.NORMAL)
    time.sleep(0.01)
    queue.enqueue(job_id=2, priority=JobPriority.NORMAL)
    time.sleep(0.01)
    queue.enqueue(job_id=3, priority=JobPriority.NORMAL)
    
    # Извлечь задачи - должны быть в порядке 1, 2, 3 (FIFO)
    job1 = queue.dequeue()
    job2 = queue.dequeue()
    job3 = queue.dequeue()
    
    assert job1 == 1
    assert job2 == 2
    assert job3 == 3


# ==================== QA-4: length_by_priority ====================

def test_length_by_priority_correct_buckets():
    """
    Тест QA-4: length_by_priority должен корректно считать задачи
    """
    class MockRedis:
        def __init__(self):
            self.data = []
        
        def zadd(self, key, mapping):
            for job_id, score in mapping.items():
                self.data.append((job_id, score))
        
        def zcount(self, key, min_score, max_score):
            return len([x for x in self.data if min_score <= x[1] <= max_score])
    
    redis_mock = MockRedis()
    queue = PriorityQueue(redis_client=redis_mock, queue_name="test_queue")
    
    # Добавить задачи разных priority
    queue.enqueue(job_id=1, priority=JobPriority.LOW)
    queue.enqueue(job_id=2, priority=JobPriority.NORMAL)
    queue.enqueue(job_id=3, priority=JobPriority.NORMAL)
    queue.enqueue(job_id=4, priority=JobPriority.HIGH)
    
    # Проверить подсчет
    counts = queue.length_by_priority()
    assert counts[JobPriority.LOW.name] == 1
    assert counts[JobPriority.NORMAL.name] == 2
    assert counts[JobPriority.HIGH.name] == 1
    assert counts[JobPriority.CRITICAL.name] == 0


# ==================== QA-5: Histogram metrics с labels ====================

def test_histogram_metrics_preserve_labels():
    """
    Тест QA-5: histogram metrics должны сохранять labels
    """
    metrics = MetricsCollector()
    
    # Добавить метрики с разными labels
    metrics.observe_histogram("job_duration", 10.5, labels={"type": "image"})
    metrics.observe_histogram("job_duration", 20.3, labels={"type": "image"})
    metrics.observe_histogram("job_duration", 5.1, labels={"type": "video"})
    
    # Получить все метрики
    all_metrics = metrics.get_all_metrics()
    histograms = all_metrics["histograms"]
    
    # Проверить, что labels сохранились
    assert "job_duration{type=image}" in histograms
    assert "job_duration{type=video}" in histograms
    
    # Проверить статистику
    image_stats = histograms["job_duration{type=image}"]
    assert image_stats["count"] == 2
    assert abs(image_stats["mean"] - 15.4) < 0.1
    
    video_stats = histograms["job_duration{type=video}"]
    assert video_stats["count"] == 1
    assert abs(video_stats["mean"] - 5.1) < 0.1


# ==================== Запуск тестов ====================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])

"""
Chaos Test: Redis Failure Simulation

Simulates Redis connection loss and verifies system resilience
"""
import asyncio
import redis
import time
import logging
from typing import Dict

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class RedisChaosTest:
    """Simulate Redis failures and test system resilience"""
    
    def __init__(self, redis_host='localhost', redis_port=6379):
        self.redis_host = redis_host
        self.redis_port = redis_port
        self.redis_client = None
        self.results: Dict[str, bool] = {}
    
    def connect_redis(self):
        """Connect to Redis"""
        try:
            self.redis_client = redis.Redis(
                host=self.redis_host,
                port=self.redis_port,
                decode_responses=True,
                socket_connect_timeout=5
            )
            self.redis_client.ping()
            logger.info("✅ Connected to Redis")
            return True
        except Exception as e:
            logger.error(f"❌ Redis connection failed: {e}")
            return False
    
    def test_queue_resilience(self):
        """Test: Queue operations with Redis failure"""
        logger.info("\n🧪 Test: Queue Resilience")
        
        try:
            # 1. Add job to queue
            self.redis_client.lpush('rq:queue:default', 'test_job_1')
            logger.info("✅ Job added to queue")
            
            # 2. Simulate Redis failure
            logger.info("⚠️  Simulating Redis connection loss...")
            self.redis_client.connection_pool.disconnect()
            
            # 3. Try to add another job (should fail gracefully)
            try:
                self.redis_client.lpush('rq:queue:default', 'test_job_2')
                logger.error("❌ Should have failed but didn't")
                self.results['queue_resilience'] = False
            except redis.ConnectionError:
                logger.info("✅ Graceful failure detected")
                self.results['queue_resilience'] = True
            
            # 4. Reconnect
            self.connect_redis()
            
            # 5. Verify queue integrity
            queue_length = self.redis_client.llen('rq:queue:default')
            logger.info(f"✅ Queue recovered, length: {queue_length}")
            
        except Exception as e:
            logger.error(f"❌ Test failed: {e}")
            self.results['queue_resilience'] = False
    
    def test_rate_limiter_resilience(self):
        """Test: Rate limiter with Redis failure"""
        logger.info("\n🧪 Test: Rate Limiter Resilience")
        
        try:
            # 1. Set rate limit key
            user_id = 'test_user_123'
            key = f'rate_limit:{user_id}'
            self.redis_client.zadd(key, {str(time.time()): time.time()})
            logger.info("✅ Rate limit key set")
            
            # 2. Simulate Redis failure
            logger.info("⚠️  Simulating Redis connection loss...")
            self.redis_client.connection_pool.disconnect()
            
            # 3. Try to check rate limit (should fallback to allow)
            try:
                self.redis_client.zcount(key, '-inf', '+inf')
                logger.error("❌ Should have failed but didn't")
                self.results['rate_limiter_resilience'] = False
            except redis.ConnectionError:
                logger.info("✅ Graceful failure detected (fallback to allow)")
                self.results['rate_limiter_resilience'] = True
            
            # 4. Reconnect
            self.connect_redis()
            
        except Exception as e:
            logger.error(f"❌ Test failed: {e}")
            self.results['rate_limiter_resilience'] = False
    
    def test_lock_resilience(self):
        """Test: Distributed lock with Redis failure"""
        logger.info("\n🧪 Test: Distributed Lock Resilience")
        
        try:
            # 1. Acquire lock
            lock_key = 'lock:user:test_user_123'
            self.redis_client.set(lock_key, '1', ex=300)
            logger.info("✅ Lock acquired")
            
            # 2. Simulate Redis failure
            logger.info("⚠️  Simulating Redis connection loss...")
            self.redis_client.connection_pool.disconnect()
            
            # 3. Try to release lock (should fail gracefully)
            try:
                self.redis_client.delete(lock_key)
                logger.error("❌ Should have failed but didn't")
                self.results['lock_resilience'] = False
            except redis.ConnectionError:
                logger.info("✅ Graceful failure detected")
                self.results['lock_resilience'] = True
            
            # 4. Reconnect
            self.connect_redis()
            
            # 5. Verify lock can be re-acquired
            self.redis_client.set(lock_key, '1', ex=300)
            logger.info("✅ Lock re-acquired after recovery")
            
        except Exception as e:
            logger.error(f"❌ Test failed: {e}")
            self.results['lock_resilience'] = False
    
    def test_redis_restart(self):
        """Test: Redis restart scenario"""
        logger.info("\n🧪 Test: Redis Restart")
        
        try:
            # 1. Add test data
            self.redis_client.set('test_key', 'test_value')
            self.redis_client.lpush('test_queue', 'item1', 'item2')
            logger.info("✅ Test data added")
            
            # 2. Simulate Redis restart (flush all data)
            logger.info("⚠️  Simulating Redis restart (FLUSHALL)...")
            self.redis_client.flushall()
            
            # 3. Verify data loss
            value = self.redis_client.get('test_key')
            queue_length = self.redis_client.llen('test_queue')
            
            if value is None and queue_length == 0:
                logger.info("✅ Data cleared as expected")
                self.results['redis_restart'] = True
            else:
                logger.error("❌ Data should have been cleared")
                self.results['redis_restart'] = False
            
            # 4. Verify system can recover
            self.redis_client.set('recovery_test', 'ok')
            if self.redis_client.get('recovery_test') == 'ok':
                logger.info("✅ System recovered after restart")
            
        except Exception as e:
            logger.error(f"❌ Test failed: {e}")
            self.results['redis_restart'] = False
    
    def run_all_tests(self):
        """Run all chaos tests"""
        logger.info("=" * 60)
        logger.info("🔥 Starting Redis Chaos Tests")
        logger.info("=" * 60)
        
        if not self.connect_redis():
            logger.error("Cannot connect to Redis. Aborting tests.")
            return
        
        self.test_queue_resilience()
        self.test_rate_limiter_resilience()
        self.test_lock_resilience()
        self.test_redis_restart()
        
        # Summary
        logger.info("\n" + "=" * 60)
        logger.info("📊 Test Summary")
        logger.info("=" * 60)
        
        passed = sum(1 for v in self.results.values() if v)
        total = len(self.results)
        
        for test_name, result in self.results.items():
            status = "✅ PASS" if result else "❌ FAIL"
            logger.info(f"{status}: {test_name}")
        
        logger.info(f"\nTotal: {passed}/{total} tests passed")
        logger.info("=" * 60)
        
        return passed == total


if __name__ == '__main__':
    chaos_test = RedisChaosTest()
    success = chaos_test.run_all_tests()
    
    exit(0 if success else 1)

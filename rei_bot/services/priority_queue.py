"""
Priority Queue for Jobs

Implements multi-level priority queues with Redis sorted sets
"""
import redis
import time
import logging
from typing import Optional, Dict, List
from enum import IntEnum

logger = logging.getLogger(__name__)


class JobPriority(IntEnum):
    """Job priority levels (higher number = higher priority)"""
    CRITICAL = 100  # Admin operations, refunds
    HIGH = 75       # Paid jobs
    NORMAL = 50     # Free tier
    LOW = 25        # Batch operations


class PriorityQueue:
    """
    Priority queue implementation using Redis sorted sets
    
    Features:
    - Multiple priority levels
    - FIFO within same priority
    - Atomic operations
    - Distributed-safe
    """
    
    def __init__(self, redis_client: redis.Redis, queue_name: str = "jobs"):
        self.redis = redis_client
        self.queue_name = f"priority_queue:{queue_name}"
    
    def enqueue(
        self,
        job_id: int,
        priority: JobPriority = JobPriority.NORMAL,
        metadata: Optional[Dict] = None
    ) -> bool:
        """
        Add job to priority queue
        
        Args:
            job_id: Job ID
            priority: Priority level
            metadata: Optional metadata (stored separately)
        
        Returns:
            True if added successfully
        """
        try:
            # Score = priority * 1e9 - timestamp
            # This ensures FIFO within same priority level:
            # - Higher priority = higher score (processed first)
            # - Earlier timestamp = higher score (FIFO within priority)
            score = priority * 1e9 - time.time()
            
            # Add to sorted set
            self.redis.zadd(self.queue_name, {str(job_id): score})
            
            # Store metadata if provided
            if metadata:
                metadata_key = f"{self.queue_name}:metadata:{job_id}"
                self.redis.hset(metadata_key, mapping=metadata)
                self.redis.expire(metadata_key, 86400)  # 24 hours TTL
            
            logger.info(f"Enqueued job {job_id} with priority {priority.name}")
            return True
        
        except Exception as e:
            logger.error(f"Failed to enqueue job {job_id}: {e}")
            return False
    
    def dequeue(self) -> Optional[int]:
        """
        Get next job from queue (highest priority first)
        
        Returns:
            Job ID or None if queue is empty
        """
        try:
            # Get highest priority job (highest score)
            result = self.redis.zpopmax(self.queue_name)
            
            if not result:
                return None
            
            job_id = int(result[0][0])
            logger.debug(f"Dequeued job {job_id}")
            return job_id
        
        except Exception as e:
            logger.error(f"Failed to dequeue job: {e}")
            return None
    
    def peek(self, count: int = 1) -> List[int]:
        """
        Peek at next jobs without removing them
        
        Args:
            count: Number of jobs to peek
        
        Returns:
            List of job IDs
        """
        try:
            # Get top N jobs by score (descending)
            results = self.redis.zrevrange(self.queue_name, 0, count - 1)
            return [int(job_id) for job_id in results]
        
        except Exception as e:
            logger.error(f"Failed to peek queue: {e}")
            return []
    
    def remove(self, job_id: int) -> bool:
        """
        Remove specific job from queue
        
        Args:
            job_id: Job ID to remove
        
        Returns:
            True if removed
        """
        try:
            removed = self.redis.zrem(self.queue_name, str(job_id))
            
            # Remove metadata
            metadata_key = f"{self.queue_name}:metadata:{job_id}"
            self.redis.delete(metadata_key)
            
            if removed:
                logger.info(f"Removed job {job_id} from queue")
            
            return bool(removed)
        
        except Exception as e:
            logger.error(f"Failed to remove job {job_id}: {e}")
            return False
    
    def get_metadata(self, job_id: int) -> Optional[Dict]:
        """Get job metadata"""
        try:
            metadata_key = f"{self.queue_name}:metadata:{job_id}"
            metadata = self.redis.hgetall(metadata_key)
            return {k.decode(): v.decode() for k, v in metadata.items()} if metadata else None
        
        except Exception as e:
            logger.error(f"Failed to get metadata for job {job_id}: {e}")
            return None
    
    def length(self) -> int:
        """Get queue length"""
        try:
            return self.redis.zcard(self.queue_name)
        except Exception as e:
            logger.error(f"Failed to get queue length: {e}")
            return 0
    
    def length_by_priority(self) -> Dict[str, int]:
        """Get queue length by priority level"""
        try:
            counts = {}
            
            for priority in JobPriority:
                # Score = priority.value * 1e9 - timestamp
                # Bucket bounds:
                # - min_score: priority.value * 1e9 - 1e9 (oldest possible)
                # - max_score: priority.value * 1e9 (newest possible, current time)
                min_score = priority.value * 1e9 - 1e9
                max_score = priority.value * 1e9
                count = self.redis.zcount(self.queue_name, min_score, max_score)
                counts[priority.name] = count
            
            return counts
        
        except Exception as e:
            logger.error(f"Failed to get queue stats: {e}")
            return {}
    
    def clear(self):
        """Clear entire queue"""
        try:
            self.redis.delete(self.queue_name)
            logger.warning(f"Cleared queue {self.queue_name}")
        except Exception as e:
            logger.error(f"Failed to clear queue: {e}")
    
    def get_position(self, job_id: int) -> Optional[int]:
        """
        Get position of job in queue (0-indexed)
        
        Returns:
            Position or None if not in queue
        """
        try:
            # Get rank (0-indexed, ascending order)
            rank = self.redis.zrevrank(self.queue_name, str(job_id))
            return rank if rank is not None else None
        
        except Exception as e:
            logger.error(f"Failed to get position for job {job_id}: {e}")
            return None


class PriorityQueueManager:
    """Manage multiple priority queues"""
    
    def __init__(self, redis_client: redis.Redis):
        self.redis = redis_client
        self.queues: Dict[str, PriorityQueue] = {}
    
    def get_queue(self, queue_name: str) -> PriorityQueue:
        """Get or create queue"""
        if queue_name not in self.queues:
            self.queues[queue_name] = PriorityQueue(self.redis, queue_name)
        return self.queues[queue_name]
    
    def enqueue_job(
        self,
        job_id: int,
        job_type: str,
        priority: JobPriority = JobPriority.NORMAL,
        metadata: Optional[Dict] = None
    ) -> bool:
        """Enqueue job to appropriate queue"""
        queue = self.get_queue(job_type)
        return queue.enqueue(job_id, priority, metadata)
    
    def dequeue_job(self, job_type: str) -> Optional[int]:
        """Dequeue job from specific queue"""
        queue = self.get_queue(job_type)
        return queue.dequeue()
    
    def get_stats(self) -> Dict:
        """Get statistics for all queues"""
        stats = {}
        
        for queue_name, queue in self.queues.items():
            stats[queue_name] = {
                "total": queue.length(),
                "by_priority": queue.length_by_priority()
            }
        
        return stats


# Helper functions for common operations

def determine_job_priority(
    user_id: int,
    job_type: str,
    is_paid: bool,
    is_admin: bool = False
) -> JobPriority:
    """
    Determine job priority based on context
    
    Args:
        user_id: User ID
        job_type: Type of job
        is_paid: Whether user paid for this job
        is_admin: Whether this is an admin operation
    
    Returns:
        Priority level
    """
    if is_admin:
        return JobPriority.CRITICAL
    elif is_paid:
        return JobPriority.HIGH
    elif job_type == "batch":
        return JobPriority.LOW
    else:
        return JobPriority.NORMAL

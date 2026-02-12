"""
Сервис очереди задач (Redis + RQ)
"""
import config
from typing import Optional

# Проверяем наличие Redis
try:
    from redis import Redis
    from rq import Queue
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    Redis = None
    Queue = None


class JobQueue:
    """Очередь задач для асинхронной обработки"""
    
    def __init__(self):
        self.redis_conn = None
        self.queue = None
        self.enabled = False
        
        if REDIS_AVAILABLE and hasattr(config, 'REDIS_URL'):
            try:
                self.redis_conn = Redis.from_url(config.REDIS_URL)
                self.queue = Queue('default', connection=self.redis_conn)
                self.enabled = True
            except Exception as e:
                print(f"⚠️ Redis недоступен: {e}")
                print("⚠️ Задачи будут выполняться синхронно")
                self.enabled = False
        else:
            print("⚠️ Redis не настроен. Задачи будут выполняться синхронно")
            self.enabled = False
    
    def enqueue(self, func_name: str, *args, **kwargs):
        """
        Добавить задачу в очередь
        
        Args:
            func_name: Полное имя функции (например, 'workers.image_worker.generate_image')
            *args, **kwargs: Аргументы для функции
        
        Returns:
            Job ID или None если очередь не доступна
        """
        if not self.enabled:
            return None
        
        try:
            job = self.queue.enqueue(func_name, *args, **kwargs, job_timeout='10m')
            return job.id
        except Exception as e:
            print(f"❌ Ошибка добавления в очередь: {e}")
            return None
    
    def get_job_status(self, job_id: str) -> Optional[str]:
        """
        Получить статус задачи в очереди
        
        Returns:
            'queued', 'started', 'finished', 'failed', 'deferred', 'scheduled' или None
        """
        if not self.enabled or not job_id:
            return None
        
        try:
            from rq.job import Job
            job = Job.fetch(job_id, connection=self.redis_conn)
            return job.get_status()
        except Exception:
            return None
    
    def cancel_job(self, job_id: str) -> bool:
        """Отменить задачу в очереди"""
        if not self.enabled or not job_id:
            return False
        
        try:
            from rq.job import Job
            job = Job.fetch(job_id, connection=self.redis_conn)
            job.cancel()
            return True
        except Exception:
            return False


# Глобальный экземпляр очереди
job_queue = JobQueue()


# ==================== ФУНКЦИИ ДЛЯ ДОБАВЛЕНИЯ ЗАДАЧ ====================

async def enqueue_image_generation(job_id: int, user_id: int, prompt: str):
    """Добавить задачу генерации изображения в очередь"""
    if job_queue.enabled:
        return job_queue.enqueue(
            'workers.image_worker.generate_image',
            job_id, user_id, prompt
        )
    else:
        # Если очередь не доступна, выполнить синхронно
        from workers import image_worker
        await image_worker.generate_image(job_id, user_id, prompt)
        return None


async def enqueue_image_edit(job_id: int, user_id: int, image_path: str, prompt: str):
    """Добавить задачу редактирования изображения в очередь"""
    if job_queue.enabled:
        return job_queue.enqueue(
            'workers.image_worker.edit_image',
            job_id, user_id, image_path, prompt
        )
    else:
        from workers import image_worker
        await image_worker.edit_image(job_id, user_id, image_path, prompt)
        return None


async def enqueue_video_generation(
    job_id: int,
    user_id: int,
    mode: str,
    model: str,
    duration: int,
    content: str
):
    """Добавить задачу генерации видео в очередь"""
    if job_queue.enabled:
        return job_queue.enqueue(
            'workers.video_worker.generate_video',
            job_id, user_id, mode, model, duration, content
        )
    else:
        from workers import video_worker
        await video_worker.generate_video(job_id, user_id, mode, model, duration, content)
        return None

"""
GC Worker для автоматической очистки истекших ассетов
Решение F-304: физическое удаление файлов по expires_at
"""
import os
import asyncio
import logging
from datetime import datetime, timedelta
from pathlib import Path

from database.models import db


logger = logging.getLogger(__name__)


class AssetGarbageCollector:
    """
    Garbage Collector для автоматической очистки истекших ассетов
    
    Функции:
    - Удаление файлов по expires_at
    - Очистка старых job записей
    - Логирование удаленных файлов
    """
    
    def __init__(self, assets_dir: str = "/home/ubuntu/rei_bot/assets"):
        self.assets_dir = Path(assets_dir)
        self.stats = {
            "files_deleted": 0,
            "bytes_freed": 0,
            "jobs_cleaned": 0,
            "errors": 0
        }
    
    async def run_gc_cycle(self):
        """
        Запустить цикл GC
        
        1. Найти истекшие job
        2. Удалить связанные файлы
        3. Обновить статус job
        4. Логировать результаты
        """
        logger.info("🗑️ Starting GC cycle...")
        
        try:
            # 1. Найти истекшие job
            expired_jobs = await db.get_expired_jobs()
            
            if not expired_jobs:
                logger.info("✅ No expired jobs found")
                return
            
            logger.info(f"Found {len(expired_jobs)} expired jobs")
            
            # 2. Обработать каждый job
            for job in expired_jobs:
                await self._cleanup_job(job)
            
            # 3. Логировать статистику
            logger.info(
                f"🗑️ GC cycle completed: "
                f"files_deleted={self.stats['files_deleted']}, "
                f"bytes_freed={self.stats['bytes_freed']}, "
                f"jobs_cleaned={self.stats['jobs_cleaned']}, "
                f"errors={self.stats['errors']}"
            )
            
            # Сбросить статистику
            self.stats = {
                "files_deleted": 0,
                "bytes_freed": 0,
                "jobs_cleaned": 0,
                "errors": 0
            }
        
        except Exception as e:
            logger.error(f"❌ GC cycle failed: {e}", exc_info=True)
    
    async def _cleanup_job(self, job: dict):
        """
        Очистить файлы связанные с job
        
        Args:
            job: Запись job из БД
        """
        try:
            job_id = job['id']
            result_path = job.get('result_path')
            
            # Удалить файл результата
            if result_path and os.path.exists(result_path):
                file_size = os.path.getsize(result_path)
                os.remove(result_path)
                
                self.stats['files_deleted'] += 1
                self.stats['bytes_freed'] += file_size
                
                logger.info(f"🗑️ Deleted file: {result_path} ({file_size} bytes)")
            
            # Обновить статус job
            await db.update_job_status(job_id, 'expired', progress=100)
            self.stats['jobs_cleaned'] += 1
            
            logger.info(f"✅ Cleaned job {job_id}")
        
        except Exception as e:
            logger.error(f"❌ Failed to cleanup job {job.get('id')}: {e}")
            self.stats['errors'] += 1
    
    async def cleanup_old_jobs(self, days: int = 30):
        """
        Очистить старые завершенные job
        
        Args:
            days: Удалить job старше N дней
        """
        try:
            cutoff_date = datetime.now() - timedelta(days=days)
            
            # Получить старые job
            old_jobs = await db.get_jobs_before_date(cutoff_date)
            
            if not old_jobs:
                logger.info(f"✅ No old jobs found (older than {days} days)")
                return
            
            logger.info(f"Found {len(old_jobs)} old jobs to cleanup")
            
            # Удалить файлы и записи
            for job in old_jobs:
                await self._cleanup_job(job)
                await db.delete_job(job['id'])
            
            logger.info(f"🗑️ Cleaned {len(old_jobs)} old jobs")
        
        except Exception as e:
            logger.error(f"❌ Failed to cleanup old jobs: {e}", exc_info=True)
    
    async def cleanup_orphaned_files(self):
        """
        Очистить файлы без связанных job (orphaned files)
        """
        try:
            if not self.assets_dir.exists():
                logger.warning(f"Assets directory not found: {self.assets_dir}")
                return
            
            # Получить все job с файлами
            jobs_with_files = await db.get_jobs_with_files()
            valid_paths = {job['result_path'] for job in jobs_with_files if job.get('result_path')}
            
            # Найти orphaned files
            orphaned_count = 0
            orphaned_size = 0
            
            for file_path in self.assets_dir.rglob("*"):
                if file_path.is_file():
                    file_path_str = str(file_path)
                    
                    if file_path_str not in valid_paths:
                        file_size = file_path.stat().st_size
                        file_path.unlink()
                        
                        orphaned_count += 1
                        orphaned_size += file_size
                        
                        logger.info(f"🗑️ Deleted orphaned file: {file_path_str}")
            
            if orphaned_count > 0:
                logger.info(
                    f"🗑️ Cleaned {orphaned_count} orphaned files "
                    f"({orphaned_size} bytes)"
                )
            else:
                logger.info("✅ No orphaned files found")
        
        except Exception as e:
            logger.error(f"❌ Failed to cleanup orphaned files: {e}", exc_info=True)


# Глобальный экземпляр GC
gc = AssetGarbageCollector()


async def run_gc_worker(interval_hours: int = 6):
    """
    Запустить GC worker в бесконечном цикле
    
    Args:
        interval_hours: Интервал между циклами GC (в часах)
    """
    logger.info(f"🗑️ GC Worker started (interval: {interval_hours} hours)")
    
    while True:
        try:
            # Запустить GC цикл
            await gc.run_gc_cycle()
            
            # Очистить старые job (30 дней)
            await gc.cleanup_old_jobs(days=30)
            
            # Очистить orphaned files
            await gc.cleanup_orphaned_files()
            
            # Подождать до следующего цикла
            await asyncio.sleep(interval_hours * 3600)
        
        except Exception as e:
            logger.error(f"❌ GC Worker error: {e}", exc_info=True)
            # Подождать 1 час перед повторной попыткой
            await asyncio.sleep(3600)


if __name__ == "__main__":
    # Запустить GC worker standalone
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    asyncio.run(run_gc_worker(interval_hours=6))

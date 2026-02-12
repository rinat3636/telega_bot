"""
Бизнес-метрики и алерты
Решение F-305: observability для критичных событий
"""
import logging
from typing import Dict, Optional
from datetime import datetime
from collections import defaultdict
import asyncio


logger = logging.getLogger(__name__)


class MetricsCollector:
    """
    Сборщик бизнес-метрик
    
    Метрики:
    - ledger_negative_attempts: Попытки уйти в минус
    - jobs_failed: Провалы генерации
    - payment_webhook_errors: Ошибки webhook
    - queue_length: Длина очереди
    - provider_errors: Ошибки AI провайдеров
    """
    
    def __init__(self):
        self.counters: Dict[str, int] = defaultdict(int)
        self.gauges: Dict[str, float] = {}
        self.histograms: Dict[str, list] = defaultdict(list)
        
        # Пороги для алертов
        self.alert_thresholds = {
            'ledger_negative_attempts': 1,  # Критично: любая попытка
            'queue_length': 100,  # Warning: очередь > 100
            'provider_error_rate': 0.1,  # Warning: > 10% ошибок
            'payment_webhook_errors': 5,  # Warning: > 5 ошибок за период
        }
    
    # ==================== COUNTERS ====================
    
    def inc_counter(self, name: str, value: int = 1, labels: Optional[Dict] = None):
        """
        Увеличить счетчик
        
        Args:
            name: Имя метрики
            value: Значение для увеличения
            labels: Метки (например, {"provider": "nano_banana"})
        """
        key = self._make_key(name, labels)
        self.counters[key] += value
        
        # Проверить алерты
        self._check_alert(name, self.counters[key])
        
        logger.debug(f"📊 Counter {key} = {self.counters[key]}")
    
    def get_counter(self, name: str, labels: Optional[Dict] = None) -> int:
        """Получить значение счетчика"""
        key = self._make_key(name, labels)
        return self.counters.get(key, 0)
    
    # ==================== GAUGES ====================
    
    def set_gauge(self, name: str, value: float, labels: Optional[Dict] = None):
        """
        Установить gauge (текущее значение)
        
        Args:
            name: Имя метрики
            value: Текущее значение
            labels: Метки
        """
        key = self._make_key(name, labels)
        self.gauges[key] = value
        
        # Проверить алерты
        self._check_alert(name, value)
        
        logger.debug(f"📊 Gauge {key} = {value}")
    
    def get_gauge(self, name: str, labels: Optional[Dict] = None) -> Optional[float]:
        """Получить значение gauge"""
        key = self._make_key(name, labels)
        return self.gauges.get(key)
    
    # ==================== HISTOGRAMS ====================
    
    def observe(self, name: str, value: float, labels: Optional[Dict] = None):
        """
        Добавить наблюдение в histogram
        
        Args:
            name: Имя метрики
            value: Наблюдаемое значение
            labels: Метки
        """
        key = self._make_key(name, labels)
        self.histograms[key].append(value)
        
        logger.debug(f"📊 Histogram {key} observed {value}")
    
    def get_histogram_stats(self, name: str, labels: Optional[Dict] = None) -> Dict:
        """
        Получить статистику histogram
        
        Returns:
            {"count": int, "sum": float, "avg": float, "min": float, "max": float}
        """
        key = self._make_key(name, labels)
        values = self.histograms.get(key, [])
        
        if not values:
            return {"count": 0, "sum": 0, "avg": 0, "min": 0, "max": 0}
        
        return {
            "count": len(values),
            "sum": sum(values),
            "avg": sum(values) / len(values),
            "min": min(values),
            "max": max(values)
        }
    
    # ==================== ALERTS ====================
    
    def _check_alert(self, name: str, value: float):
        """
        Проверить пороги алертов
        
        Args:
            name: Имя метрики
            value: Текущее значение
        """
        threshold = self.alert_thresholds.get(name)
        
        if threshold is None:
            return
        
        if value >= threshold:
            self._fire_alert(name, value, threshold)
    
    def _fire_alert(self, name: str, value: float, threshold: float):
        """
        Сработать алерт
        
        Args:
            name: Имя метрики
            value: Текущее значение
            threshold: Порог
        """
        severity = "CRITICAL" if name == "ledger_negative_attempts" else "WARNING"
        
        logger.warning(
            f"🚨 [{severity}] Alert: {name} = {value} (threshold: {threshold})"
        )
        
        # TODO: Интеграция с внешними системами алертинга (Telegram, Slack, PagerDuty)
    
    # ==================== UTILITIES ====================
    
    def _make_key(self, name: str, labels: Optional[Dict] = None) -> str:
        """
        Создать ключ метрики с метками
        
        Args:
            name: Имя метрики
            labels: Метки
        
        Returns:
            "metric_name{label1=value1,label2=value2}"
        """
        if not labels:
            return name
        
        labels_str = ",".join(f"{k}={v}" for k, v in sorted(labels.items()))
        return f"{name}{{{labels_str}}}"
    
    def reset(self):
        """Сбросить все метрики"""
        self.counters.clear()
        self.gauges.clear()
        self.histograms.clear()
        logger.info("📊 Metrics reset")
    
    def get_all_metrics(self) -> Dict:
        """
        Получить все метрики
        
        Returns:
            {"counters": {...}, "gauges": {...}, "histograms": {...}}
        """
        # Вычислить статистику напрямую из сохраненных значений
        histograms_stats = {}
        for key, values in self.histograms.items():
            if values:
                sorted_values = sorted(values)
                count = len(sorted_values)
                histograms_stats[key] = {
                    "count": count,
                    "sum": sum(sorted_values),
                    "min": sorted_values[0],
                    "max": sorted_values[-1],
                    "mean": sum(sorted_values) / count,
                    "p50": sorted_values[int(count * 0.5)],
                    "p95": sorted_values[int(count * 0.95)] if count > 1 else sorted_values[0],
                    "p99": sorted_values[int(count * 0.99)] if count > 1 else sorted_values[0]
                }
            else:
                histograms_stats[key] = {
                    "count": 0,
                    "sum": 0,
                    "min": 0,
                    "max": 0,
                    "mean": 0,
                    "p50": 0,
                    "p95": 0,
                    "p99": 0
                }
        
        return {
            "counters": dict(self.counters),
            "gauges": dict(self.gauges),
            "histograms": histograms_stats
        }


# Глобальный экземпляр metrics collector
metrics = MetricsCollector()


# ==================== HELPER FUNCTIONS ====================

def track_ledger_negative_attempt(user_id: int, amount: float):
    """Отследить попытку уйти в минус"""
    metrics.inc_counter('ledger_negative_attempts', labels={"user_id": str(user_id)})
    logger.error(f"🚨 CRITICAL: User {user_id} attempted negative balance (amount: {amount})")


def track_job_failed(job_id: int, job_type: str, reason: str):
    """Отследить провал job"""
    metrics.inc_counter('jobs_failed', labels={"type": job_type})
    logger.warning(f"⚠️ Job {job_id} failed: {reason}")


def track_payment_webhook_error(error: str):
    """Отследить ошибку webhook"""
    metrics.inc_counter('payment_webhook_errors')
    logger.error(f"🚨 Payment webhook error: {error}")


def track_queue_length(length: int):
    """Отследить длину очереди"""
    metrics.set_gauge('queue_length', length)


def track_provider_error(provider: str, error: str):
    """Отследить ошибку AI провайдера"""
    metrics.inc_counter('provider_errors', labels={"provider": provider})
    logger.warning(f"⚠️ Provider {provider} error: {error}")


def track_job_duration(job_type: str, duration_seconds: float):
    """Отследить длительность job"""
    metrics.observe('job_duration_seconds', duration_seconds, labels={"type": job_type})


def track_balance_operation(operation_type: str, amount: float):
    """Отследить операцию с балансом"""
    metrics.inc_counter('balance_operations', labels={"type": operation_type})
    metrics.observe('balance_operation_amount', amount, labels={"type": operation_type})


async def metrics_reporter(interval_seconds: int = 60):
    """
    Периодически логировать метрики
    
    Args:
        interval_seconds: Интервал между отчетами
    """
    logger.info(f"📊 Metrics reporter started (interval: {interval_seconds}s)")
    
    while True:
        try:
            await asyncio.sleep(interval_seconds)
            
            all_metrics = metrics.get_all_metrics()
            
            logger.info(
                f"📊 Metrics Report:\n"
                f"Counters: {all_metrics['counters']}\n"
                f"Gauges: {all_metrics['gauges']}\n"
                f"Histograms: {all_metrics['histograms']}"
            )
        
        except Exception as e:
            logger.error(f"❌ Metrics reporter error: {e}", exc_info=True)


# ==================== DECORATOR ====================

def track_execution_time(metric_name: str, labels: Optional[Dict] = None):
    """
    Декоратор для отслеживания времени выполнения
    
    Usage:
        @track_execution_time("image_generation_duration", {"provider": "nano_banana"})
        async def generate_image(...):
            ...
    """
    def decorator(func):
        async def wrapper(*args, **kwargs):
            start_time = datetime.now()
            try:
                result = await func(*args, **kwargs)
                return result
            finally:
                duration = (datetime.now() - start_time).total_seconds()
                metrics.observe(metric_name, duration, labels)
        return wrapper
    return decorator

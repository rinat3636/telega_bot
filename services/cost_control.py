"""
Cost Control: Cost-caps и auto-stop при low balance
Защита от перерасхода и автоматическая остановка при недостатке средств
"""
import logging
from typing import Optional, Tuple
from datetime import datetime, timedelta

from database.models import db
from services.metrics import metrics, track_balance_operation


logger = logging.getLogger(__name__)


class CostController:
    """
    Контроллер стоимости для защиты от перерасхода
    
    Функции:
    - Cost-caps (₽/день, ₽/час)
    - Auto-stop job при low balance
    - Уведомления пользователям
    """
    
    def __init__(
        self,
        daily_limit: float = 5000.0,
        hourly_limit: float = 1000.0,
        min_balance_threshold: float = 10.0
    ):
        """
        Args:
            daily_limit: Лимит расходов в день (₽)
            hourly_limit: Лимит расходов в час (₽)
            min_balance_threshold: Минимальный баланс для продолжения (₽)
        """
        self.daily_limit = daily_limit
        self.hourly_limit = hourly_limit
        self.min_balance_threshold = min_balance_threshold
    
    async def check_cost_cap(
        self,
        user_id: int,
        cost: float
    ) -> Tuple[bool, str]:
        """
        Проверить cost-cap перед созданием job
        
        Args:
            user_id: ID пользователя
            cost: Стоимость операции
        
        Returns:
            (allowed, message): (разрешено ли, сообщение об ошибке)
        """
        # 1. Проверить дневной лимит
        daily_spent = await self._get_spent_amount(user_id, hours=24)
        
        if daily_spent + cost > self.daily_limit:
            remaining = self.daily_limit - daily_spent
            logger.warning(
                f"⚠️ User {user_id} exceeded daily limit: "
                f"spent={daily_spent}, limit={self.daily_limit}"
            )
            metrics.inc_counter('cost_cap_daily_exceeded', labels={"user_id": str(user_id)})
            
            return False, (
                f"⚠️ Превышен дневной лимит расходов!\n\n"
                f"Потрачено сегодня: {daily_spent:.2f} ₽\n"
                f"Дневной лимит: {self.daily_limit:.2f} ₽\n"
                f"Осталось: {remaining:.2f} ₽\n\n"
                f"Попробуйте завтра или обратитесь к администратору."
            )
        
        # 2. Проверить часовой лимит
        hourly_spent = await self._get_spent_amount(user_id, hours=1)
        
        if hourly_spent + cost > self.hourly_limit:
            remaining = self.hourly_limit - hourly_spent
            logger.warning(
                f"⚠️ User {user_id} exceeded hourly limit: "
                f"spent={hourly_spent}, limit={self.hourly_limit}"
            )
            metrics.inc_counter('cost_cap_hourly_exceeded', labels={"user_id": str(user_id)})
            
            return False, (
                f"⚠️ Превышен часовой лимит расходов!\n\n"
                f"Потрачено за последний час: {hourly_spent:.2f} ₽\n"
                f"Часовой лимит: {self.hourly_limit:.2f} ₽\n"
                f"Осталось: {remaining:.2f} ₽\n\n"
                f"Подождите немного и попробуйте снова."
            )
        
        return True, ""
    
    async def check_balance_threshold(
        self,
        user_id: int,
        cost: float
    ) -> Tuple[bool, str]:
        """
        Проверить минимальный баланс
        
        Args:
            user_id: ID пользователя
            cost: Стоимость операции
        
        Returns:
            (allowed, message): (разрешено ли, сообщение об ошибке)
        """
        balance = await db.get_balance(user_id)
        
        # Проверить, что после операции баланс не упадет ниже порога
        if balance - cost < self.min_balance_threshold:
            logger.warning(
                f"⚠️ User {user_id} balance too low: "
                f"balance={balance}, cost={cost}, threshold={self.min_balance_threshold}"
            )
            metrics.inc_counter('balance_threshold_hit', labels={"user_id": str(user_id)})
            
            return False, (
                f"⚠️ Недостаточно средств!\n\n"
                f"Ваш баланс: {balance:.2f} ₽\n"
                f"Стоимость операции: {cost:.2f} ₽\n"
                f"Минимальный остаток: {self.min_balance_threshold:.2f} ₽\n\n"
                f"Пополните баланс командой /pay"
            )
        
        return True, ""
    
    async def should_auto_stop_job(
        self,
        user_id: int,
        job_id: int,
        current_cost: float
    ) -> Tuple[bool, str]:
        """
        Проверить, нужно ли автоматически остановить job
        
        Args:
            user_id: ID пользователя
            job_id: ID задачи
            current_cost: Текущая стоимость
        
        Returns:
            (should_stop, reason): (нужно ли остановить, причина)
        """
        balance = await db.get_balance(user_id)
        
        # Если баланс упал ниже порога - остановить
        if balance < self.min_balance_threshold:
            logger.warning(
                f"🛑 Auto-stopping job {job_id} for user {user_id}: "
                f"balance={balance}, threshold={self.min_balance_threshold}"
            )
            metrics.inc_counter('jobs_auto_stopped', labels={"reason": "low_balance"})
            
            return True, (
                f"⚠️ Задача автоматически остановлена!\n\n"
                f"Причина: недостаточно средств на балансе.\n"
                f"Ваш баланс: {balance:.2f} ₽\n"
                f"Минимальный остаток: {self.min_balance_threshold:.2f} ₽\n\n"
                f"Пополните баланс командой /pay для продолжения."
            )
        
        # Проверить дневной лимит
        daily_spent = await self._get_spent_amount(user_id, hours=24)
        
        if daily_spent >= self.daily_limit:
            logger.warning(
                f"🛑 Auto-stopping job {job_id} for user {user_id}: "
                f"daily limit exceeded ({daily_spent}/{self.daily_limit})"
            )
            metrics.inc_counter('jobs_auto_stopped', labels={"reason": "daily_limit"})
            
            return True, (
                f"⚠️ Задача автоматически остановлена!\n\n"
                f"Причина: превышен дневной лимит расходов.\n"
                f"Потрачено сегодня: {daily_spent:.2f} ₽\n"
                f"Дневной лимит: {self.daily_limit:.2f} ₽\n\n"
                f"Попробуйте завтра."
            )
        
        return False, ""
    
    async def _get_spent_amount(self, user_id: int, hours: int) -> float:
        """
        Получить сумму расходов за последние N часов
        
        Args:
            user_id: ID пользователя
            hours: Количество часов
        
        Returns:
            Сумма расходов (₽)
        """
        cutoff_time = datetime.now() - timedelta(hours=hours)
        cutoff_str = cutoff_time.isoformat()
        
        # Получить все debit операции за период
        ledger_entries = await db.get_ledger_entries(user_id)
        
        total_spent = 0.0
        for entry in ledger_entries:
            if entry['type'] == 'debit' and entry['created_at'] >= cutoff_str:
                # debit имеет отрицательную сумму, берем abs
                total_spent += abs(entry['amount'])
        
        return total_spent
    
    async def get_spending_stats(self, user_id: int) -> dict:
        """
        Получить статистику расходов пользователя
        
        Returns:
            {
                "hourly_spent": float,
                "daily_spent": float,
                "hourly_limit": float,
                "daily_limit": float,
                "balance": float
            }
        """
        hourly_spent = await self._get_spent_amount(user_id, hours=1)
        daily_spent = await self._get_spent_amount(user_id, hours=24)
        balance = await db.get_balance(user_id)
        
        return {
            "hourly_spent": hourly_spent,
            "daily_spent": daily_spent,
            "hourly_limit": self.hourly_limit,
            "daily_limit": self.daily_limit,
            "hourly_remaining": max(0, self.hourly_limit - hourly_spent),
            "daily_remaining": max(0, self.daily_limit - daily_spent),
            "balance": balance
        }


# Глобальный экземпляр cost controller
cost_controller: Optional[CostController] = None


def init_cost_controller(
    daily_limit: float = 5000.0,
    hourly_limit: float = 1000.0,
    min_balance_threshold: float = 10.0
):
    """
    Инициализировать глобальный cost controller
    
    Args:
        daily_limit: Лимит расходов в день (₽)
        hourly_limit: Лимит расходов в час (₽)
        min_balance_threshold: Минимальный баланс (₽)
    """
    global cost_controller
    cost_controller = CostController(daily_limit, hourly_limit, min_balance_threshold)
    logger.info(
        f"Cost controller initialized: "
        f"daily_limit={daily_limit}, hourly_limit={hourly_limit}, "
        f"min_balance_threshold={min_balance_threshold}"
    )


def get_cost_controller() -> CostController:
    """Получить глобальный cost controller"""
    if cost_controller is None:
        raise RuntimeError("Cost controller not initialized. Call init_cost_controller() first.")
    return cost_controller

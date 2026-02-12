"""
Модели базы данных с ledger-based балансом и защитой от гонок
"""
import aiosqlite
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any
import config
import json

logger = logging.getLogger(__name__)


class Database:
    def __init__(self, db_path: str = config.DATABASE_PATH):
        self.db_path = db_path
    
    async def init_db(self):
        """Инициализация базы данных"""
        async with aiosqlite.connect(self.db_path) as db:
            # Таблица пользователей (БЕЗ balance!)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    tg_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    created_at TEXT NOT NULL,
                    is_banned INTEGER DEFAULT 0
                )
            """)
            
            # Ledger - источник истины для баланса (с инвариантами)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS ledger (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    type TEXT NOT NULL CHECK(type IN ('credit', 'debit', 'refund')),
                    amount REAL NOT NULL CHECK(amount != 0),
                    ref_type TEXT,
                    ref_id TEXT,
                    description TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES users (tg_id),
                    UNIQUE(user_id, ref_type, ref_id)
                )
            """)
            
            await db.execute("CREATE INDEX IF NOT EXISTS idx_ledger_user ON ledger(user_id)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_ledger_created ON ledger(created_at)")
            
            # Таблица задач (расширенная с deadline/cancel/retry)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    type TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('pending', 'processing', 'completed', 'failed', 'cancelled')),
                    progress INTEGER DEFAULT 0,
                    params TEXT,
                    result_url TEXT,
                    error_message TEXT,
                    cost_estimate REAL,
                    cost_actual REAL,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    expires_at TEXT,
                    max_runtime INTEGER DEFAULT 300,
                    retry_count INTEGER DEFAULT 0,
                    max_retries INTEGER DEFAULT 3,
                    cancelled_by INTEGER,
                    cancel_reason TEXT,
                    FOREIGN KEY (user_id) REFERENCES users (tg_id)
                )
            """)
            
            await db.execute("CREATE INDEX IF NOT EXISTS idx_jobs_user ON jobs(user_id)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_jobs_expires ON jobs(expires_at)")
            
            # Таблица платежей (с уникальным provider_payment_id)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS payments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    provider_payment_id TEXT UNIQUE NOT NULL,
                    user_id INTEGER NOT NULL,
                    amount REAL NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    confirmation_url TEXT,
                    created_at TEXT NOT NULL,
                    paid_at TEXT,
                    expires_at TEXT,
                    FOREIGN KEY (user_id) REFERENCES users (tg_id)
                )
            """)
            
            await db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_payments_provider_id ON payments(provider_payment_id)")
            
            # Таблица usage_sessions для отслеживания ₽/сек (F-302)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS usage_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    started_at TEXT NOT NULL,
                    ended_at TEXT,
                    billed_seconds INTEGER DEFAULT 0,
                    amount REAL DEFAULT 0,
                    ledger_ref_id TEXT,
                    FOREIGN KEY (job_id) REFERENCES jobs (id),
                    FOREIGN KEY (user_id) REFERENCES users (tg_id)
                )
            """)
            
            await db.execute("CREATE INDEX IF NOT EXISTS idx_usage_sessions_job ON usage_sessions(job_id)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_usage_sessions_user ON usage_sessions(user_id)")
            
            # Materialized balance view cache (QA-2)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS user_balance_cache (
                    user_id INTEGER PRIMARY KEY,
                    balance REAL NOT NULL DEFAULT 0,
                    last_updated TEXT NOT NULL,
                    ledger_count INTEGER NOT NULL DEFAULT 0,
                    FOREIGN KEY (user_id) REFERENCES users (tg_id)
                )
            """)
            
            await db.execute("CREATE INDEX IF NOT EXISTS idx_balance_cache_updated ON user_balance_cache(last_updated)")
            
            # Trigger: автоматическое обновление кэша при INSERT
            await db.execute("""
                CREATE TRIGGER IF NOT EXISTS update_balance_cache_on_ledger_insert
                AFTER INSERT ON ledger
                BEGIN
                    INSERT OR REPLACE INTO user_balance_cache (user_id, balance, last_updated, ledger_count)
                    SELECT 
                        NEW.user_id,
                        COALESCE((SELECT SUM(amount) FROM ledger WHERE user_id = NEW.user_id), 0),
                        datetime('now'),
                        (SELECT COUNT(*) FROM ledger WHERE user_id = NEW.user_id)
                    ;
                END;
            """)
            
            # Trigger: автоматическое обновление кэша при UPDATE
            await db.execute("""
                CREATE TRIGGER IF NOT EXISTS update_balance_cache_on_ledger_update
                AFTER UPDATE ON ledger
                BEGIN
                    -- Обновить кэш для NEW.user_id
                    INSERT OR REPLACE INTO user_balance_cache (user_id, balance, last_updated, ledger_count)
                    SELECT 
                        NEW.user_id,
                        COALESCE((SELECT SUM(amount) FROM ledger WHERE user_id = NEW.user_id), 0),
                        datetime('now'),
                        (SELECT COUNT(*) FROM ledger WHERE user_id = NEW.user_id)
                    ;
                    -- Если user_id изменился, обновить кэш для OLD.user_id
                    INSERT OR REPLACE INTO user_balance_cache (user_id, balance, last_updated, ledger_count)
                    SELECT 
                        OLD.user_id,
                        COALESCE((SELECT SUM(amount) FROM ledger WHERE user_id = OLD.user_id), 0),
                        datetime('now'),
                        (SELECT COUNT(*) FROM ledger WHERE user_id = OLD.user_id)
                    WHERE OLD.user_id != NEW.user_id;
                END;
            """)
            
            # Trigger: автоматическое обновление кэша при DELETE
            await db.execute("""
                CREATE TRIGGER IF NOT EXISTS update_balance_cache_on_ledger_delete
                AFTER DELETE ON ledger
                BEGIN
                    INSERT OR REPLACE INTO user_balance_cache (user_id, balance, last_updated, ledger_count)
                    SELECT 
                        OLD.user_id,
                        COALESCE((SELECT SUM(amount) FROM ledger WHERE user_id = OLD.user_id), 0),
                        datetime('now'),
                        (SELECT COUNT(*) FROM ledger WHERE user_id = OLD.user_id)
                    ;
                END;
            """)
            
            # Таблица webhook events для deduplication
            await db.execute("""
                CREATE TABLE IF NOT EXISTS webhook_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    webhook_id TEXT UNIQUE NOT NULL,
                    processed_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                )
            """)
            
            await db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_webhook_id ON webhook_events(webhook_id)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_webhook_expires ON webhook_events(expires_at)")
            
            # Таблица цен для админ-управления (F-207)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS pricing (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    provider TEXT NOT NULL,
                    model TEXT,
                    action TEXT,
                    price_rub REAL NOT NULL CHECK(price_rub >= 0),
                    updated_at TEXT NOT NULL,
                    updated_by INTEGER,
                    UNIQUE(provider, model, action),
                    FOREIGN KEY (updated_by) REFERENCES users (tg_id)
                )
            """)
            
            await db.execute("CREATE INDEX IF NOT EXISTS idx_pricing_provider ON pricing(provider)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_pricing_model ON pricing(model)")
            
            # Миграция: перенести данные из старой wallets в ledger
            await self._migrate_wallets_to_ledger(db)
            
            await db.commit()
    
    async def _migrate_wallets_to_ledger(self, db):
        """Миграция данных из wallets в ledger"""
        # Проверить, существует ли таблица wallets
        async with db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='wallets'"
        ) as cursor:
            if not await cursor.fetchone():
                return  # Таблица не существует, миграция не нужна
        
        # Перенести балансы в ledger
        async with db.execute("SELECT user_id, balance FROM wallets WHERE balance > 0") as cursor:
            wallets = await cursor.fetchall()
        
        for user_id, balance in wallets:
            # Проверить, есть ли уже записи в ledger для этого пользователя
            async with db.execute(
                "SELECT COUNT(*) FROM ledger WHERE user_id = ?", (user_id,)
            ) as cursor:
                count = (await cursor.fetchone())[0]
            
            if count == 0:  # Только если еще нет записей
                await db.execute(
                    """
                    INSERT INTO ledger (user_id, type, amount, ref_type, ref_id, description, created_at)
                    VALUES (?, 'credit', ?, 'migration', 'initial', 'Миграция из wallets', ?)
                    """,
                    (user_id, balance, datetime.now().isoformat())
                )
        
        # Удалить таблицу wallets (опционально, можно оставить для истории)
        # await db.execute("DROP TABLE IF EXISTS wallets")
    
    # ==================== ПОЛЬЗОВАТЕЛИ ====================
    
    async def get_or_create_user(self, tg_id: int, username: str = None, first_name: str = None) -> Dict[str, Any]:
        """Получить или создать пользователя"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            
            # Проверяем существование пользователя
            async with db.execute("SELECT * FROM users WHERE tg_id = ?", (tg_id,)) as cursor:
                user = await cursor.fetchone()
            
            if user:
                return dict(user)
            
            # Создаем нового пользователя
            created_at = datetime.now().isoformat()
            await db.execute(
                "INSERT INTO users (tg_id, username, first_name, created_at, is_banned) VALUES (?, ?, ?, ?, 0)",
                (tg_id, username, first_name, created_at)
            )
            
            await db.commit()
            
            return {
                "tg_id": tg_id,
                "username": username,
                "first_name": first_name,
                "created_at": created_at,
                "is_banned": 0
            }
    
    async def is_banned(self, tg_id: int) -> bool:
        """Проверить, забанен ли пользователь"""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT is_banned FROM users WHERE tg_id = ?",
                (tg_id,)
            ) as cursor:
                row = await cursor.fetchone()
                return bool(row[0]) if row else False
    
    async def ban_user(self, tg_id: int):
        """Забанить пользователя"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE users SET is_banned = 1 WHERE tg_id = ?",
                (tg_id,)
            )
            await db.commit()
    
    # ==================== LEDGER (БАЛАНС) ====================
    
    async def add_ledger_entry(
        self,
        user_id: int,
        entry_type: str,
        amount: float,
        ref_type: str = None,
        ref_id: str = None,
        description: str = None
    ) -> int:
        """
        Добавить запись в ledger
        
        Args:
            user_id: ID пользователя
            entry_type: Тип операции ('credit', 'debit', 'refund')
            amount: Сумма (положительная для credit/refund, отрицательная для debit)
            ref_type: Тип ссылки ('payment', 'job', 'admin', 'reservation')
            ref_id: ID связанной сущности
            description: Описание операции
        
        Returns:
            ID созданной записи
        """
        async with aiosqlite.connect(self.db_path) as db:
            created_at = datetime.now().isoformat()
            cursor = await db.execute(
                """
                INSERT INTO ledger (user_id, type, amount, ref_type, ref_id, description, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (user_id, entry_type, amount, ref_type, ref_id, description, created_at)
            )
            await db.commit()
            return cursor.lastrowid
    
    async def get_balance(self, tg_id: int, db: Optional[aiosqlite.Connection] = None) -> float:
        """
        Получить баланс пользователя (SUM из ledger)
        
        Args:
            tg_id: Telegram ID пользователя
            db: Опциональное существующее соединение (для атомарности)
        """
        if db is not None:
            # Используем существующее соединение (внутри транзакции)
            async with db.execute(
                "SELECT COALESCE(SUM(amount), 0) FROM ledger WHERE user_id = ?",
                (tg_id,)
            ) as cursor:
                row = await cursor.fetchone()
                return float(row[0]) if row else 0.0
        else:
            # Создаем новое соединение
            async with aiosqlite.connect(self.db_path) as db:
                async with db.execute(
                    "SELECT COALESCE(SUM(amount), 0) FROM ledger WHERE user_id = ?",
                    (tg_id,)
                ) as cursor:
                    row = await cursor.fetchone()
                    return float(row[0]) if row else 0.0
    
    async def get_ledger_history(self, tg_id: int, limit: int = 50) -> List[Dict[str, Any]]:
        """Получить историю операций пользователя"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT * FROM ledger
                WHERE user_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (tg_id, limit)
            ) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]
    
    async def reserve_balance(self, user_id: int, amount: float, ref_id: str) -> bool:
        """
        Зарезервировать баланс для задачи (атомарно)
        
        Returns:
            True если успешно, False если недостаточно средств
        """
        async with aiosqlite.connect(self.db_path) as db:
            # BEGIN IMMEDIATE для блокировки
            await db.execute("BEGIN IMMEDIATE")
            
            try:
                # Используем то же соединение для проверки баланса (атомарность)
                balance = await self.get_balance(user_id, db=db)
                
                if balance < amount:
                    await db.rollback()
                    return False
                
                # Создать запись резервирования
                await db.execute(
                    """
                    INSERT INTO ledger (user_id, type, amount, ref_type, ref_id, description, created_at)
                    VALUES (?, 'debit', ?, 'reservation', ?, 'Резервирование средств', ?)
                    """,
                    (user_id, -amount, ref_id, datetime.now().isoformat())
                )
                
                await db.commit()
                return True
            except Exception as e:
                await db.rollback()
                raise e
    
    async def charge_reserved_balance(self, user_id: int, ref_id: str, actual_amount: float, new_ref_id: str):
        """
        Списать зарезервированные средства и согласовать с actual_amount
        
        Args:
            user_id: ID пользователя
            ref_id: ID резервации
            actual_amount: Фактическая стоимость
            new_ref_id: Новый ref_id (для job)
        """
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            
            try:
                # Получить зарезервированную сумму
                async with db.execute(
                    """
                    SELECT amount FROM ledger
                    WHERE user_id = ? AND ref_type = 'reservation' AND ref_id = ?
                    """,
                    (user_id, ref_id)
                ) as cursor:
                    row = await cursor.fetchone()
                    
                    if not row:
                        # ИДЕМПОТЕНТНОСТЬ: Проверить, не обработано ли уже
                        async with db.execute(
                            """
                            SELECT amount FROM ledger
                            WHERE user_id = ? AND ref_type = 'job' AND ref_id = ?
                            """,
                            (user_id, new_ref_id)
                        ) as job_cursor:
                            job_row = await job_cursor.fetchone()
                            if job_row:
                                # Job уже создан - возвращаем успех (идемпотентность)
                                logger.info(f"Job {new_ref_id} already processed (idempotent)")
                                await db.rollback()
                                return
                            else:
                                # Reservation не найдена и job не создан - ошибка
                                raise ValueError(f"Reservation {ref_id} not found and job {new_ref_id} not created")
                    
                    reserved_amount = abs(float(row[0]))  # amount отрицательный
                
                # Обновить запись резервирования
                await db.execute(
                    """
                    UPDATE ledger
                    SET ref_type = 'job', ref_id = ?, amount = ?, description = 'Списание за задачу'
                    WHERE user_id = ? AND ref_type = 'reservation' AND ref_id = ?
                    """,
                    (new_ref_id, -actual_amount, user_id, ref_id)
                )
                
                # Если есть разница, создать компенсирующую запись
                delta = reserved_amount - actual_amount
                if abs(delta) > 0.01:  # Игнорируем округления
                    try:
                        await db.execute(
                            """
                            INSERT INTO ledger (user_id, type, amount, ref_type, ref_id, description, created_at)
                            VALUES (?, 'refund', ?, 'reconciliation', ?, 'Корректировка резерва', ?)
                            """,
                            (user_id, delta, f"{new_ref_id}_reconcile", datetime.now().isoformat())
                        )
                    except Exception as reconcile_error:
                        # ИДЕМПОТЕНТНОСТЬ: Если reconciliation уже существует (UNIQUE constraint), игнорируем
                        if "UNIQUE constraint" in str(reconcile_error):
                            logger.info(f"Reconciliation {new_ref_id}_reconcile already exists (idempotent)")
                        else:
                            raise reconcile_error
                
                await db.commit()
            except Exception as e:
                await db.rollback()
                raise e
    
    async def refund_balance(self, user_id: int, amount: float, ref_type: str, ref_id: str, description: str):
        """Вернуть средства пользователю"""
        await self.add_ledger_entry(
            user_id=user_id,
            entry_type='refund',
            amount=amount,
            ref_type=ref_type,
            ref_id=ref_id,
            description=description
        )
    
    # Для обратной совместимости
    async def add_balance(self, tg_id: int, amount: float) -> float:
        """Добавить средства на баланс (для обратной совместимости)"""
        await self.add_ledger_entry(
            user_id=tg_id,
            entry_type='credit',
            amount=amount,
            ref_type='admin',
            ref_id=None,
            description='Пополнение администратором'
        )
        return await self.get_balance(tg_id)
    
    async def subtract_balance(self, tg_id: int, amount: float) -> bool:
        """Списать средства с баланса (для обратной совместимости)"""
        balance = await self.get_balance(tg_id)
        
        if balance < amount:
            return False
        
        await self.add_ledger_entry(
            user_id=tg_id,
            entry_type='debit',
            amount=-amount,
            ref_type='admin',
            ref_id=None,
            description='Списание администратором'
        )
        return True
    
    # ==================== ЗАДАЧИ (JOBS) ====================
    
    async def create_job(
        self,
        user_id: int,
        job_type: str,
        params: Dict[str, Any],
        cost_estimate: float,
        max_runtime: int = 300,
        deadline_minutes: int = 30
    ) -> int:
        """
        Создать задачу с deadline
        
        Args:
            max_runtime: Максимальное время выполнения (секунды)
            deadline_minutes: Общий deadline задачи (минуты)
        """
        from datetime import timedelta
        async with aiosqlite.connect(self.db_path) as db:
            created_at = datetime.now()
            expires_at = created_at + timedelta(minutes=deadline_minutes)
            
            cursor = await db.execute(
                """
                INSERT INTO jobs (
                    user_id, type, status, progress, params, cost_estimate, 
                    created_at, expires_at, max_runtime
                ) VALUES (?, ?, 'pending', 0, ?, ?, ?, ?, ?)
                """,
                (user_id, job_type, json.dumps(params), cost_estimate, 
                 created_at.isoformat(), expires_at.isoformat(), max_runtime)
            )
            await db.commit()
            return cursor.lastrowid
    
    async def update_job_status(
        self,
        job_id: int,
        status: str,
        progress: int = None,
        result_url: str = None,
        error_message: str = None,
        cost_actual: float = None
    ):
        """Обновить статус задачи"""
        async with aiosqlite.connect(self.db_path) as db:
            updates = ["status = ?"]
            params = [status]
            
            if progress is not None:
                updates.append("progress = ?")
                params.append(progress)
            
            if result_url is not None:
                updates.append("result_url = ?")
                params.append(result_url)
            
            if error_message is not None:
                updates.append("error_message = ?")
                params.append(error_message)
            
            if cost_actual is not None:
                updates.append("cost_actual = ?")
                params.append(cost_actual)
            
            if status == 'processing' and not await self._job_has_started(db, job_id):
                updates.append("started_at = ?")
                params.append(datetime.now().isoformat())
            
            if status in ('completed', 'failed', 'cancelled'):
                updates.append("completed_at = ?")
                params.append(datetime.now().isoformat())
            
            params.append(job_id)
            
            await db.execute(
                f"UPDATE jobs SET {', '.join(updates)} WHERE id = ?",
                params
            )
            await db.commit()
    
    async def _job_has_started(self, db, job_id: int) -> bool:
        """Проверить, была ли задача уже запущена"""
        async with db.execute("SELECT started_at FROM jobs WHERE id = ?", (job_id,)) as cursor:
            row = await cursor.fetchone()
            return row and row[0] is not None
    
    async def get_job(self, job_id: int) -> Optional[Dict[str, Any]]:
        """Получить задачу по ID"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)) as cursor:
                row = await cursor.fetchone()
                if row:
                    job = dict(row)
                    if job.get('params'):
                        try:
                            job['params'] = json.loads(job['params'])
                        except json.JSONDecodeError as e:
                            logger.error(f"Invalid JSON in job params for job_id={job.get('id')}: {e}")
                            job['params'] = {}
                    return job
                return None
    
    async def get_user_active_jobs(self, user_id: int) -> List[Dict[str, Any]]:
        """Получить активные задачи пользователя"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT * FROM jobs
                WHERE user_id = ? AND status IN ('pending', 'processing')
                ORDER BY created_at DESC
                """,
                (user_id,)
            ) as cursor:
                rows = await cursor.fetchall()
                jobs = []
                for row in rows:
                    job = dict(row)
                    if job.get('params'):
                        job['params'] = json.loads(job['params'])
                    jobs.append(job)
                return jobs
    
    async def cancel_job(self, job_id: int, cancelled_by: int = None, reason: str = None) -> bool:
        """
        Отменить задачу
        
        Args:
            job_id: ID задачи
            cancelled_by: ID пользователя или админа
            reason: Причина отмены
        
        Returns:
            True если успешно, False если задача не найдена или уже завершена
        """
        async with aiosqlite.connect(self.db_path) as db:
            # Проверить, можно ли отменить
            async with db.execute(
                "SELECT status FROM jobs WHERE id = ?",
                (job_id,)
            ) as cursor:
                row = await cursor.fetchone()
                if not row:
                    return False
                
                status = row[0]
                if status in ('completed', 'failed', 'cancelled'):
                    return False  # Уже завершена
            
            # Отменить
            completed_at = datetime.now().isoformat()
            await db.execute(
                """
                UPDATE jobs 
                SET status = 'cancelled', 
                    cancelled_by = ?, 
                    cancel_reason = ?,
                    completed_at = ?
                WHERE id = ?
                """,
                (cancelled_by, reason, completed_at, job_id)
            )
            await db.commit()
            return True
    
    async def increment_retry_count(self, job_id: int):
        """Увеличить счетчик retry"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE jobs SET retry_count = retry_count + 1 WHERE id = ?",
                (job_id,)
            )
            await db.commit()
    
    async def get_expired_jobs(self) -> List[Dict[str, Any]]:
        """Получить задачи с истекшим deadline"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            now = datetime.now().isoformat()
            async with db.execute(
                """
                SELECT * FROM jobs
                WHERE status IN ('pending', 'processing')
                AND expires_at < ?
                """,
                (now,)
            ) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]
    
    # ==================== ПЛАТЕЖИ ====================
    
    async def create_payment(
        self,
        user_id: int,
        provider_payment_id: str,
        amount: float,
        confirmation_url: Optional[str] = None,
        status: str = "pending",
        expires_at: Optional[str] = None
    ) -> Optional[int]:
        """
        Создать запись о платеже
        
        Args:
            user_id: ID пользователя
            provider_payment_id: ID платежа от провайдера
            amount: Сумма
            confirmation_url: Ссылка на оплату
            status: Статус платежа
            expires_at: Время истечения
        
        Returns:
            ID платежа или None если уже существует
        """
        async with aiosqlite.connect(self.db_path) as db:
            try:
                created_at = datetime.now().isoformat()
                cursor = await db.execute(
                    """
                    INSERT INTO payments (provider_payment_id, user_id, amount, status, confirmation_url, created_at, expires_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (provider_payment_id, user_id, amount, status, confirmation_url, created_at, expires_at)
                )
                await db.commit()
                return cursor.lastrowid
            except aiosqlite.IntegrityError:
                # Платёж с таким provider_payment_id уже существует
                return None
    
    async def update_payment_status(self, provider_payment_id: str, status: str) -> bool:
        """
        Обновить статус платежа
        
        Returns:
            True если обновлено, False если платеж не найден
        """
        async with aiosqlite.connect(self.db_path) as db:
            paid_at = datetime.now().isoformat() if status == 'paid' else None
            
            cursor = await db.execute(
                "UPDATE payments SET status = ?, paid_at = ? WHERE provider_payment_id = ?",
                (status, paid_at, provider_payment_id)
            )
            await db.commit()
            
            return cursor.rowcount > 0
    
    async def process_paid_payment(
        self,
        provider_payment_id: str,
        user_id: int,
        amount: float
    ) -> Dict[str, Any]:
        """
        Атомарная обработка оплаченного платежа
        
        Выполняет в одной транзакции:
        1. Проверку статуса платежа
        2. Добавление записи в ledger
        3. Обновление статуса платежа
        
        Args:
            provider_payment_id: ID платежа от провайдера
            user_id: ID пользователя
            amount: Сумма платежа
        
        Returns:
            {
                "success": bool,
                "already_processed": bool,
                "new_balance": float,
                "error": str (optional)
            }
        """
        async with aiosqlite.connect(self.db_path) as db:
            try:
                # Начать транзакцию
                await db.execute("BEGIN TRANSACTION")
                
                # 1. Проверить текущий статус платежа
                db.row_factory = aiosqlite.Row
                async with db.execute(
                    "SELECT status FROM payments WHERE provider_payment_id = ?",
                    (provider_payment_id,)
                ) as cursor:
                    row = await cursor.fetchone()
                    
                    if not row:
                        await db.execute("ROLLBACK")
                        return {
                            "success": False,
                            "error": "Payment not found"
                        }
                    
                    current_status = row["status"]
                    
                    # Если уже paid - вернуть already_processed
                    if current_status == "paid":
                        await db.execute("ROLLBACK")
                        
                        # Получить текущий баланс
                        balance = await self._get_balance_in_transaction(db, user_id)
                        
                        return {
                            "success": True,
                            "already_processed": True,
                            "new_balance": balance
                        }
                
                # 2. Добавить запись в ledger (с UNIQUE constraint)
                created_at = datetime.now().isoformat()
                
                try:
                    await db.execute(
                        """
                        INSERT INTO ledger (user_id, entry_type, amount, ref_type, ref_id, description, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            user_id,
                            "credit",
                            amount,
                            "payment",
                            provider_payment_id,
                            f"Пополнение баланса через YooKassa",
                            created_at
                        )
                    )
                except aiosqlite.IntegrityError as e:
                    # UNIQUE constraint failed - платеж уже начислен
                    await db.execute("ROLLBACK")
                    
                    # Получить текущий баланс
                    balance = await self._get_balance_in_transaction(db, user_id)
                    
                    return {
                        "success": True,
                        "already_processed": True,
                        "new_balance": balance
                    }
                
                # 3. Обновить статус платежа
                paid_at = datetime.now().isoformat()
                await db.execute(
                    "UPDATE payments SET status = ?, paid_at = ? WHERE provider_payment_id = ?",
                    ("paid", paid_at, provider_payment_id)
                )
                
                # Получить новый баланс
                new_balance = await self._get_balance_in_transaction(db, user_id)
                
                # Закоммитить транзакцию
                await db.commit()
                
                return {
                    "success": True,
                    "already_processed": False,
                    "new_balance": new_balance
                }
            
            except Exception as e:
                await db.execute("ROLLBACK")
                logger.error(f"Error processing paid payment {provider_payment_id}: {e}", exc_info=True)
                return {
                    "success": False,
                    "error": str(e)
                }
    
    async def _get_balance_in_transaction(self, db, user_id: int) -> float:
        """Получить баланс в рамках транзакции"""
        async with db.execute(
            "SELECT COALESCE(SUM(amount), 0) as balance FROM ledger WHERE user_id = ?",
            (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return float(row[0]) if row else 0.0
    
    async def get_payment_by_provider_id(self, provider_payment_id: str) -> Optional[Dict[str, Any]]:
        """Получить информацию о платеже по provider_payment_id"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM payments WHERE provider_payment_id = ?",
                (provider_payment_id,)
            ) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None
    
    async def get_payment(self, payment_id: int) -> Optional[Dict[str, Any]]:
        """Получить информацию о платеже по ID"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM payments WHERE id = ?",
                (payment_id,)
            ) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None


    async def get_user_payments_since(
        self,
        user_id: int,
        since: datetime
    ) -> List[Dict[str, Any]]:
        """
        Получить платежи пользователя с определенного времени
        
        Args:
            user_id: ID пользователя
            since: Дата/время начала периода
        
        Returns:
            Список платежей
        """
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            since_iso = since.isoformat()
            async with db.execute(
                "SELECT * FROM payments WHERE user_id = ? AND created_at >= ? ORDER BY created_at DESC",
                (user_id, since_iso)
            ) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]


    # ==================== USAGE SESSIONS (F-302) ====================
    
    async def create_usage_session(self, job_id: int, user_id: int) -> int:
        """
        Создать usage session для отслеживания ₽/сек
        
        Returns:
            session_id
        """
        async with aiosqlite.connect(self.db_path) as db:
            started_at = datetime.now().isoformat()
            
            cursor = await db.execute(
                "INSERT INTO usage_sessions (job_id, user_id, started_at) VALUES (?, ?, ?)",
                (job_id, user_id, started_at)
            )
            await db.commit()
            return cursor.lastrowid
    
    async def end_usage_session(
        self,
        session_id: int,
        billed_seconds: int,
        amount: float,
        ledger_ref_id: str
    ) -> bool:
        """
        Завершить usage session
        
        Args:
            session_id: ID сессии
            billed_seconds: Количество секунд для биллинга
            amount: Сумма списания
            ledger_ref_id: Ссылка на ledger entry
        
        Returns:
            True если обновлено
        """
        async with aiosqlite.connect(self.db_path) as db:
            ended_at = datetime.now().isoformat()
            
            cursor = await db.execute(
                """UPDATE usage_sessions 
                   SET ended_at = ?, billed_seconds = ?, amount = ?, ledger_ref_id = ?
                   WHERE id = ?""",
                (ended_at, billed_seconds, amount, ledger_ref_id, session_id)
            )
            await db.commit()
            return cursor.rowcount > 0
    
    async def get_usage_session(self, session_id: int) -> Optional[Dict[str, Any]]:
        """Получить usage session"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM usage_sessions WHERE id = ?",
                (session_id,)
            ) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None
    
    async def get_job_usage_sessions(self, job_id: int) -> List[Dict[str, Any]]:
        """Получить все usage sessions для job"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM usage_sessions WHERE job_id = ? ORDER BY started_at",
                (job_id,)
            ) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]
    
    async def get_user_usage_sessions(
        self,
        user_id: int,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Получить usage sessions пользователя"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """SELECT * FROM usage_sessions 
                   WHERE user_id = ? 
                   ORDER BY started_at DESC 
                   LIMIT ?""",
                (user_id, limit)
            ) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]


    # ========== Webhook Events (Deduplication) ==========
    
    async def is_webhook_processed(self, webhook_id: str) -> bool:
        """
        Проверить, был ли webhook уже обработан
        
        Args:
            webhook_id: Уникальный ID webhook
        
        Returns:
            True если webhook уже обработан
        """
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT 1 FROM webhook_events WHERE webhook_id = ?",
                (webhook_id,)
            ) as cursor:
                return await cursor.fetchone() is not None
    
    async def mark_webhook_processed(self, webhook_id: str, ttl_hours: int = 24) -> bool:
        """
        Пометить webhook как обработанный
        
        Args:
            webhook_id: Уникальный ID webhook
            ttl_hours: Время хранения в часах
        
        Returns:
            True если успешно, False если уже существует
        """
        try:
            async with aiosqlite.connect(self.db_path) as db:
                processed_at = datetime.now().isoformat()
                expires_at = (datetime.now() + timedelta(hours=ttl_hours)).isoformat()
                
                await db.execute(
                    "INSERT INTO webhook_events (webhook_id, processed_at, expires_at) VALUES (?, ?, ?)",
                    (webhook_id, processed_at, expires_at)
                )
                await db.commit()
                return True
        except aiosqlite.IntegrityError:
            # Webhook уже существует
            return False
    
    async def cleanup_expired_webhooks(self) -> int:
        """
        Удалить устаревшие webhook events
        
        Returns:
            Количество удаленных записей
        """
        async with aiosqlite.connect(self.db_path) as db:
            now = datetime.now().isoformat()
            cursor = await db.execute(
                "DELETE FROM webhook_events WHERE expires_at < ?",
                (now,)
            )
            await db.commit()
            return cursor.rowcount


    # ========== Pricing Management ==========
    
    async def set_price(
        self,
        provider: str,
        price_rub: float,
        model: Optional[str] = None,
        action: Optional[str] = None,
        updated_by: Optional[int] = None
    ) -> bool:
        """
        Установить цену для провайдера/модели/действия
        
        Args:
            provider: Провайдер (nano_banana, kling)
            price_rub: Цена в рублях
            model: Модель (опционально)
            action: Действие (generation, edit, опционально)
            updated_by: ID админа
        
        Returns:
            True если успешно
        """
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute(
                    """
                    INSERT INTO pricing (provider, model, action, price_rub, updated_at, updated_by)
                    VALUES (?, ?, ?, ?, datetime('now'), ?)
                    ON CONFLICT(provider, model, action) DO UPDATE SET
                        price_rub = excluded.price_rub,
                        updated_at = excluded.updated_at,
                        updated_by = excluded.updated_by
                    """,
                    (provider, model, action, price_rub, updated_by)
                )
                await db.commit()
                logger.info(f"Price set: {provider}/{model}/{action} = {price_rub} ₽")
                return True
        except Exception as e:
            logger.error(f"Failed to set price: {e}")
            return False
    
    async def get_price(
        self,
        provider: str,
        model: Optional[str] = None,
        action: Optional[str] = None
    ) -> Optional[float]:
        """
        Получить цену с fallback
        
        Порядок поиска:
        1. provider + model + action
        2. provider + model (action=NULL)
        3. provider (model=NULL, action=NULL)
        4. config (fallback)
        
        Args:
            provider: Провайдер
            model: Модель
            action: Действие
        
        Returns:
            Цена в рублях или None
        """
        async with aiosqlite.connect(self.db_path) as db:
            # 1. Полное совпадение
            if model and action:
                async with db.execute(
                    "SELECT price_rub FROM pricing WHERE provider = ? AND model = ? AND action = ?",
                    (provider, model, action)
                ) as cursor:
                    row = await cursor.fetchone()
                    if row:
                        return row[0]
            
            # 2. provider + model
            if model:
                async with db.execute(
                    "SELECT price_rub FROM pricing WHERE provider = ? AND model = ? AND action IS NULL",
                    (provider, model)
                ) as cursor:
                    row = await cursor.fetchone()
                    if row:
                        return row[0]
            
            # 3. Только provider
            async with db.execute(
                "SELECT price_rub FROM pricing WHERE provider = ? AND model IS NULL AND action IS NULL",
                (provider,)
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    return row[0]
        
        # 4. Fallback на config
        return self._get_price_from_config(provider, action)
    
    def _get_price_from_config(self, provider: str, action: Optional[str] = None) -> Optional[float]:
        """Получить цену из config.py"""
        if provider == "nano_banana":
            if action == "edit":
                return config.IMAGE_EDIT_PRICE
            return config.IMAGE_GENERATION_PRICE
        elif provider == "kling":
            return config.VIDEO_5SEC_PRICE
        return None
    
    async def get_all_prices(self) -> List[Dict[str, Any]]:
        """Получить все цены из БД"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM pricing ORDER BY provider, model, action"
            ) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]


# Глобальный экземпляр базы данных
db = Database()

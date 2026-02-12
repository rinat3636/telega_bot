"""
Balance View Refresh Logic

Provides functions to refresh materialized balance view
"""
import asyncio
import aiosqlite
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class BalanceViewRefresher:
    """Refresh materialized balance view"""
    
    def __init__(self, db_path: str):
        self.db_path = db_path
    
    async def refresh_user_balance(self, user_id: int) -> float:
        """
        Refresh balance for specific user
        
        Returns:
            Updated balance
        """
        async with aiosqlite.connect(self.db_path) as db:
            # Calculate balance from ledger
            cursor = await db.execute(
                "SELECT COALESCE(SUM(amount), 0) FROM ledger WHERE user_id = ?",
                (user_id,)
            )
            row = await cursor.fetchone()
            balance = row[0] if row else 0.0
            
            # Count ledger entries
            cursor = await db.execute(
                "SELECT COUNT(*) FROM ledger WHERE user_id = ?",
                (user_id,)
            )
            row = await cursor.fetchone()
            ledger_count = row[0] if row else 0
            
            # Update cache
            await db.execute(
                """
                INSERT INTO user_balance_cache (user_id, balance, last_updated, ledger_count)
                VALUES (?, ?, CURRENT_TIMESTAMP, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    balance = excluded.balance,
                    last_updated = CURRENT_TIMESTAMP,
                    ledger_count = excluded.ledger_count
                """,
                (user_id, balance, ledger_count)
            )
            await db.commit()
            
            logger.info(f"Refreshed balance for user {user_id}: {balance}")
            return balance
    
    async def refresh_all_balances(self):
        """Refresh balances for all users"""
        async with aiosqlite.connect(self.db_path) as db:
            # Get all users with ledger entries
            cursor = await db.execute(
                "SELECT DISTINCT user_id FROM ledger"
            )
            user_ids = [row[0] for row in await cursor.fetchall()]
            
            logger.info(f"Refreshing balances for {len(user_ids)} users...")
            
            for user_id in user_ids:
                await self.refresh_user_balance(user_id)
            
            logger.info(f"Refreshed balances for {len(user_ids)} users")
    
    async def refresh_stale_balances(self, max_age_minutes: int = 5):
        """
        Refresh balances that haven't been updated recently
        
        Args:
            max_age_minutes: Maximum age in minutes before refresh
        """
        async with aiosqlite.connect(self.db_path) as db:
            cutoff_time = datetime.now() - timedelta(minutes=max_age_minutes)
            
            # Find stale balances using SQLite datetime comparison
            cursor = await db.execute(
                """
                SELECT user_id FROM user_balance_cache
                WHERE datetime(last_updated) < datetime(?)
                """,
                (cutoff_time.strftime("%Y-%m-%d %H:%M:%S"),)
            )
            stale_users = [row[0] for row in await cursor.fetchall()]
            
            if stale_users:
                logger.info(f"Found {len(stale_users)} stale balances, refreshing...")
                
                for user_id in stale_users:
                    await self.refresh_user_balance(user_id)
                
                logger.info(f"Refreshed {len(stale_users)} stale balances")
            else:
                logger.debug("No stale balances found")
    
    async def verify_balance_integrity(self) -> bool:
        """
        Verify that cached balances match ledger
        
        Returns:
            True if all balances match, False otherwise
        """
        async with aiosqlite.connect(self.db_path) as db:
            # Compare cached balances with ledger
            cursor = await db.execute(
                """
                SELECT 
                    c.user_id,
                    c.balance as cached_balance,
                    COALESCE(SUM(l.amount), 0) as actual_balance
                FROM user_balance_cache c
                LEFT JOIN ledger l ON c.user_id = l.user_id
                GROUP BY c.user_id
                HAVING ABS(c.balance - actual_balance) > 0.01
                """
            )
            
            mismatches = await cursor.fetchall()
            
            if mismatches:
                logger.error(f"Found {len(mismatches)} balance mismatches:")
                for user_id, cached, actual in mismatches:
                    logger.error(f"  User {user_id}: cached={cached}, actual={actual}")
                return False
            else:
                logger.info("All balances verified successfully")
                return True
    
    async def get_balance_stats(self) -> dict:
        """Get statistics about balance cache"""
        async with aiosqlite.connect(self.db_path) as db:
            # Total users
            cursor = await db.execute("SELECT COUNT(*) FROM user_balance_cache")
            total_users = (await cursor.fetchone())[0]
            
            # Total balance
            cursor = await db.execute("SELECT SUM(balance) FROM user_balance_cache")
            total_balance = (await cursor.fetchone())[0] or 0.0
            
            # Average balance
            avg_balance = total_balance / total_users if total_users > 0 else 0.0
            
            # Stale balances (> 5 minutes)
            cutoff_time = datetime.now() - timedelta(minutes=5)
            cursor = await db.execute(
                "SELECT COUNT(*) FROM user_balance_cache WHERE datetime(last_updated) < datetime(?)",
                (cutoff_time.strftime("%Y-%m-%d %H:%M:%S"),)
            )
            stale_count = (await cursor.fetchone())[0]
            
            return {
                "total_users": total_users,
                "total_balance": total_balance,
                "average_balance": avg_balance,
                "stale_count": stale_count
            }


# Scheduled refresh task
async def scheduled_refresh_task(db_path: str, interval_minutes: int = 5):
    """
    Background task to refresh stale balances periodically
    
    Args:
        db_path: Path to database
        interval_minutes: Refresh interval in minutes
    """
    refresher = BalanceViewRefresher(db_path)
    
    while True:
        try:
            await refresher.refresh_stale_balances(max_age_minutes=interval_minutes)
            await asyncio.sleep(interval_minutes * 60)
        except Exception as e:
            logger.error(f"Error in scheduled refresh: {e}", exc_info=True)
            await asyncio.sleep(60)  # Retry after 1 minute


if __name__ == '__main__':
    # Test refresh
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python refresh_balance.py <db_path>")
        sys.exit(1)
    
    db_path = sys.argv[1]
    refresher = BalanceViewRefresher(db_path)
    
    async def main():
        print("Refreshing all balances...")
        await refresher.refresh_all_balances()
        
        print("\nVerifying integrity...")
        valid = await refresher.verify_balance_integrity()
        
        print("\nBalance stats:")
        stats = await refresher.get_balance_stats()
        for key, value in stats.items():
            print(f"  {key}: {value}")
        
        return valid
    
    success = asyncio.run(main())
    sys.exit(0 if success else 1)

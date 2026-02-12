-- Materialized View: User Balance
-- 
-- Provides fast access to user balances without scanning entire ledger
-- Refresh strategy: ON COMMIT (real-time) + scheduled fallback

-- Drop existing view if exists
DROP VIEW IF EXISTS user_balance_view;

-- Create materialized view (SQLite doesn't support MATERIALIZED VIEW, so we use a regular table)
CREATE TABLE IF NOT EXISTS user_balance_cache (
    user_id INTEGER PRIMARY KEY,
    balance REAL NOT NULL DEFAULT 0.0,
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    ledger_count INTEGER DEFAULT 0
);

-- Create index for fast lookups
CREATE INDEX IF NOT EXISTS idx_user_balance_updated ON user_balance_cache(last_updated);

-- Trigger: Update balance on ledger INSERT
CREATE TRIGGER IF NOT EXISTS trg_ledger_insert_update_balance
AFTER INSERT ON ledger
BEGIN
    INSERT INTO user_balance_cache (user_id, balance, last_updated, ledger_count)
    VALUES (
        NEW.user_id,
        NEW.amount,
        CURRENT_TIMESTAMP,
        1
    )
    ON CONFLICT(user_id) DO UPDATE SET
        balance = balance + NEW.amount,
        last_updated = CURRENT_TIMESTAMP,
        ledger_count = ledger_count + 1;
END;

-- Function to refresh balance for specific user
-- (Implemented in Python as SQLite doesn't support stored procedures)

-- Function to refresh all balances
-- (Implemented in Python as SQLite doesn't support stored procedures)

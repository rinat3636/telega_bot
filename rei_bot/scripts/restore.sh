#!/bin/bash
#
# Cold Restore Script for REI Bot
# Usage: ./restore.sh <backup_timestamp>
#

set -e

if [ $# -lt 1 ]; then
    echo "Usage: $0 <backup_timestamp>"
    echo "Example: $0 20260212_143000"
    exit 1
fi

TIMESTAMP=$1
BACKUP_DIR="${BACKUP_DIR:-/var/backups/rei_bot}"
RESTORE_DIR="${RESTORE_DIR:-./restored}"
S3_BUCKET="${S3_BUCKET:-}"

echo "[$(date)] Starting cold restore for timestamp: $TIMESTAMP"

# Create restore directory
mkdir -p "$RESTORE_DIR"

# ==================== DOWNLOAD FROM S3 (if configured) ====================

if [ -n "$S3_BUCKET" ]; then
    echo "[$(date)] Downloading backups from S3..."
    
    aws s3 cp "s3://$S3_BUCKET/backups/db_$TIMESTAMP.db.gz" "$BACKUP_DIR/" || echo "WARNING: DB download failed"
    aws s3 cp "s3://$S3_BUCKET/backups/ledger_$TIMESTAMP.csv.gz" "$BACKUP_DIR/" || echo "WARNING: Ledger download failed"
    aws s3 cp "s3://$S3_BUCKET/backups/assets_$TIMESTAMP.tar.gz" "$BACKUP_DIR/" || echo "WARNING: Assets download failed"
    aws s3 cp "s3://$S3_BUCKET/backups/config_$TIMESTAMP.tar.gz" "$BACKUP_DIR/" || echo "WARNING: Config download failed"
fi

# ==================== RESTORE DATABASE ====================

echo "[$(date)] Restoring database..."
DB_BACKUP="$BACKUP_DIR/db_$TIMESTAMP.db.gz"

if [ -f "$DB_BACKUP" ]; then
    gunzip -c "$DB_BACKUP" > "$RESTORE_DIR/bot.db"
    
    # Verify integrity
    sqlite3 "$RESTORE_DIR/bot.db" "PRAGMA integrity_check;" > /dev/null
    
    echo "[$(date)] Database restored: $RESTORE_DIR/bot.db"
else
    echo "[$(date)] ERROR: Database backup not found: $DB_BACKUP"
    exit 1
fi

# ==================== RESTORE LEDGER (verification) ====================

echo "[$(date)] Verifying ledger..."
LEDGER_BACKUP="$BACKUP_DIR/ledger_$TIMESTAMP.csv.gz"

if [ -f "$LEDGER_BACKUP" ]; then
    gunzip -c "$LEDGER_BACKUP" > "$RESTORE_DIR/ledger.csv"
    
    # Count records
    LEDGER_COUNT=$(tail -n +2 "$RESTORE_DIR/ledger.csv" | wc -l)
    echo "[$(date)] Ledger records: $LEDGER_COUNT"
else
    echo "[$(date)] WARNING: Ledger backup not found: $LEDGER_BACKUP"
fi

# ==================== RESTORE ASSETS ====================

echo "[$(date)] Restoring assets..."
ASSETS_BACKUP="$BACKUP_DIR/assets_$TIMESTAMP.tar.gz"

if [ -f "$ASSETS_BACKUP" ]; then
    tar -xzf "$ASSETS_BACKUP" -C "$RESTORE_DIR"
    echo "[$(date)] Assets restored: $RESTORE_DIR/assets"
else
    echo "[$(date)] WARNING: Assets backup not found: $ASSETS_BACKUP"
fi

# ==================== RESTORE CONFIG ====================

echo "[$(date)] Restoring config..."
CONFIG_BACKUP="$BACKUP_DIR/config_$TIMESTAMP.tar.gz"

if [ -f "$CONFIG_BACKUP" ]; then
    tar -xzf "$CONFIG_BACKUP" -C "$RESTORE_DIR"
    echo "[$(date)] Config restored"
else
    echo "[$(date)] WARNING: Config backup not found: $CONFIG_BACKUP"
fi

# ==================== VERIFICATION ====================

echo "[$(date)] Verifying restore..."

# Check database
if [ -f "$RESTORE_DIR/bot.db" ]; then
    USER_COUNT=$(sqlite3 "$RESTORE_DIR/bot.db" "SELECT COUNT(*) FROM users;")
    JOB_COUNT=$(sqlite3 "$RESTORE_DIR/bot.db" "SELECT COUNT(*) FROM jobs;")
    LEDGER_COUNT=$(sqlite3 "$RESTORE_DIR/bot.db" "SELECT COUNT(*) FROM ledger;")
    
    echo "  Users: $USER_COUNT"
    echo "  Jobs: $JOB_COUNT"
    echo "  Ledger entries: $LEDGER_COUNT"
fi

# Check assets
if [ -d "$RESTORE_DIR/assets" ]; then
    ASSET_COUNT=$(find "$RESTORE_DIR/assets" -type f | wc -l)
    ASSET_SIZE=$(du -sh "$RESTORE_DIR/assets" | cut -f1)
    echo "  Assets: $ASSET_COUNT files ($ASSET_SIZE)"
fi

echo "[$(date)] Cold restore complete!"
echo ""
echo "Restored files location: $RESTORE_DIR"
echo ""
echo "Next steps:"
echo "1. Review restored files"
echo "2. Copy to production location"
echo "3. Update .env configuration"
echo "4. Restart services"

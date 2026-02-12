#!/bin/bash
#
# Automated Backup Script for REI Bot
# Runs hourly via cron
#

set -e

# Configuration
BACKUP_DIR="${BACKUP_DIR:-/var/backups/rei_bot}"
DATABASE_PATH="${DATABASE_PATH:-./bot.db}"
ASSETS_DIR="${ASSETS_DIR:-./assets}"
RETENTION_DAYS="${RETENTION_DAYS:-7}"
S3_BUCKET="${S3_BUCKET:-}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

# Create backup directory
mkdir -p "$BACKUP_DIR"

echo "[$(date)] Starting backup..."

# ==================== DATABASE BACKUP ====================

echo "[$(date)] Backing up database..."
DB_BACKUP="$BACKUP_DIR/db_$TIMESTAMP.db"

if [ -f "$DATABASE_PATH" ]; then
    # SQLite backup with integrity check
    sqlite3 "$DATABASE_PATH" ".backup '$DB_BACKUP'"
    
    # Verify backup integrity
    sqlite3 "$DB_BACKUP" "PRAGMA integrity_check;" > /dev/null
    
    # Compress backup
    gzip "$DB_BACKUP"
    DB_BACKUP="$DB_BACKUP.gz"
    
    echo "[$(date)] Database backup: $DB_BACKUP"
else
    echo "[$(date)] WARNING: Database not found at $DATABASE_PATH"
fi

# ==================== LEDGER EXPORT ====================

echo "[$(date)] Exporting ledger..."
LEDGER_BACKUP="$BACKUP_DIR/ledger_$TIMESTAMP.csv"

if [ -f "$DATABASE_PATH" ]; then
    sqlite3 "$DATABASE_PATH" <<EOF > "$LEDGER_BACKUP"
.mode csv
.headers on
SELECT * FROM ledger ORDER BY created_at;
EOF
    
    gzip "$LEDGER_BACKUP"
    LEDGER_BACKUP="$LEDGER_BACKUP.gz"
    
    echo "[$(date)] Ledger export: $LEDGER_BACKUP"
fi

# ==================== ASSETS BACKUP ====================

echo "[$(date)] Backing up assets..."
ASSETS_BACKUP="$BACKUP_DIR/assets_$TIMESTAMP.tar.gz"

if [ -d "$ASSETS_DIR" ]; then
    tar -czf "$ASSETS_BACKUP" -C "$(dirname "$ASSETS_DIR")" "$(basename "$ASSETS_DIR")"
    echo "[$(date)] Assets backup: $ASSETS_BACKUP"
else
    echo "[$(date)] WARNING: Assets directory not found at $ASSETS_DIR"
fi

# ==================== CONFIG BACKUP ====================

echo "[$(date)] Backing up config..."
CONFIG_BACKUP="$BACKUP_DIR/config_$TIMESTAMP.tar.gz"

tar -czf "$CONFIG_BACKUP" \
    --exclude='*.db' \
    --exclude='assets/*' \
    --exclude='__pycache__' \
    --exclude='.git' \
    .env config.py requirements.txt

echo "[$(date)] Config backup: $CONFIG_BACKUP"

# ==================== S3 UPLOAD (optional) ====================

if [ -n "$S3_BUCKET" ]; then
    echo "[$(date)] Uploading to S3..."
    
    aws s3 cp "$DB_BACKUP" "s3://$S3_BUCKET/backups/$(basename "$DB_BACKUP")" || echo "WARNING: S3 upload failed"
    aws s3 cp "$LEDGER_BACKUP" "s3://$S3_BUCKET/backups/$(basename "$LEDGER_BACKUP")" || echo "WARNING: S3 upload failed"
    aws s3 cp "$ASSETS_BACKUP" "s3://$S3_BUCKET/backups/$(basename "$ASSETS_BACKUP")" || echo "WARNING: S3 upload failed"
    aws s3 cp "$CONFIG_BACKUP" "s3://$S3_BUCKET/backups/$(basename "$CONFIG_BACKUP")" || echo "WARNING: S3 upload failed"
    
    echo "[$(date)] S3 upload complete"
fi

# ==================== CLEANUP OLD BACKUPS ====================

echo "[$(date)] Cleaning up old backups (retention: $RETENTION_DAYS days)..."

find "$BACKUP_DIR" -name "*.gz" -type f -mtime +$RETENTION_DAYS -delete
find "$BACKUP_DIR" -name "*.tar.gz" -type f -mtime +$RETENTION_DAYS -delete

echo "[$(date)] Backup complete!"

# ==================== BACKUP VERIFICATION ====================

echo "[$(date)] Verifying backups..."

# Check file sizes
for file in "$DB_BACKUP" "$LEDGER_BACKUP" "$ASSETS_BACKUP" "$CONFIG_BACKUP"; do
    if [ -f "$file" ]; then
        size=$(du -h "$file" | cut -f1)
        echo "  $file: $size"
    fi
done

echo "[$(date)] Backup verification complete"

# Multi-Region Setup Guide

## Overview

This guide provides instructions for setting up REI Bot in a multi-region configuration for disaster recovery and high availability.

**Architecture:**
- Primary region: Main production instance
- Secondary region: Hot standby with read replicas
- S3: Cross-region replication for backups and assets

---

## Prerequisites

- AWS Account with multi-region access
- Two regions configured (e.g., us-east-1 and eu-west-1)
- S3 buckets in both regions
- RDS or managed PostgreSQL (for production scale)

---

## Step 1: Primary Region Setup

### 1.1 Database Setup

```bash
# Primary database (PostgreSQL recommended for production)
# Create primary database
createdb rei_bot_primary

# Run migrations
python3 database/migrate.py

# Enable WAL archiving for replication
# Edit postgresql.conf:
wal_level = replica
max_wal_senders = 3
wal_keep_segments = 64
```

### 1.2 S3 Bucket Setup

```bash
# Create primary S3 bucket
aws s3 mb s3://rei-bot-assets-us-east-1

# Enable versioning
aws s3api put-bucket-versioning \
    --bucket rei-bot-assets-us-east-1 \
    --versioning-configuration Status=Enabled

# Enable cross-region replication
aws s3api put-bucket-replication \
    --bucket rei-bot-assets-us-east-1 \
    --replication-configuration file://replication-config.json
```

**replication-config.json:**
```json
{
  "Role": "arn:aws:iam::ACCOUNT_ID:role/S3ReplicationRole",
  "Rules": [
    {
      "Status": "Enabled",
      "Priority": 1,
      "Filter": {},
      "Destination": {
        "Bucket": "arn:aws:s3:::rei-bot-assets-eu-west-1",
        "ReplicationTime": {
          "Status": "Enabled",
          "Time": {
            "Minutes": 15
          }
        }
      }
    }
  ]
}
```

### 1.3 Application Deployment

```bash
# Deploy primary application
cd /opt/rei_bot
git pull origin main

# Update configuration
cp .env.primary .env

# Restart services
systemctl restart rei_bot
systemctl restart rei_bot_workers
```

---

## Step 2: Secondary Region Setup

### 2.1 Database Replication

```bash
# Create read replica
aws rds create-db-instance-read-replica \
    --db-instance-identifier rei-bot-replica-eu \
    --source-db-instance-identifier rei-bot-primary-us \
    --db-instance-class db.t3.medium \
    --availability-zone eu-west-1a

# Wait for replica to be available
aws rds wait db-instance-available \
    --db-instance-identifier rei-bot-replica-eu
```

**For PostgreSQL streaming replication:**

```bash
# On secondary server
# Stop PostgreSQL
systemctl stop postgresql

# Remove existing data
rm -rf /var/lib/postgresql/data/*

# Create base backup from primary
pg_basebackup -h primary-db-host -D /var/lib/postgresql/data -U replication -P -v

# Configure recovery
cat > /var/lib/postgresql/data/recovery.conf <<EOF
standby_mode = 'on'
primary_conninfo = 'host=primary-db-host port=5432 user=replication password=PASSWORD'
trigger_file = '/tmp/postgresql.trigger'
EOF

# Start PostgreSQL
systemctl start postgresql
```

### 2.2 S3 Bucket Setup

```bash
# Create secondary S3 bucket
aws s3 mb s3://rei-bot-assets-eu-west-1 --region eu-west-1

# Enable versioning
aws s3api put-bucket-versioning \
    --bucket rei-bot-assets-eu-west-1 \
    --versioning-configuration Status=Enabled \
    --region eu-west-1
```

### 2.3 Application Deployment (Standby)

```bash
# Deploy standby application
cd /opt/rei_bot
git pull origin main

# Update configuration (read-only mode)
cp .env.secondary .env

# Configure read-only mode
echo "READ_ONLY_MODE=true" >> .env
echo "DATABASE_URL=postgresql://replica-host/rei_bot" >> .env

# Start services (read-only)
systemctl start rei_bot_readonly
```

---

## Step 3: Monitoring and Failover

### 3.1 Replication Monitoring

```bash
# Check replication lag (PostgreSQL)
psql -h replica-host -c "SELECT now() - pg_last_xact_replay_timestamp() AS replication_lag;"

# Monitor replication status
psql -h primary-host -c "SELECT * FROM pg_stat_replication;"
```

### 3.2 Automated Health Checks

```bash
# Create health check script
cat > /opt/rei_bot/scripts/health_check.sh <<'EOF'
#!/bin/bash

PRIMARY_HOST="primary-db-host"
SECONDARY_HOST="secondary-db-host"

# Check primary health
if ! pg_isready -h $PRIMARY_HOST -p 5432; then
    echo "PRIMARY DOWN: Initiating failover..."
    /opt/rei_bot/scripts/failover.sh
fi

# Check replication lag
LAG=$(psql -h $SECONDARY_HOST -t -c "SELECT EXTRACT(EPOCH FROM (now() - pg_last_xact_replay_timestamp()));" | tr -d ' ')

if [ $(echo "$LAG > 300" | bc) -eq 1 ]; then
    echo "WARNING: Replication lag > 5 minutes ($LAG seconds)"
fi
EOF

chmod +x /opt/rei_bot/scripts/health_check.sh

# Add to cron (every minute)
echo "* * * * * /opt/rei_bot/scripts/health_check.sh" | crontab -
```

### 3.3 Failover Script

```bash
# Create failover script
cat > /opt/rei_bot/scripts/failover.sh <<'EOF'
#!/bin/bash

set -e

echo "[$(date)] Starting failover to secondary region..."

# 1. Promote secondary to primary
touch /tmp/postgresql.trigger

# Wait for promotion
sleep 10

# 2. Update DNS (Route53)
aws route53 change-resource-record-sets \
    --hosted-zone-id ZONE_ID \
    --change-batch file://failover-dns.json

# 3. Enable write mode on secondary
systemctl stop rei_bot_readonly
sed -i 's/READ_ONLY_MODE=true/READ_ONLY_MODE=false/' /opt/rei_bot/.env
systemctl start rei_bot
systemctl start rei_bot_workers

# 4. Notify team
curl -X POST https://hooks.slack.com/services/YOUR/WEBHOOK/URL \
    -H 'Content-Type: application/json' \
    -d '{"text":"🚨 FAILOVER: Switched to secondary region"}'

echo "[$(date)] Failover complete!"
EOF

chmod +x /opt/rei_bot/scripts/failover.sh
```

---

## Step 4: Testing Failover

### 4.1 Planned Failover Test

```bash
# 1. Schedule maintenance window
# 2. Notify users

# 3. Execute failover
/opt/rei_bot/scripts/failover.sh

# 4. Verify functionality
curl https://api.rei-bot.com/health
python3 /opt/rei_bot/tests/integration/test_failover.py

# 5. Monitor for 1 hour
# 6. Document results
```

### 4.2 Failback Procedure

```bash
# 1. Fix primary region
# 2. Sync data from secondary to primary
pg_basebackup -h secondary-host -D /var/lib/postgresql/data -U replication -P -v

# 3. Configure primary as new primary
rm /var/lib/postgresql/data/recovery.conf
systemctl restart postgresql

# 4. Configure secondary as replica again
# Follow Step 2.1

# 5. Switch DNS back to primary
aws route53 change-resource-record-sets \
    --hosted-zone-id ZONE_ID \
    --change-batch file://failback-dns.json

# 6. Restart services
systemctl restart rei_bot
systemctl restart rei_bot_workers
```

---

## Step 5: Backup Strategy

### 5.1 Continuous Backups

```bash
# Enable point-in-time recovery
aws rds modify-db-instance \
    --db-instance-identifier rei-bot-primary \
    --backup-retention-period 7 \
    --preferred-backup-window "03:00-04:00"

# S3 backup replication (already configured in Step 1.2)
```

### 5.2 Cross-Region Backup Verification

```bash
# Verify S3 replication
aws s3api get-bucket-replication \
    --bucket rei-bot-assets-us-east-1

# Test restore from secondary region
aws s3 cp s3://rei-bot-assets-eu-west-1/backups/latest.db.gz /tmp/
gunzip /tmp/latest.db.gz
sqlite3 /tmp/latest.db "PRAGMA integrity_check;"
```

---

## Monitoring Dashboard

### Key Metrics

| Metric | Threshold | Action |
|--------|-----------|--------|
| Replication Lag | > 5 minutes | Alert on-call |
| Primary DB Health | Down | Auto-failover |
| S3 Replication Lag | > 1 hour | Alert ops team |
| Secondary DB Health | Down | Alert ops team |

### Grafana Dashboard

```yaml
# Import dashboard: dashboards/multi-region.json
# Panels:
# - Replication lag
# - Cross-region latency
# - Backup status
# - Failover history
```

---

## Cost Optimization

### Read Replica Scaling

```bash
# Scale down replica during off-peak hours
aws rds modify-db-instance \
    --db-instance-identifier rei-bot-replica-eu \
    --db-instance-class db.t3.small \
    --apply-immediately

# Scale up during peak hours
aws rds modify-db-instance \
    --db-instance-identifier rei-bot-replica-eu \
    --db-instance-class db.t3.medium \
    --apply-immediately
```

### S3 Lifecycle Policies

```json
{
  "Rules": [
    {
      "Id": "ArchiveOldBackups",
      "Status": "Enabled",
      "Transitions": [
        {
          "Days": 30,
          "StorageClass": "GLACIER"
        }
      ],
      "Expiration": {
        "Days": 90
      }
    }
  ]
}
```

---

## Troubleshooting

### Replication Stopped

```bash
# Check replication status
psql -h primary-host -c "SELECT * FROM pg_stat_replication;"

# Check replica logs
tail -f /var/log/postgresql/postgresql.log

# Restart replication
systemctl restart postgresql
```

### Split-Brain Scenario

```bash
# If both regions think they're primary:
# 1. Stop writes on both
systemctl stop rei_bot rei_bot_workers

# 2. Determine which has latest data
psql -h primary-host -c "SELECT pg_last_xact_replay_timestamp();"
psql -h secondary-host -c "SELECT pg_last_xact_replay_timestamp();"

# 3. Choose primary (latest data)
# 4. Re-sync secondary from primary
# 5. Resume operations
```

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-02-12 | Initial version |

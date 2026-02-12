# Disaster Recovery Runbook

## Overview

This runbook provides step-by-step procedures for recovering the REI Bot system in case of catastrophic failure.

**RTO (Recovery Time Objective):** 1 hour  
**RPO (Recovery Point Objective):** 1 hour

---

## Scenarios

### 1. Database Corruption

**Symptoms:**
- SQLite integrity check fails
- Application crashes on database queries
- Inconsistent data

**Recovery Steps:**

```bash
# 1. Stop all services
systemctl stop rei_bot
systemctl stop rei_bot_workers

# 2. Backup corrupted database
mv bot.db bot.db.corrupted

# 3. Restore from latest backup
./scripts/restore.sh <latest_timestamp>

# 4. Copy restored database
cp restored/bot.db ./bot.db

# 5. Verify integrity
sqlite3 bot.db "PRAGMA integrity_check;"

# 6. Restart services
systemctl start rei_bot
systemctl start rei_bot_workers

# 7. Monitor logs
tail -f logs/bot.log
```

**Estimated Recovery Time:** 15 minutes

---

### 2. Complete Data Loss

**Symptoms:**
- All local data lost
- Server failure
- Disk failure

**Recovery Steps:**

```bash
# 1. Provision new server
# 2. Install dependencies
pip3 install -r requirements.txt

# 3. Download backups from S3
export S3_BUCKET=your-backup-bucket
./scripts/restore.sh <latest_timestamp>

# 4. Copy restored files
cp -r restored/* ./

# 5. Update configuration
cp .env.example .env
# Edit .env with production values

# 6. Start services
systemctl start redis
systemctl start rei_bot
systemctl start rei_bot_workers

# 7. Verify functionality
# - Send test message to bot
# - Check /balance
# - Verify payments
```

**Estimated Recovery Time:** 45 minutes

---

### 3. Redis Failure

**Symptoms:**
- Jobs not processing
- Rate limiting not working
- Connection errors to Redis

**Recovery Steps:**

```bash
# 1. Check Redis status
systemctl status redis

# 2. Restart Redis
systemctl restart redis

# 3. If Redis data corrupted, flush and restart
redis-cli FLUSHALL
systemctl restart redis

# 4. Restart workers
systemctl restart rei_bot_workers

# 5. Verify queue
redis-cli LLEN rq:queue:default
```

**Estimated Recovery Time:** 5 minutes

**Note:** Redis data is ephemeral. Job queue will be rebuilt from database.

---

### 4. Payment Provider Outage

**Symptoms:**
- YooKassa webhook failures
- Payment processing errors
- User complaints about payments

**Recovery Steps:**

```bash
# 1. Check YooKassa status
curl https://status.yookassa.ru/

# 2. Enable manual payment verification
# Edit config.py:
YOOKASSA_MANUAL_MODE=True

# 3. Monitor pending payments
sqlite3 bot.db "SELECT * FROM payments WHERE status='pending';"

# 4. After provider recovery, sync payments
python3 scripts/sync_payments.py

# 5. Notify affected users
python3 scripts/notify_payment_issues.py
```

**Estimated Recovery Time:** Variable (depends on provider)

---

### 5. AI Provider Outage

**Symptoms:**
- Job failures
- Timeout errors
- Provider API errors

**Recovery Steps:**

```bash
# 1. Check provider status
# Nano Banana: check dashboard
# Kling: check API status

# 2. Enable fallback providers
# Edit .env:
ENABLE_FALLBACK_PROVIDERS=true

# 3. Retry failed jobs
python3 scripts/retry_failed_jobs.py --last-hour

# 4. Monitor success rate
# Check Grafana dashboard

# 5. Notify users of delays
python3 scripts/broadcast_message.py "Experiencing delays..."
```

**Estimated Recovery Time:** 10 minutes

---

## Backup Verification

### Weekly Backup Test

```bash
# 1. Get latest backup
LATEST=$(ls -t /var/backups/rei_bot/db_*.db.gz | head -1)
TIMESTAMP=$(basename "$LATEST" | sed 's/db_\(.*\)\.db\.gz/\1/')

# 2. Restore to test directory
RESTORE_DIR=/tmp/backup_test ./scripts/restore.sh $TIMESTAMP

# 3. Verify data
sqlite3 /tmp/backup_test/bot.db <<EOF
SELECT COUNT(*) FROM users;
SELECT COUNT(*) FROM jobs;
SELECT COUNT(*) FROM ledger;
PRAGMA integrity_check;
EOF

# 4. Cleanup
rm -rf /tmp/backup_test
```

**Schedule:** Every Sunday at 02:00

---

## DR Drill Procedure

### Quarterly DR Drill

**Objective:** Validate recovery procedures and RTO/RPO targets

**Steps:**

1. **Preparation (Day 1)**
   - Notify team of drill
   - Schedule 2-hour maintenance window
   - Prepare test environment

2. **Execution (Day 2)**
   - Simulate failure scenario
   - Execute recovery procedures
   - Measure recovery time
   - Validate data integrity

3. **Verification (Day 2)**
   - Test all critical functions
   - Verify user data
   - Check payment processing
   - Validate job execution

4. **Debrief (Day 3)**
   - Document actual RTO/RPO
   - Identify improvements
   - Update runbook
   - Share lessons learned

**Next Drill:** Q2 2026

---

## Emergency Contacts

| Role | Name | Contact |
|------|------|---------|
| System Admin | TBD | +X-XXX-XXX-XXXX |
| Database Admin | TBD | +X-XXX-XXX-XXXX |
| On-Call Engineer | TBD | +X-XXX-XXX-XXXX |
| YooKassa Support | - | support@yookassa.ru |
| Nano Banana Support | - | support@nanobanana.ai |

---

## Post-Recovery Checklist

- [ ] All services running
- [ ] Database integrity verified
- [ ] Ledger balance matches
- [ ] Payment processing working
- [ ] Job queue processing
- [ ] Webhook receiving events
- [ ] Monitoring dashboards updated
- [ ] Incident report filed
- [ ] Team notified
- [ ] Users notified (if applicable)

---

## Lessons Learned Template

**Incident Date:**  
**Recovery Time:**  
**Data Loss:**  
**Root Cause:**  
**What Went Well:**  
**What Needs Improvement:**  
**Action Items:**

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-02-12 | Initial version |

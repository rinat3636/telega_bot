# Changelog v3.2 - FULL ENTERPRISE

## Added

- **F-402: SLO/SLA Monitoring**
  - `observability/slo.py` with SLO definitions, error budget tracking, and burn rate alerts.
  - Helper functions for tracking job, payment, and API success/failure.
  - `/admin/slo` endpoint for real-time SLO dashboard.

- **F-403: Disaster Recovery**
  - `scripts/backup.sh`: Automated hourly backups of database and assets to S3.
  - `scripts/restore.sh`: Cold restore script for full system recovery.
  - `runbooks/disaster_recovery.md`: Comprehensive DR runbook with scenarios and procedures.

- **F-404: Load & Chaos Testing**
  - `tests/load/parallel_jobs.js`: k6 load test for simulating 100 concurrent users.
  - `tests/chaos/redis_failure.py`: Chaos test for simulating Redis failures.

- **F-405: Dynamic Cost-Routing**
  - `services/ai_router.py`: Intelligent provider router with cost-based routing and auto-failover.
  - Provider scoring based on cost, latency, and quality.

- **F-401: Materialized Balance View**
  - `database/views/user_balance.sql`: Materialized view for fast balance lookups.
  - `database/refresh_balance.py`: Logic for refreshing stale balances.
  - Trigger-based real-time updates to balance cache.

- **Priority Queues**
  - `services/priority_queue.py`: Multi-level priority queue with Redis sorted sets.
  - `CRITICAL`, `HIGH`, `NORMAL`, `LOW` priority levels.

- **Multi-Region Setup**
  - `runbooks/multi_region_setup.md`: Guide for setting up multi-region deployment.
  - Scripts for failover, health checks, and replication monitoring.

- **Dynamic Pricing & Margin Alerts**
  - `services/dynamic_pricing.py`: Dynamic pricing engine with cost-plus pricing, peak/off-peak adjustments, and user tier discounts.
  - Proactive margin alerts for low-margin services.

## Changed

- **Database:**
  - Added `user_balance_cache` table for materialized balance view.
  - Added triggers for real-time balance updates.

- **Configuration:**
  - New `.env` variables for multi-region, S3, and dynamic pricing.

- **Workers:**
  - Integrated with priority queues for job processing.
  - Integrated with AI router for provider selection.

- **Admin Panel:**
  - Added `/admin/slo` for SLO dashboard.
  - Added `/admin/pricing` for dynamic pricing report.
  - Added `/admin/failover` for manual DR failover.

## Fixed

- **F-401:** Mitigated stale balance reads with materialized view and refresh strategy.
- **F-402:** Implemented SLO/SLA monitoring to track and alert on performance issues.
- **F-403:** Established clear DR procedures and automated backups to minimize data loss.
- **F-404:** Validated system resilience and performance under load and chaos conditions.
- **F-405:** Optimized provider costs and improved reliability with dynamic routing.

## Removed

- Hardcoded provider selection logic (replaced by AI router).
- Simple balance calculation from ledger (replaced by materialized view).


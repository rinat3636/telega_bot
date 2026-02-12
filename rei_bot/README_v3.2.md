# REI Bot v3.2 - FULL ENTERPRISE

## Overview

This version of REI Bot has been upgraded to **FULL ENTERPRISE** readiness, with a focus on reliability, scalability, and operational excellence.

**Key Features:**
- **Financial Integrity:** Ledger-based balance, materialized views, and database constraints.
- **High Availability:** Multi-region setup with automated failover.
- **Resilience:** Priority queues, chaos testing, and SLO/SLA monitoring.
- **Economic Optimization:** Dynamic pricing, cost-based routing, and margin alerts.
- **Operational Excellence:** Comprehensive runbooks, automated backups, and DR drills.

---

## Architecture

```mermaid
graph TD
    subgraph User Facing
        Telegram --> API_Gateway[API Gateway]
    end

    subgraph Application Layer
        API_Gateway --> Handlers
        Handlers --> Guards[Guards (Rate/Cost/RBAC)]
        Guards --> Jobs_Service[Jobs Service]
    end

    subgraph Job Processing
        Jobs_Service --> Priority_Queues[Priority Queues]
        Priority_Queues --> Workers
        Workers --> AI_Router[AI Router]
        AI_Router --> AI_Providers[AI Providers]
    end

    subgraph Billing & Payments
        Jobs_Service --> Usage_Sessions[Usage Sessions]
        Usage_Sessions --> Ledger
        Payments_Webhook[Payments Webhook] --> Ledger
    end

    subgraph Data Layer
        Ledger --> Postgres_Primary[Postgres (Primary)]
        Postgres_Primary --> Postgres_Replica[Postgres (Replica)]
        Workers --> S3_Assets[S3 Assets]
        S3_Assets --> GC_Worker[GC Worker]
    end

    subgraph Observability
        Application_Layer --> Metrics[Metrics (Prometheus)]
        Metrics --> Alerts[Alerts (Alertmanager)]
        Metrics --> Dashboards[Dashboards (Grafana)]
    end
```

---

## New Features in v3.2

### F-402: SLO/SLA Monitoring
- **SLO Definitions:** `job_success_rate`, `payment_success_rate`, `job_latency_p95`.
- **Error Budgets:** Automated calculation and tracking.
- **Burn Rate Alerts:** Proactive alerts on high error rates.
- **Dashboard:** Real-time SLO compliance view.

### F-403: Disaster Recovery
- **Automated Backups:** Hourly backups of database and assets to S3.
- **Cold Restore Script:** `scripts/restore.sh` for full system recovery.
- **DR Runbook:** Step-by-step procedures for various failure scenarios.
- **DR Drills:** Quarterly drills to validate RTO/RPO.

### F-404: Load & Chaos Testing
- **Load Testing (k6):** Simulates 100 concurrent users with `parallel_jobs.js`.
- **Chaos Testing (Python):** `redis_failure.py` simulates Redis connection loss and restart.
- **Resilience Validation:** Ensures graceful degradation and recovery.

### F-405: Dynamic Cost-Routing
- **AI Router:** Selects best provider based on cost, latency, and quality.
- **Auto-Failover:** Automatically retries with fallback providers.
- **Provider Scoring:** Dynamically scores providers to optimize for cost and performance.

### F-401: Materialized Balance View
- **Cached Balances:** `user_balance_cache` table for fast balance lookups.
- **Real-time Updates:** Trigger-based updates on ledger inserts.
- **Stale Refresh:** Scheduled task to refresh stale balances.
- **Integrity Verification:** `verify_balance_integrity()` to ensure consistency.

### Priority Queues
- **Multi-level Priority:** `CRITICAL`, `HIGH`, `NORMAL`, `LOW`.
- **FIFO within Priority:** Ensures fairness.
- **Redis-based:** Scalable and distributed-safe.

### Multi-Region Setup
- **Primary/Secondary Regions:** Hot standby with read replicas.
- **S3 Cross-Region Replication:** For backups and assets.
- **Automated Failover:** Health checks and failover script.

### Dynamic Pricing & Margin Alerts
- **Cost-plus Pricing:** With target margins.
- **Peak/Off-peak Pricing:** Adjusts prices based on demand.
- **User Tier Discounts:** For `BASIC`, `PRO`, `ENTERPRISE` tiers.
- **Margin Alerts:** Proactive alerts on low margins.

---

## Getting Started

### Prerequisites
- Docker & Docker Compose
- Python 3.11+
- Redis
- PostgreSQL
- AWS CLI (for multi-region setup)
- k6 (for load testing)

### Installation

```bash
# 1. Clone repository
git clone <repo_url>
cd rei_bot

# 2. Install dependencies
pip3 install -r requirements.txt

# 3. Configure environment
cp .env.example .env
# Edit .env with your settings

# 4. Run database migrations
python3 database/migrate.py

# 5. Start services
docker-compose up -d
```

### Running Tests

```bash
# Unit tests
pytest

# Load tests
k6 run --vus 100 --duration 5m tests/load/parallel_jobs.js

# Chaos tests
python3 tests/chaos/redis_failure.py
```

---

## Runbooks

- `runbooks/disaster_recovery.md`: Procedures for recovering from failures.
- `runbooks/multi_region_setup.md`: Guide for setting up multi-region deployment.
- `runbooks/onboarding.md`: Guide for new engineers.

---

## Monitoring

- **Prometheus:** `http://localhost:9090`
- **Grafana:** `http://localhost:3000` (import dashboards from `dashboards/`)
- **Alertmanager:** `http://localhost:9093`

---

## Known Limitations

- **Cold Start Latency:** First request to a new worker may have higher latency.
- **Database Scaling:** For >1M users, consider sharding or a managed DB like CockroachDB.
- **Security:** Requires regular security audits and penetration testing.

---

## Version History

| Version | Date | Key Features |
|---------|------|--------------|
| 3.2 | 2026-02-12 | FULL ENTERPRISE: Multi-region, SLOs, DR, Dynamic Pricing |
| 3.1 | 2026-02-12 | Enterprise Ready: GC, Metrics, Cost-caps, Admin |
| 3.0 | 2026-02-12 | Production Ready: Ledger, Queue, Replay Protection |
| 2.0 | 2026-02-12 | Beta Prod: Basic fixes |
| 1.0 | 2026-02-12 | Initial version |

---

## Contact

- **On-Call Engineer:** See PagerDuty schedule
- **System Admin:** See `runbooks/disaster_recovery.md`
- **Support:** `support@rei-bot.com`

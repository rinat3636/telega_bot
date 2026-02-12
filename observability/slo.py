"""
Service Level Objectives (SLO) definitions and tracking
"""
import time
from typing import Dict, List, Optional
from dataclasses import dataclass
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


@dataclass
class SLO:
    """Service Level Objective definition"""
    name: str
    description: str
    target: float  # Target percentage (e.g., 99.5 for 99.5%)
    window: int  # Time window in seconds (e.g., 2592000 for 30 days)
    metric_name: str  # Prometheus metric name
    
    def error_budget(self) -> float:
        """Calculate error budget (100 - target)"""
        return 100.0 - self.target
    
    def allowed_failures(self, total_requests: int) -> int:
        """Calculate allowed failures based on error budget"""
        return int(total_requests * (self.error_budget() / 100.0))


# ==================== SLO DEFINITIONS ====================

SLOS: Dict[str, SLO] = {
    "job_success_rate": SLO(
        name="job_success_rate",
        description="Percentage of successfully completed jobs",
        target=99.5,  # 99.5% success rate
        window=30 * 24 * 3600,  # 30 days
        metric_name="jobs_completed_total"
    ),
    
    "payment_success_rate": SLO(
        name="payment_success_rate",
        description="Percentage of successful payment transactions",
        target=99.9,  # 99.9% success rate
        window=30 * 24 * 3600,  # 30 days
        metric_name="payments_completed_total"
    ),
    
    "job_latency_p95": SLO(
        name="job_latency_p95",
        description="95th percentile job completion latency",
        target=180.0,  # 180 seconds
        window=24 * 3600,  # 24 hours
        metric_name="job_duration_seconds"
    ),
    
    "webhook_processing_time": SLO(
        name="webhook_processing_time",
        description="Webhook processing time",
        target=5.0,  # 5 seconds
        window=24 * 3600,  # 24 hours
        metric_name="webhook_processing_seconds"
    ),
    
    "api_availability": SLO(
        name="api_availability",
        description="API endpoint availability",
        target=99.95,  # 99.95% uptime
        window=30 * 24 * 3600,  # 30 days
        metric_name="api_requests_total"
    )
}


# ==================== SLO TRACKER ====================

class SLOTracker:
    """Track SLO compliance and error budget consumption"""
    
    def __init__(self):
        self.measurements: Dict[str, List[Dict]] = {slo_name: [] for slo_name in SLOS}
    
    def record_success(self, slo_name: str):
        """Record successful operation"""
        if slo_name not in SLOS:
            logger.warning(f"Unknown SLO: {slo_name}")
            return
        
        self.measurements[slo_name].append({
            "timestamp": time.time(),
            "success": True
        })
    
    def record_failure(self, slo_name: str, reason: Optional[str] = None):
        """Record failed operation"""
        if slo_name not in SLOS:
            logger.warning(f"Unknown SLO: {slo_name}")
            return
        
        self.measurements[slo_name].append({
            "timestamp": time.time(),
            "success": False,
            "reason": reason
        })
        
        logger.warning(f"SLO violation: {slo_name}, reason: {reason}")
    
    def get_compliance(self, slo_name: str, window_seconds: Optional[int] = None) -> Dict:
        """
        Calculate SLO compliance for given time window
        
        Returns:
            {
                "total": int,
                "success": int,
                "failure": int,
                "success_rate": float,
                "target": float,
                "compliant": bool,
                "error_budget_consumed": float
            }
        """
        if slo_name not in SLOS:
            return {}
        
        slo = SLOS[slo_name]
        window = window_seconds or slo.window
        cutoff_time = time.time() - window
        
        # Filter measurements within window
        recent = [m for m in self.measurements[slo_name] if m["timestamp"] >= cutoff_time]
        
        if not recent:
            return {
                "total": 0,
                "success": 0,
                "failure": 0,
                "success_rate": 100.0,
                "target": slo.target,
                "compliant": True,
                "error_budget_consumed": 0.0
            }
        
        total = len(recent)
        success = sum(1 for m in recent if m["success"])
        failure = total - success
        success_rate = (success / total) * 100.0
        
        # Calculate error budget consumption
        error_budget = slo.error_budget()
        actual_error_rate = 100.0 - success_rate
        error_budget_consumed = (actual_error_rate / error_budget) * 100.0 if error_budget > 0 else 0.0
        
        return {
            "total": total,
            "success": success,
            "failure": failure,
            "success_rate": success_rate,
            "target": slo.target,
            "compliant": success_rate >= slo.target,
            "error_budget_consumed": min(error_budget_consumed, 100.0),
            "error_budget_remaining": max(100.0 - error_budget_consumed, 0.0)
        }
    
    def get_all_compliance(self) -> Dict[str, Dict]:
        """Get compliance for all SLOs"""
        return {
            slo_name: self.get_compliance(slo_name)
            for slo_name in SLOS
        }
    
    def check_burn_rate(self, slo_name: str) -> Dict:
        """
        Check error budget burn rate
        
        Returns:
            {
                "burn_rate": float,  # Multiplier (1x = normal, 2x = double speed)
                "alert_level": str,  # "none", "warning", "critical"
                "time_to_exhaustion": int  # Seconds until budget exhausted
            }
        """
        if slo_name not in SLOS:
            return {}
        
        slo = SLOS[slo_name]
        
        # Calculate burn rate over last hour vs. monthly target
        hourly_compliance = self.get_compliance(slo_name, window_seconds=3600)
        monthly_compliance = self.get_compliance(slo_name, window_seconds=slo.window)
        
        if hourly_compliance["total"] == 0:
            return {
                "burn_rate": 0.0,
                "alert_level": "none",
                "time_to_exhaustion": float('inf')
            }
        
        # Burn rate = (hourly error rate) / (monthly error budget / hours in month)
        hourly_error_rate = 100.0 - hourly_compliance["success_rate"]
        expected_hourly_error_rate = slo.error_budget() / (slo.window / 3600)
        
        burn_rate = hourly_error_rate / expected_hourly_error_rate if expected_hourly_error_rate > 0 else 0.0
        
        # Calculate time to exhaustion
        if burn_rate > 0:
            remaining_budget = monthly_compliance["error_budget_remaining"]
            time_to_exhaustion = (remaining_budget / burn_rate) * 3600  # seconds
        else:
            time_to_exhaustion = float('inf')
        
        # Determine alert level
        if burn_rate >= 10.0:
            alert_level = "critical"
        elif burn_rate >= 5.0:
            alert_level = "warning"
        elif burn_rate >= 2.0:
            alert_level = "info"
        else:
            alert_level = "none"
        
        return {
            "burn_rate": burn_rate,
            "alert_level": alert_level,
            "time_to_exhaustion": int(time_to_exhaustion)
        }
    
    def cleanup_old_measurements(self):
        """Remove measurements older than max window"""
        max_window = max(slo.window for slo in SLOS.values())
        cutoff_time = time.time() - max_window
        
        for slo_name in self.measurements:
            self.measurements[slo_name] = [
                m for m in self.measurements[slo_name]
                if m["timestamp"] >= cutoff_time
            ]


# ==================== GLOBAL TRACKER ====================

slo_tracker = SLOTracker()


# ==================== HELPER FUNCTIONS ====================

def track_job_success():
    """Track successful job completion"""
    slo_tracker.record_success("job_success_rate")


def track_job_failure(reason: str):
    """Track failed job"""
    slo_tracker.record_failure("job_success_rate", reason)


def track_payment_success():
    """Track successful payment"""
    slo_tracker.record_success("payment_success_rate")


def track_payment_failure(reason: str):
    """Track failed payment"""
    slo_tracker.record_failure("payment_success_rate", reason)


def track_api_success():
    """Track successful API request"""
    slo_tracker.record_success("api_availability")


def track_api_failure(reason: str):
    """Track failed API request"""
    slo_tracker.record_failure("api_availability", reason)


def get_slo_dashboard() -> Dict:
    """Get SLO dashboard data"""
    compliance = slo_tracker.get_all_compliance()
    
    dashboard = {
        "timestamp": datetime.now().isoformat(),
        "slos": {}
    }
    
    for slo_name, slo in SLOS.items():
        comp = compliance[slo_name]
        burn = slo_tracker.check_burn_rate(slo_name)
        
        dashboard["slos"][slo_name] = {
            "description": slo.description,
            "target": slo.target,
            "compliance": comp,
            "burn_rate": burn,
            "status": "healthy" if comp.get("compliant", True) else "violated"
        }
    
    return dashboard

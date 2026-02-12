"""
Dynamic Pricing Engine with Margin Alerts

Adjusts prices based on:
- Provider costs
- Demand
- Time of day
- User tier
"""
import time
import logging
from typing import Dict, Optional
from dataclasses import dataclass
from datetime import datetime, time as dt_time
from enum import Enum

logger = logging.getLogger(__name__)


class UserTier(Enum):
    """User tier levels"""
    FREE = "free"
    BASIC = "basic"
    PRO = "pro"
    ENTERPRISE = "enterprise"


@dataclass
class PricingRule:
    """Pricing rule configuration"""
    base_cost: float  # Provider cost
    margin_target: float  # Target margin (e.g., 0.3 for 30%)
    margin_min: float  # Minimum acceptable margin
    peak_multiplier: float  # Multiplier during peak hours
    off_peak_discount: float  # Discount during off-peak hours


class DynamicPricingEngine:
    """
    Dynamic pricing engine with margin optimization
    
    Features:
    - Cost-plus pricing with target margins
    - Peak/off-peak pricing
    - User tier discounts
    - Margin alerts
    """
    
    def __init__(self):
        self.rules: Dict[str, PricingRule] = {}
        self.margin_alerts: list = []
        self._initialize_rules()
    
    def _initialize_rules(self):
        """Initialize default pricing rules"""
        
        # Image Generation
        self.rules["image_generation"] = PricingRule(
            base_cost=30.0,  # Provider cost
            margin_target=0.4,  # 40% target margin
            margin_min=0.2,  # 20% minimum margin
            peak_multiplier=1.2,  # 20% more during peak
            off_peak_discount=0.9  # 10% discount off-peak
        )
        
        # Image Edit
        self.rules["image_edit"] = PricingRule(
            base_cost=25.0,
            margin_target=0.4,
            margin_min=0.2,
            peak_multiplier=1.2,
            off_peak_discount=0.9
        )
        
        # Video Generation (5 sec)
        self.rules["video_5sec"] = PricingRule(
            base_cost=60.0,
            margin_target=0.35,
            margin_min=0.15,
            peak_multiplier=1.3,
            off_peak_discount=0.85
        )
        
        # Video Generation (10 sec)
        self.rules["video_10sec"] = PricingRule(
            base_cost=120.0,
            margin_target=0.35,
            margin_min=0.15,
            peak_multiplier=1.3,
            off_peak_discount=0.85
        )
    
    def calculate_price(
        self,
        service_type: str,
        user_tier: UserTier = UserTier.FREE,
        current_time: Optional[datetime] = None
    ) -> Dict:
        """
        Calculate dynamic price for service
        
        Args:
            service_type: Type of service
            user_tier: User's tier level
            current_time: Current time (for peak/off-peak)
        
        Returns:
            {
                "price": float,
                "base_cost": float,
                "margin": float,
                "margin_percent": float,
                "breakdown": dict
            }
        """
        if service_type not in self.rules:
            logger.error(f"Unknown service type: {service_type}")
            return {}
        
        rule = self.rules[service_type]
        current_time = current_time or datetime.now()
        
        # 1. Base price = cost + target margin
        base_price = rule.base_cost * (1 + rule.margin_target)
        
        # 2. Apply peak/off-peak multiplier
        if self._is_peak_hour(current_time):
            time_multiplier = rule.peak_multiplier
            time_label = "peak"
        else:
            time_multiplier = rule.off_peak_discount
            time_label = "off-peak"
        
        price_after_time = base_price * time_multiplier
        
        # 3. Apply user tier discount
        tier_discount = self._get_tier_discount(user_tier)
        final_price = price_after_time * (1 - tier_discount)
        
        # 4. Calculate actual margin
        margin = final_price - rule.base_cost
        margin_percent = (margin / final_price) * 100 if final_price > 0 else 0
        
        # 5. Check margin alert
        if margin_percent < rule.margin_min * 100:
            self._trigger_margin_alert(service_type, margin_percent, rule.margin_min * 100)
        
        return {
            "price": round(final_price, 2),
            "base_cost": rule.base_cost,
            "margin": round(margin, 2),
            "margin_percent": round(margin_percent, 2),
            "breakdown": {
                "base_price": round(base_price, 2),
                "time_multiplier": time_multiplier,
                "time_label": time_label,
                "tier_discount": tier_discount,
                "tier_label": user_tier.value
            }
        }
    
    def _is_peak_hour(self, current_time: datetime) -> bool:
        """
        Check if current time is peak hour
        
        Peak hours: 9 AM - 9 PM (Moscow time)
        """
        hour = current_time.hour
        return 9 <= hour < 21
    
    def _get_tier_discount(self, tier: UserTier) -> float:
        """Get discount for user tier"""
        discounts = {
            UserTier.FREE: 0.0,  # No discount
            UserTier.BASIC: 0.05,  # 5% discount
            UserTier.PRO: 0.10,  # 10% discount
            UserTier.ENTERPRISE: 0.15  # 15% discount
        }
        return discounts.get(tier, 0.0)
    
    def _trigger_margin_alert(self, service_type: str, actual_margin: float, min_margin: float):
        """Trigger margin alert"""
        alert = {
            "timestamp": time.time(),
            "service_type": service_type,
            "actual_margin": actual_margin,
            "min_margin": min_margin,
            "severity": "warning" if actual_margin > 0 else "critical"
        }
        
        self.margin_alerts.append(alert)
        
        logger.warning(
            f"Margin alert: {service_type} margin={actual_margin:.2f}% "
            f"(min={min_margin:.2f}%)"
        )
    
    def update_base_cost(self, service_type: str, new_cost: float):
        """
        Update provider base cost
        
        Triggers repricing
        """
        if service_type not in self.rules:
            logger.error(f"Unknown service type: {service_type}")
            return
        
        old_cost = self.rules[service_type].base_cost
        self.rules[service_type].base_cost = new_cost
        
        logger.info(
            f"Updated {service_type} base cost: {old_cost} -> {new_cost}"
        )
    
    def get_margin_report(self) -> Dict:
        """
        Get margin report for all services
        
        Returns:
            {
                "services": {...},
                "alerts": [...],
                "summary": {...}
            }
        """
        services = {}
        total_margin = 0.0
        
        for service_type, rule in self.rules.items():
            pricing = self.calculate_price(service_type)
            services[service_type] = {
                "price": pricing["price"],
                "cost": pricing["base_cost"],
                "margin": pricing["margin"],
                "margin_percent": pricing["margin_percent"],
                "target_margin": rule.margin_target * 100,
                "min_margin": rule.margin_min * 100,
                "status": "healthy" if pricing["margin_percent"] >= rule.margin_min * 100 else "low"
            }
            total_margin += pricing["margin_percent"]
        
        avg_margin = total_margin / len(services) if services else 0.0
        
        return {
            "services": services,
            "alerts": self.margin_alerts[-10:],  # Last 10 alerts
            "summary": {
                "average_margin": round(avg_margin, 2),
                "total_alerts": len(self.margin_alerts),
                "services_count": len(services)
            }
        }
    
    def simulate_price_change(
        self,
        service_type: str,
        cost_change_percent: float
    ) -> Dict:
        """
        Simulate impact of cost change
        
        Args:
            service_type: Service to simulate
            cost_change_percent: Cost change (e.g., 10 for +10%)
        
        Returns:
            Before/after comparison
        """
        if service_type not in self.rules:
            return {}
        
        rule = self.rules[service_type]
        
        # Current pricing
        current = self.calculate_price(service_type)
        
        # Simulated pricing
        new_cost = rule.base_cost * (1 + cost_change_percent / 100)
        old_cost = rule.base_cost
        rule.base_cost = new_cost
        
        simulated = self.calculate_price(service_type)
        
        # Restore original cost
        rule.base_cost = old_cost
        
        return {
            "service_type": service_type,
            "cost_change": f"{cost_change_percent:+.1f}%",
            "before": {
                "price": current["price"],
                "margin": current["margin_percent"]
            },
            "after": {
                "price": simulated["price"],
                "margin": simulated["margin_percent"]
            },
            "impact": {
                "price_change": simulated["price"] - current["price"],
                "margin_change": simulated["margin_percent"] - current["margin_percent"]
            }
        }


# Global pricing engine
pricing_engine = DynamicPricingEngine()


# Helper functions

def get_current_price(service_type: str, user_tier: UserTier = UserTier.FREE) -> float:
    """Get current price for service"""
    result = pricing_engine.calculate_price(service_type, user_tier)
    return result.get("price", 0.0)


def get_margin_status() -> Dict:
    """Get current margin status"""
    return pricing_engine.get_margin_report()

"""
Dynamic AI Provider Router with Cost-based Routing
"""
import time
import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class ProviderType(Enum):
    """AI Provider types"""
    IMAGE_GENERATION = "image_generation"
    IMAGE_EDIT = "image_edit"
    VIDEO_GENERATION = "video_generation"


@dataclass
class ProviderConfig:
    """Provider configuration"""
    name: str
    type: ProviderType
    cost_per_request: float  # Base cost in rubles
    avg_latency: float  # Average latency in seconds
    success_rate: float  # Success rate (0.0 - 1.0)
    priority: int  # Priority (1 = highest)
    enabled: bool = True
    max_retries: int = 3


class AIRouter:
    """
    Intelligent AI provider router with:
    - Cost-based routing
    - Latency-based fallback
    - Quality scoring
    - Auto-failover
    """
    
    def __init__(self):
        self.providers: Dict[str, ProviderConfig] = {}
        self.provider_stats: Dict[str, Dict] = {}
        self._initialize_providers()
    
    def _initialize_providers(self):
        """Initialize provider configurations"""
        
        # Image Generation Providers
        self.register_provider(ProviderConfig(
            name="nano_banana_pro",
            type=ProviderType.IMAGE_GENERATION,
            cost_per_request=50.0,
            avg_latency=30.0,
            success_rate=0.995,
            priority=1
        ))
        
        self.register_provider(ProviderConfig(
            name="nano_banana_standard",
            type=ProviderType.IMAGE_GENERATION,
            cost_per_request=30.0,
            avg_latency=45.0,
            success_rate=0.98,
            priority=2
        ))
        
        # Video Generation Providers
        self.register_provider(ProviderConfig(
            name="kling_3.0",
            type=ProviderType.VIDEO_GENERATION,
            cost_per_request=100.0,
            avg_latency=120.0,
            success_rate=0.99,
            priority=1
        ))
        
        self.register_provider(ProviderConfig(
            name="kling_2.6",
            type=ProviderType.VIDEO_GENERATION,
            cost_per_request=80.0,
            avg_latency=90.0,
            success_rate=0.97,
            priority=2
        ))
    
    def register_provider(self, config: ProviderConfig):
        """Register a provider"""
        self.providers[config.name] = config
        self.provider_stats[config.name] = {
            "total_requests": 0,
            "successful_requests": 0,
            "failed_requests": 0,
            "total_latency": 0.0,
            "total_cost": 0.0,
            "last_failure": None
        }
        logger.info(f"Registered provider: {config.name}")
    
    def select_provider(
        self,
        provider_type: ProviderType,
        max_cost: Optional[float] = None,
        max_latency: Optional[float] = None,
        quality_threshold: float = 0.95
    ) -> Optional[ProviderConfig]:
        """
        Select best provider based on cost, latency, and quality
        
        Args:
            provider_type: Type of provider needed
            max_cost: Maximum acceptable cost
            max_latency: Maximum acceptable latency (SLA requirement)
            quality_threshold: Minimum success rate
        
        Returns:
            Selected provider config or None
        """
        # Filter providers by type and enabled status
        candidates = [
            p for p in self.providers.values()
            if p.type == provider_type and p.enabled
        ]
        
        if not candidates:
            logger.error(f"No providers available for {provider_type}")
            return None
        
        # Apply filters
        if max_cost:
            candidates = [p for p in candidates if p.cost_per_request <= max_cost]
        
        if max_latency:
            candidates = [p for p in candidates if p.avg_latency <= max_latency]
        
        candidates = [p for p in candidates if p.success_rate >= quality_threshold]
        
        if not candidates:
            logger.warning(f"No providers match criteria for {provider_type}")
            return None
        
        # Score providers: lower is better
        # Score = (cost_weight * normalized_cost) + (latency_weight * normalized_latency) - (quality_weight * success_rate)
        cost_weight = 0.5
        latency_weight = 0.3
        quality_weight = 0.2
        
        max_cost_val = max(p.cost_per_request for p in candidates)
        max_latency_val = max(p.avg_latency for p in candidates)
        
        scored_providers = []
        for provider in candidates:
            normalized_cost = provider.cost_per_request / max_cost_val if max_cost_val > 0 else 0
            normalized_latency = provider.avg_latency / max_latency_val if max_latency_val > 0 else 0
            
            score = (
                cost_weight * normalized_cost +
                latency_weight * normalized_latency -
                quality_weight * provider.success_rate
            )
            
            scored_providers.append((score, provider))
        
        # Sort by score (lower is better) and priority
        scored_providers.sort(key=lambda x: (x[0], x[1].priority))
        
        selected = scored_providers[0][1]
        logger.info(f"Selected provider: {selected.name} (cost={selected.cost_per_request}, latency={selected.avg_latency})")
        
        return selected
    
    def execute_with_fallback(
        self,
        provider_type: ProviderType,
        execute_fn,
        max_retries: int = 3,
        **kwargs
    ) -> Tuple[bool, Optional[any], Optional[str]]:
        """
        Execute request with automatic fallback
        
        Args:
            provider_type: Type of provider
            execute_fn: Function to execute (receives provider_name as first arg)
            max_retries: Maximum retry attempts
            **kwargs: Additional arguments for select_provider
        
        Returns:
            (success, result, error_message)
        """
        attempts = 0
        tried_providers = set()
        
        while attempts < max_retries:
            attempts += 1
            
            # Select provider (excluding already tried ones)
            provider = self.select_provider(provider_type, **kwargs)
            
            if not provider or provider.name in tried_providers:
                logger.warning(f"No more providers to try (attempt {attempts}/{max_retries})")
                break
            
            tried_providers.add(provider.name)
            
            # Execute request
            start_time = time.time()
            
            try:
                logger.info(f"Attempt {attempts}: Using provider {provider.name}")
                result = execute_fn(provider.name)
                
                # Record success
                latency = time.time() - start_time
                self._record_success(provider.name, latency, provider.cost_per_request)
                
                return True, result, None
            
            except Exception as e:
                # Record failure
                latency = time.time() - start_time
                self._record_failure(provider.name, str(e))
                
                logger.error(f"Provider {provider.name} failed: {e}")
                
                # Continue to next provider
                continue
        
        # All attempts failed
        error_msg = f"All providers failed after {attempts} attempts"
        logger.error(error_msg)
        return False, None, error_msg
    
    def _record_success(self, provider_name: str, latency: float, cost: float):
        """Record successful request"""
        stats = self.provider_stats[provider_name]
        stats["total_requests"] += 1
        stats["successful_requests"] += 1
        stats["total_latency"] += latency
        stats["total_cost"] += cost
        
        # Update provider success rate
        provider = self.providers[provider_name]
        provider.success_rate = stats["successful_requests"] / stats["total_requests"]
        provider.avg_latency = stats["total_latency"] / stats["total_requests"]
    
    def _record_failure(self, provider_name: str, error: str):
        """Record failed request"""
        stats = self.provider_stats[provider_name]
        stats["total_requests"] += 1
        stats["failed_requests"] += 1
        stats["last_failure"] = {
            "timestamp": time.time(),
            "error": error
        }
        
        # Update provider success rate
        provider = self.providers[provider_name]
        if stats["total_requests"] > 0:
            provider.success_rate = stats["successful_requests"] / stats["total_requests"]
        
        # Disable provider if success rate drops too low
        if provider.success_rate < 0.8 and stats["total_requests"] > 10:
            logger.warning(f"Disabling provider {provider_name} due to low success rate: {provider.success_rate}")
            provider.enabled = False
    
    def get_provider_stats(self) -> Dict:
        """Get statistics for all providers"""
        return {
            name: {
                **stats,
                "config": {
                    "cost": self.providers[name].cost_per_request,
                    "avg_latency": self.providers[name].avg_latency,
                    "success_rate": self.providers[name].success_rate,
                    "enabled": self.providers[name].enabled
                }
            }
            for name, stats in self.provider_stats.items()
        }
    
    def reset_provider(self, provider_name: str):
        """Reset provider (re-enable and clear stats)"""
        if provider_name in self.providers:
            self.providers[provider_name].enabled = True
            self.provider_stats[provider_name] = {
                "total_requests": 0,
                "successful_requests": 0,
                "failed_requests": 0,
                "total_latency": 0.0,
                "total_cost": 0.0,
                "last_failure": None
            }
            logger.info(f"Reset provider: {provider_name}")


# Global router instance
ai_router = AIRouter()


# Helper functions
def route_image_generation(execute_fn, max_cost: Optional[float] = None):
    """Route image generation request"""
    return ai_router.execute_with_fallback(
        ProviderType.IMAGE_GENERATION,
        execute_fn,
        max_cost=max_cost,
        max_latency=180.0  # SLA requirement
    )


def route_video_generation(execute_fn, max_cost: Optional[float] = None):
    """Route video generation request"""
    return ai_router.execute_with_fallback(
        ProviderType.VIDEO_GENERATION,
        execute_fn,
        max_cost=max_cost,
        max_latency=180.0  # SLA requirement
    )

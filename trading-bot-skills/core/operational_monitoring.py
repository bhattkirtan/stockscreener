"""
Operational Monitoring
Tracks system health, API performance, and operational metrics beyond P&L.
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Deque
from collections import deque
import asyncio
import time


@dataclass
class LatencyMetric:
    """Track latency for an operation"""
    operation: str
    duration_ms: float
    timestamp: datetime
    success: bool


@dataclass
class HealthCheck:
    """Health check result"""
    component: str
    status: str  # 'HEALTHY', 'DEGRADED', 'UNHEALTHY'
    last_check: datetime
    message: Optional[str] = None
    details: Dict = field(default_factory=dict)


class WebSocketHealthMonitor:
    """
    Monitor WebSocket connection health.
    
    Tracks:
    - Connection uptime
    - Reconnection attempts
    - Message latency
    - Missed heartbeats
    """
    
    def __init__(self, heartbeat_interval_seconds: int = 30, 
                 missed_heartbeat_threshold: int = 3):
        """
        Initialize WebSocket health monitor.
        
        Args:
            heartbeat_interval_seconds: Expected time between heartbeats
            missed_heartbeat_threshold: Number of missed heartbeats before UNHEALTHY
        """
        self.heartbeat_interval = heartbeat_interval_seconds
        self.missed_threshold = missed_heartbeat_threshold
        
        # Connection tracking
        self.is_connected = False
        self.connected_at: Optional[datetime] = None
        self.disconnect_count = 0
        self.last_disconnect: Optional[datetime] = None
        
        # Heartbeat tracking
        self.last_heartbeat: Optional[datetime] = None
        self.consecutive_missed = 0
        self.total_missed = 0
        
        # Message tracking
        self.messages_received = 0
        self.last_message: Optional[datetime] = None
    
    def on_connect(self) -> None:
        """Record WebSocket connection"""
        self.is_connected = True
        self.connected_at = datetime.now()
        self.consecutive_missed = 0
        print(f"✅ WebSocket connected at {self.connected_at}")
    
    def on_disconnect(self) -> None:
        """Record WebSocket disconnection"""
        self.is_connected = False
        self.disconnect_count += 1
        self.last_disconnect = datetime.now()
        
        if self.connected_at:
            uptime = (self.last_disconnect - self.connected_at).total_seconds()
            print(f"⚠️ WebSocket disconnected (uptime: {uptime:.1f}s)")
    
    def on_heartbeat(self) -> None:
        """Record heartbeat received"""
        self.last_heartbeat = datetime.now()
        self.consecutive_missed = 0
    
    def on_message(self) -> None:
        """Record message received"""
        self.messages_received += 1
        self.last_message = datetime.now()
    
    def check_heartbeat(self) -> bool:
        """
        Check if heartbeat is within expected interval.
        
        Returns:
            True if healthy, False if missed
        """
        if not self.last_heartbeat:
            return True  # No heartbeat expected yet
        
        elapsed = (datetime.now() - self.last_heartbeat).total_seconds()
        
        if elapsed > self.heartbeat_interval * 1.5:  # 50% grace period
            self.consecutive_missed += 1
            self.total_missed += 1
            print(f"⚠️ Heartbeat missed (elapsed: {elapsed:.1f}s, consecutive: {self.consecutive_missed})")
            return False
        
        return True
    
    def get_health(self) -> HealthCheck:
        """Get WebSocket health status"""
        if not self.is_connected:
            return HealthCheck(
                component='websocket',
                status='UNHEALTHY',
                last_check=datetime.now(),
                message='WebSocket disconnected',
                details={
                    'disconnect_count': self.disconnect_count,
                    'last_disconnect': self.last_disconnect.isoformat() if self.last_disconnect else None
                }
            )
        
        # Check heartbeat
        heartbeat_ok = self.check_heartbeat()
        
        if self.consecutive_missed >= self.missed_threshold:
            return HealthCheck(
                component='websocket',
                status='UNHEALTHY',
                last_check=datetime.now(),
                message=f'Missed {self.consecutive_missed} consecutive heartbeats',
                details={
                    'consecutive_missed': self.consecutive_missed,
                    'total_missed': self.total_missed,
                    'last_heartbeat': self.last_heartbeat.isoformat() if self.last_heartbeat else None
                }
            )
        
        # Check message staleness
        if self.last_message:
            staleness = (datetime.now() - self.last_message).total_seconds()
            if staleness > 300:  # 5 minutes
                return HealthCheck(
                    component='websocket',
                    status='DEGRADED',
                    last_check=datetime.now(),
                    message=f'No messages for {staleness:.1f}s',
                    details={
                        'last_message': self.last_message.isoformat(),
                        'messages_received': self.messages_received
                    }
                )
        
        # All checks passed
        uptime = (datetime.now() - self.connected_at).total_seconds() if self.connected_at else 0
        
        return HealthCheck(
            component='websocket',
            status='HEALTHY',
            last_check=datetime.now(),
            message=f'Connected for {uptime:.1f}s',
            details={
                'uptime_seconds': uptime,
                'messages_received': self.messages_received,
                'disconnect_count': self.disconnect_count
            }
        )


class APILatencyMonitor:
    """
    Monitor API call latency and performance.
    
    Tracks:
    - Request/response times
    - Success/failure rates
    - Slow queries
    - Error patterns
    """
    
    def __init__(self, window_size: int = 100, slow_threshold_ms: float = 1000):
        """
        Initialize API latency monitor.
        
        Args:
            window_size: Number of recent requests to track
            slow_threshold_ms: Latency threshold for "slow" classification
        """
        self.window_size = window_size
        self.slow_threshold = slow_threshold_ms
        
        # Recent latency data (rolling window)
        self.latencies: Deque[LatencyMetric] = deque(maxlen=window_size)
        
        # Per-operation tracking
        self.operation_stats: Dict[str, Dict] = {}
    
    def record_request(self, operation: str, duration_ms: float, success: bool) -> None:
        """
        Record API request completion.
        
        Args:
            operation: Operation name (e.g., 'place_order', 'get_positions')
            duration_ms: Request duration in milliseconds
            success: Whether request succeeded
        """
        metric = LatencyMetric(
            operation=operation,
            duration_ms=duration_ms,
            timestamp=datetime.now(),
            success=success
        )
        
        self.latencies.append(metric)
        
        # Update operation stats
        if operation not in self.operation_stats:
            self.operation_stats[operation] = {
                'count': 0,
                'successes': 0,
                'failures': 0,
                'total_duration_ms': 0.0,
                'min_ms': float('inf'),
                'max_ms': 0.0,
                'slow_count': 0
            }
        
        stats = self.operation_stats[operation]
        stats['count'] += 1
        stats['successes' if success else 'failures'] += 1
        stats['total_duration_ms'] += duration_ms
        stats['min_ms'] = min(stats['min_ms'], duration_ms)
        stats['max_ms'] = max(stats['max_ms'], duration_ms)
        
        if duration_ms > self.slow_threshold:
            stats['slow_count'] += 1
            print(f"🐌 Slow API call: {operation} took {duration_ms:.1f}ms")
    
    def get_average_latency(self, operation: Optional[str] = None) -> float:
        """
        Get average latency.
        
        Args:
            operation: Optional filter by operation
        
        Returns:
            Average latency in milliseconds
        """
        if operation:
            metrics = [m for m in self.latencies if m.operation == operation]
        else:
            metrics = list(self.latencies)
        
        if not metrics:
            return 0.0
        
        return sum(m.duration_ms for m in metrics) / len(metrics)
    
    def get_success_rate(self, operation: Optional[str] = None) -> float:
        """
        Get success rate.
        
        Args:
            operation: Optional filter by operation
        
        Returns:
            Success rate (0.0 to 1.0)
        """
        if operation:
            metrics = [m for m in self.latencies if m.operation == operation]
        else:
            metrics = list(self.latencies)
        
        if not metrics:
            return 0.0
        
        successes = sum(1 for m in metrics if m.success)
        return successes / len(metrics)
    
    def get_p95_latency(self, operation: Optional[str] = None) -> float:
        """
        Get 95th percentile latency.
        
        Args:
            operation: Optional filter by operation
        
        Returns:
            P95 latency in milliseconds
        """
        if operation:
            latencies = [m.duration_ms for m in self.latencies if m.operation == operation]
        else:
            latencies = [m.duration_ms for m in self.latencies]
        
        if not latencies:
            return 0.0
        
        sorted_latencies = sorted(latencies)
        index = int(len(sorted_latencies) * 0.95)
        return sorted_latencies[min(index, len(sorted_latencies) - 1)]
    
    def get_health(self) -> HealthCheck:
        """Get API health status"""
        if not self.latencies:
            return HealthCheck(
                component='api',
                status='HEALTHY',
                last_check=datetime.now(),
                message='No API calls yet'
            )
        
        avg_latency = self.get_average_latency()
        success_rate = self.get_success_rate()
        p95_latency = self.get_p95_latency()
        
        # Check for issues
        if success_rate < 0.9:  # Less than 90% success
            return HealthCheck(
                component='api',
                status='UNHEALTHY',
                last_check=datetime.now(),
                message=f'Low success rate: {success_rate:.1%}',
                details={
                    'average_latency_ms': avg_latency,
                    'success_rate': success_rate,
                    'p95_latency_ms': p95_latency
                }
            )
        
        if avg_latency > self.slow_threshold:
            return HealthCheck(
                component='api',
                status='DEGRADED',
                last_check=datetime.now(),
                message=f'High average latency: {avg_latency:.1f}ms',
                details={
                    'average_latency_ms': avg_latency,
                    'success_rate': success_rate,
                    'p95_latency_ms': p95_latency
                }
            )
        
        return HealthCheck(
            component='api',
            status='HEALTHY',
            last_check=datetime.now(),
            message=f'Average latency: {avg_latency:.1f}ms, Success: {success_rate:.1%}',
            details={
                'average_latency_ms': avg_latency,
                'success_rate': success_rate,
                'p95_latency_ms': p95_latency,
                'total_requests': len(self.latencies)
            }
        )
    
    def get_operation_stats(self) -> Dict:
        """Get per-operation statistics"""
        stats = {}
        
        for operation, data in self.operation_stats.items():
            if data['count'] > 0:
                stats[operation] = {
                    'count': data['count'],
                    'success_rate': data['successes'] / data['count'],
                    'average_ms': data['total_duration_ms'] / data['count'],
                    'min_ms': data['min_ms'],
                    'max_ms': data['max_ms'],
                    'slow_rate': data['slow_count'] / data['count']
                }
        
        return stats


class DataFreshnessMonitor:
    """
    Monitor data staleness (e.g., last candle received).
    
    Critical for detecting feed issues.
    """
    
    def __init__(self, stale_threshold_seconds: int = 600):  # 10 minutes
        """
        Initialize freshness monitor.
        
        Args:
            stale_threshold_seconds: Seconds before data considered stale
        """
        self.stale_threshold = stale_threshold_seconds
        self.last_updates: Dict[str, datetime] = {}
    
    def record_update(self, data_type: str) -> None:
        """
        Record data update.
        
        Args:
            data_type: Type of data (e.g., 'candles', 'quotes', 'positions')
        """
        self.last_updates[data_type] = datetime.now()
    
    def get_staleness(self, data_type: str) -> Optional[float]:
        """
        Get staleness in seconds.
        
        Args:
            data_type: Type of data
        
        Returns:
            Seconds since last update, or None if never updated
        """
        last_update = self.last_updates.get(data_type)
        if not last_update:
            return None
        
        return (datetime.now() - last_update).total_seconds()
    
    def is_stale(self, data_type: str) -> bool:
        """Check if data is stale"""
        staleness = self.get_staleness(data_type)
        if staleness is None:
            return True  # Never updated = stale
        
        return staleness > self.stale_threshold
    
    def get_health(self) -> HealthCheck:
        """Get data freshness health status"""
        stale_data = []
        
        for data_type, last_update in self.last_updates.items():
            staleness = (datetime.now() - last_update).total_seconds()
            if staleness > self.stale_threshold:
                stale_data.append((data_type, staleness))
        
        if stale_data:
            messages = [f"{dt}: {s:.1f}s" for dt, s in stale_data]
            return HealthCheck(
                component='data_freshness',
                status='DEGRADED',
                last_check=datetime.now(),
                message=f'Stale data: {", ".join(messages)}',
                details={dt: s for dt, s in stale_data}
            )
        
        return HealthCheck(
            component='data_freshness',
            status='HEALTHY',
            last_check=datetime.now(),
            message='All data fresh',
            details={dt: self.get_staleness(dt) for dt in self.last_updates}
        )


class OperationalMonitor:
    """
    Unified operational monitoring.
    
    Aggregates:
    - WebSocket health
    - API latency
    - Data freshness
    - System metrics
    """
    
    def __init__(self, config: Dict):
        """
        Initialize operational monitor.
        
        Args:
            config: Monitoring configuration
        """
        self.config = config
        
        # Sub-monitors
        self.websocket = WebSocketHealthMonitor(
            heartbeat_interval_seconds=config.get('heartbeat_interval_seconds', 30),
            missed_heartbeat_threshold=config.get('missed_heartbeat_threshold', 3)
        )
        
        self.api = APILatencyMonitor(
            window_size=config.get('latency_window_size', 100),
            slow_threshold_ms=config.get('slow_threshold_ms', 1000)
        )
        
        self.freshness = DataFreshnessMonitor(
            stale_threshold_seconds=config.get('stale_threshold_seconds', 600)
        )
        
        # Overall health
        self.last_health_check: Optional[datetime] = None
    
    async def run_health_checks(self) -> List[HealthCheck]:
        """
        Run all health checks.
        
        Returns:
            List of health check results
        """
        self.last_health_check = datetime.now()
        
        checks = [
            self.websocket.get_health(),
            self.api.get_health(),
            self.freshness.get_health()
        ]
        
        return checks
    
    def get_overall_status(self) -> str:
        """
        Get overall system status.
        
        Returns:
            'HEALTHY', 'DEGRADED', or 'UNHEALTHY'
        """
        checks = asyncio.run(self.run_health_checks())
        
        if any(c.status == 'UNHEALTHY' for c in checks):
            return 'UNHEALTHY'
        
        if any(c.status == 'DEGRADED' for c in checks):
            return 'DEGRADED'
        
        return 'HEALTHY'
    
    def get_metrics_summary(self) -> Dict:
        """Get comprehensive metrics summary"""
        return {
            'overall_status': self.get_overall_status(),
            'last_health_check': self.last_health_check.isoformat() if self.last_health_check else None,
            'websocket': {
                'is_connected': self.websocket.is_connected,
                'messages_received': self.websocket.messages_received,
                'disconnect_count': self.websocket.disconnect_count
            },
            'api': {
                'average_latency_ms': self.api.get_average_latency(),
                'success_rate': self.api.get_success_rate(),
                'p95_latency_ms': self.api.get_p95_latency(),
                'operations': self.api.get_operation_stats()
            },
            'data_freshness': {
                data_type: self.freshness.get_staleness(data_type)
                for data_type in self.freshness.last_updates
            }
        }


# ========== Latency Tracking Decorator ==========

def track_latency(monitor: APILatencyMonitor, operation: str):
    """
    Decorator to automatically track API call latency.
    
    Usage:
        @track_latency(monitor, 'place_order')
        async def place_order(self, ...):
            ...
    """
    def decorator(func):
        async def wrapper(*args, **kwargs):
            start = time.time()
            success = False
            
            try:
                result = await func(*args, **kwargs)
                success = True
                return result
            except Exception as e:
                raise e
            finally:
                duration_ms = (time.time() - start) * 1000
                monitor.record_request(operation, duration_ms, success)
        
        return wrapper
    return decorator

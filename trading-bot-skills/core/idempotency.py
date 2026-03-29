"""
Execution Idempotency Manager
Prevents duplicate order submissions through idempotency keys and deduplication.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, Optional, Set
import hashlib
import asyncio


@dataclass
class OrderRequest:
    """
    Idempotent order request with unique key.
    """
    # Idempotency
    idempotency_key: str
    
    # Order details
    instrument: str
    direction: str  # 'BUY' or 'SELL'
    size: float
    stop_loss: float
    take_profit: float
    
    # Metadata
    signal_timestamp: datetime
    submitted_at: Optional[datetime] = None
    deal_id: Optional[str] = None
    status: str = 'pending'  # pending, submitted, filled, rejected
    reason: Optional[str] = None
    
    @classmethod
    def create(cls, instrument: str, direction: str, size: float, 
               stop_loss: float, take_profit: float, signal_timestamp: datetime) -> 'OrderRequest':
        """
        Create order request with automatic idempotency key generation.
        
        Idempotency key format: <instrument>_<direction>_<timestamp_ms>
        This ensures same signal won't create duplicate orders.
        """
        timestamp_ms = int(signal_timestamp.timestamp() * 1000)
        idempotency_key = f"{instrument}_{direction}_{timestamp_ms}"
        
        return cls(
            idempotency_key=idempotency_key,
            instrument=instrument,
            direction=direction,
            size=size,
            stop_loss=stop_loss,
            take_profit=take_profit,
            signal_timestamp=signal_timestamp
        )


class IdempotencyManager:
    """
    Manages order idempotency and prevents duplicate submissions.
    
    Key features:
    - Idempotency key tracking (prevents duplicate orders)
    - Request deduplication (same key = same response)
    - TTL cleanup (keys expire after 24h)
    - Retry safety (same request can be retried)
    
    This is CRITICAL for preventing duplicate trades due to:
    - Network timeouts
    - Retry logic
    - Websocket reconnects
    - Bot restarts
    """
    
    def __init__(self, ttl_hours: int = 24):
        """
        Initialize idempotency manager.
        
        Args:
            ttl_hours: How long to keep idempotency keys (default 24h)
        """
        self.ttl_hours = ttl_hours
        
        # Track submitted orders by idempotency key
        self.submitted_keys: Dict[str, OrderRequest] = {}
        
        # Track filled orders (deal_id -> idempotency_key)
        self.filled_orders: Dict[str, str] = {}
        
        # Cleanup timestamp
        self.last_cleanup: datetime = datetime.now()
        self.cleanup_interval_minutes = 60
    
    def is_duplicate(self, idempotency_key: str) -> bool:
        """
        Check if order with this key was already submitted.
        
        Args:
            idempotency_key: Unique order identifier
        
        Returns:
            True if duplicate, False if new
        """
        return idempotency_key in self.submitted_keys
    
    def get_cached_result(self, idempotency_key: str) -> Optional[OrderRequest]:
        """
        Get cached result for duplicate request.
        
        If the exact same order was already submitted, return the previous result.
        This allows safe retries - same request returns same result.
        
        Args:
            idempotency_key: Unique order identifier
        
        Returns:
            Cached OrderRequest if found, None otherwise
        """
        return self.submitted_keys.get(idempotency_key)
    
    def register_submission(self, order: OrderRequest) -> None:
        """
        Register order submission to prevent duplicates.
        
        Args:
            order: OrderRequest that was submitted
        """
        order.submitted_at = datetime.now()
        order.status = 'submitted'
        self.submitted_keys[order.idempotency_key] = order
        
        print(f"✅ Registered order submission: {order.idempotency_key}")
    
    def register_fill(self, idempotency_key: str, deal_id: str) -> None:
        """
        Register order fill/acknowledgment.
        
        Args:
            idempotency_key: Order identifier
            deal_id: Broker-assigned deal ID
        """
        if idempotency_key in self.submitted_keys:
            self.submitted_keys[idempotency_key].deal_id = deal_id
            self.submitted_keys[idempotency_key].status = 'filled'
            self.filled_orders[deal_id] = idempotency_key
            
            print(f"✅ Registered order fill: {idempotency_key} -> {deal_id}")
    
    def register_rejection(self, idempotency_key: str, reason: str) -> None:
        """
        Register order rejection.
        
        Args:
            idempotency_key: Order identifier
            reason: Rejection reason
        """
        if idempotency_key in self.submitted_keys:
            self.submitted_keys[idempotency_key].status = 'rejected'
            self.submitted_keys[idempotency_key].reason = reason
            print(f"⚠️ Registered order rejection: {idempotency_key} - {reason}")
    
    def was_order_filled(self, signal_timestamp_or_key, instrument: str = None, direction: str = None) -> Optional[str]:
        """
        Check if order from this signal was already filled.

        Can be called as:
          - was_order_filled(idempotency_key)  -- single string key
          - was_order_filled(signal_timestamp, instrument, direction)

        Returns:
            deal_id if order was filled, None otherwise
        """
        if instrument is None and direction is None:
            # Called with a single idempotency key string
            idempotency_key = signal_timestamp_or_key
        else:
            signal_timestamp = signal_timestamp_or_key
            timestamp_ms = int(signal_timestamp.timestamp() * 1000)
            idempotency_key = f"{instrument}_{direction}_{timestamp_ms}"

        order = self.submitted_keys.get(idempotency_key)
        if order and order.status == 'filled':
            return True

        return False
    
    async def cleanup_expired(self) -> int:
        """
        Remove expired idempotency keys (older than TTL).

        Returns:
            Number of keys removed
        """
        now = datetime.now()
        cutoff = now - timedelta(hours=self.ttl_hours)

        # Find expired keys — check signal_timestamp first (it reflects when the signal occurred)
        # and fall back to submitted_at for backward compatibility
        expired_keys = [
            key for key, order in self.submitted_keys.items()
            if (order.signal_timestamp and order.signal_timestamp < cutoff) or
               (not order.signal_timestamp and order.submitted_at and order.submitted_at < cutoff)
        ]
        
        # Remove expired
        for key in expired_keys:
            order = self.submitted_keys.pop(key)
            if order.deal_id and order.deal_id in self.filled_orders:
                del self.filled_orders[order.deal_id]
        
        self.last_cleanup = now
        
        if expired_keys:
            print(f"🧹 Cleaned up {len(expired_keys)} expired idempotency keys")
        
        return len(expired_keys)
    
    def get_stats(self) -> Dict:
        """Get idempotency manager statistics"""
        return {
            'total_submissions': len(self.submitted_keys),
            'filled_orders': len(self.filled_orders),
            'pending_orders': len([o for o in self.submitted_keys.values() if o.status == 'pending']),
            'rejected_orders': len([o for o in self.submitted_keys.values() if o.status == 'rejected']),
            'last_cleanup': self.last_cleanup.isoformat(),
            'ttl_hours': self.ttl_hours
        }


class RetryPolicy:
    """
    Configurable retry policy for order execution.
    
    Handles:
    - Exponential backoff
    - Maximum retry attempts
    - Timeout handling
    - Transient vs permanent failures
    """
    
    def __init__(self, max_attempts: int = 3, base_delay_seconds: float = 1.0, 
                 max_delay_seconds: float = 10.0, timeout_seconds: float = 30.0):
        """
        Initialize retry policy.
        
        Args:
            max_attempts: Maximum number of retry attempts
            base_delay_seconds: Initial delay between retries
            max_delay_seconds: Maximum delay between retries (exponential backoff cap)
            timeout_seconds: Total timeout for operation
        """
        self.max_attempts = max_attempts
        self.base_delay = base_delay_seconds
        self.max_delay = max_delay_seconds
        self.timeout = timeout_seconds
    
    def calculate_delay(self, attempt: int) -> float:
        """Calculate delay for given attempt using exponential backoff."""
        delay = self.base_delay * (2 ** attempt)
        return min(delay, self.max_delay)

    def calculate_backoff_delay(self, attempt: int) -> float:
        """Alias for calculate_delay (1-indexed attempt)."""
        return self.calculate_delay(max(0, attempt - 1))

    def is_transient_error(self, exception: Exception) -> bool:
        """Determine if error is transient (retryable) or permanent."""
        error_str = str(exception).lower()
        transient_keywords = ('timeout', 'connection', 'network',
                              'temporarily unavailable', 'rate limit',
                              'too many requests', 'unavailable')
        return any(kw in error_str for kw in transient_keywords)
    
    async def execute_with_retry(self, operation, *args, **kwargs):
        """
        Execute operation with retry logic.
        
        Args:
            operation: Async function to execute
            *args, **kwargs: Arguments for operation
        
        Returns:
            Operation result
        
        Raises:
            Last exception if all retries fail
        """
        last_exception = None
        
        for attempt in range(self.max_attempts):
            try:
                # Execute operation with timeout
                result = await asyncio.wait_for(
                    operation(*args, **kwargs),
                    timeout=self.timeout
                )
                
                # Success
                if attempt > 0:
                    print(f"✅ Operation succeeded on attempt {attempt + 1}")
                return result
            
            except asyncio.TimeoutError:
                last_exception = Exception(f"Operation timed out after {self.timeout}s")
                print(f"⚠️ Attempt {attempt + 1}/{self.max_attempts} timed out")

            except Exception as e:
                last_exception = e
                if not self.is_transient_error(e):
                    # Non-transient errors (logic errors, validation, etc.) should not be retried
                    raise
                print(f"⚠️ Attempt {attempt + 1}/{self.max_attempts} failed: {e}")
            
            # Wait before retry (except on last attempt)
            if attempt < self.max_attempts - 1:
                delay = self.calculate_delay(attempt)
                print(f"⏳ Retrying in {delay:.1f}s...")
                await asyncio.sleep(delay)
        
        # All retries failed
        print(f"❌ Operation failed after {self.max_attempts} attempts")
        raise last_exception


# Transient error detection
TRANSIENT_ERRORS = {
    'timeout',
    'connection',
    'network',
    'temporarily unavailable',
    'rate limit',
    'too many requests'
}


def is_transient_error(error: Exception) -> bool:
    """
    Determine if error is transient (retryable) or permanent.
    
    Args:
        error: Exception to check
    
    Returns:
        True if error is likely transient and can be retried
    """
    error_str = str(error).lower()
    return any(keyword in error_str for keyword in TRANSIENT_ERRORS)

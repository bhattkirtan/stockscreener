"""
Unit tests for Idempotency Manager
Tests duplicate detection, retry logic, and TTL cleanup
"""
import pytest
import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock

from core.idempotency import (
    OrderRequest, IdempotencyManager, RetryPolicy
)


# ========== OrderRequest Tests ==========

def test_order_request_creation():
    """Test creating an order request with idempotency key"""
    order = OrderRequest.create(
        instrument='GOLD',
        direction='BUY',
        size=0.1,
        stop_loss=1940.00,
        take_profit=1980.00,
        signal_timestamp=datetime(2024, 1, 15, 10, 30, 45, 123456)
    )
    
    assert order.instrument == 'GOLD'
    assert order.direction == 'BUY'
    assert order.size == 0.1
    
    # Idempotency key format: {instrument}_{direction}_{timestamp_ms}
    expected_key_prefix = 'GOLD_BUY_'
    assert order.idempotency_key.startswith(expected_key_prefix)


def test_order_request_idempotency_key_uniqueness():
    """Test that same signal parameters generate same idempotency key"""
    timestamp = datetime(2024, 1, 15, 10, 30, 45, 123456)
    
    order1 = OrderRequest.create(
        instrument='GOLD',
        direction='BUY',
        size=0.1,
        stop_loss=1940.00,
        take_profit=1980.00,
        signal_timestamp=timestamp
    )
    
    order2 = OrderRequest.create(
        instrument='GOLD',
        direction='BUY',
        size=0.1,
        stop_loss=1940.00,
        take_profit=1980.00,
        signal_timestamp=timestamp
    )
    
    # Same timestamp = same idempotency key
    assert order1.idempotency_key == order2.idempotency_key


def test_order_request_different_keys_for_different_signals():
    """Test that different signals generate different idempotency keys"""
    timestamp1 = datetime(2024, 1, 15, 10, 30, 45, 123456)
    timestamp2 = datetime(2024, 1, 15, 10, 30, 45, 654321)
    
    order1 = OrderRequest.create(
        instrument='GOLD',
        direction='BUY',
        size=0.1,
        stop_loss=1940.00,
        take_profit=1980.00,
        signal_timestamp=timestamp1
    )
    
    order2 = OrderRequest.create(
        instrument='GOLD',
        direction='BUY',
        size=0.1,
        stop_loss=1940.00,
        take_profit=1980.00,
        signal_timestamp=timestamp2
    )
    
    # Different timestamps = different keys
    assert order1.idempotency_key != order2.idempotency_key


# ========== IdempotencyManager Tests ==========

@pytest.fixture
def idempotency_manager():
    """Create idempotency manager"""
    return IdempotencyManager(ttl_hours=24)


def test_first_submission_not_duplicate(idempotency_manager):
    """Test first submission is not marked as duplicate"""
    order = OrderRequest.create(
        instrument='GOLD',
        direction='BUY',
        size=0.1,
        stop_loss=1940.00,
        take_profit=1980.00,
        signal_timestamp=datetime.now()
    )
    
    is_dup = idempotency_manager.is_duplicate(order.idempotency_key)
    
    assert is_dup is False


def test_second_submission_is_duplicate(idempotency_manager):
    """Test second submission with same key is marked as duplicate"""
    order = OrderRequest.create(
        instrument='GOLD',
        direction='BUY',
        size=0.1,
        stop_loss=1940.00,
        take_profit=1980.00,
        signal_timestamp=datetime.now()
    )
    
    # First submission
    idempotency_manager.register_submission(order)
    
    # Second submission (duplicate)
    is_dup = idempotency_manager.is_duplicate(order.idempotency_key)
    
    assert is_dup is True


def test_register_submission(idempotency_manager):
    """Test registering order submission"""
    order = OrderRequest.create(
        instrument='GOLD',
        direction='BUY',
        size=0.1,
        stop_loss=1940.00,
        take_profit=1980.00,
        signal_timestamp=datetime.now()
    )
    
    idempotency_manager.register_submission(order)
    
    # Should now be tracked
    assert order.idempotency_key in idempotency_manager.submitted_keys


def test_register_fill(idempotency_manager):
    """Test registering order fill"""
    order = OrderRequest.create(
        instrument='GOLD',
        direction='BUY',
        size=0.1,
        stop_loss=1940.00,
        take_profit=1980.00,
        signal_timestamp=datetime.now()
    )
    
    idempotency_manager.register_submission(order)
    idempotency_manager.register_fill(order.idempotency_key, deal_id='DEAL123')
    
    # Should have cached result
    cached = idempotency_manager.get_cached_result(order.idempotency_key)
    
    assert cached is not None
    assert cached.deal_id == 'DEAL123'
    assert cached.status == 'filled'


def test_register_rejection(idempotency_manager):
    """Test registering order rejection"""
    order = OrderRequest.create(
        instrument='GOLD',
        direction='BUY',
        size=0.1,
        stop_loss=1940.00,
        take_profit=1980.00,
        signal_timestamp=datetime.now()
    )
    
    idempotency_manager.register_submission(order)
    idempotency_manager.register_rejection(order.idempotency_key, reason='Insufficient margin')
    
    # Should have cached result
    cached = idempotency_manager.get_cached_result(order.idempotency_key)
    
    assert cached is not None
    assert cached.status == 'rejected'
    assert cached.reason == 'Insufficient margin'


def test_get_cached_result_for_duplicate(idempotency_manager):
    """Test retrieving cached result for duplicate request"""
    order = OrderRequest.create(
        instrument='GOLD',
        direction='BUY',
        size=0.1,
        stop_loss=1940.00,
        take_profit=1980.00,
        signal_timestamp=datetime.now()
    )
    
    # Submit and fill
    idempotency_manager.register_submission(order)
    idempotency_manager.register_fill(order.idempotency_key, deal_id='DEAL123')
    
    # Duplicate request should get cached result
    cached = idempotency_manager.get_cached_result(order.idempotency_key)
    
    assert cached.deal_id == 'DEAL123'
    assert cached.status == 'filled'


def test_was_order_filled(idempotency_manager):
    """Test checking if order was filled"""
    order = OrderRequest.create(
        instrument='GOLD',
        direction='BUY',
        size=0.1,
        stop_loss=1940.00,
        take_profit=1980.00,
        signal_timestamp=datetime.now()
    )
    
    # Before fill
    was_filled = idempotency_manager.was_order_filled(order.idempotency_key)
    assert was_filled is False
    
    # After fill
    idempotency_manager.register_submission(order)
    idempotency_manager.register_fill(order.idempotency_key, deal_id='DEAL123')
    
    was_filled = idempotency_manager.was_order_filled(order.idempotency_key)
    assert was_filled is True


@pytest.mark.asyncio
async def test_cleanup_expired_keys(idempotency_manager):
    """Test cleanup removes expired keys"""
    # Create old order (25 hours ago, TTL is 24 hours)
    old_timestamp = datetime.now() - timedelta(hours=25)
    old_order = OrderRequest.create(
        instrument='GOLD',
        direction='BUY',
        size=0.1,
        stop_loss=1940.00,
        take_profit=1980.00,
        signal_timestamp=old_timestamp
    )
    
    # Create recent order (1 hour ago)
    recent_order = OrderRequest.create(
        instrument='EURUSD',
        direction='SELL',
        size=0.2,
        stop_loss=1.1050,
        take_profit=1.0950,
        signal_timestamp=datetime.now() - timedelta(hours=1)
    )
    
    # Register both
    idempotency_manager.register_submission(old_order)
    idempotency_manager.register_submission(recent_order)
    
    # Cleanup
    await idempotency_manager.cleanup_expired()
    
    # Old should be removed, recent should remain
    assert idempotency_manager.is_duplicate(old_order.idempotency_key) is False
    assert idempotency_manager.is_duplicate(recent_order.idempotency_key) is True


# ========== RetryPolicy Tests ==========

@pytest.fixture
def retry_policy():
    """Create retry policy"""
    return RetryPolicy(
        max_attempts=3,
        base_delay_seconds=1.0,
        timeout_seconds=30.0
    )


def test_is_transient_error(retry_policy):
    """Test transient error detection"""
    # Transient errors
    assert retry_policy.is_transient_error(Exception('Connection timeout')) is True
    assert retry_policy.is_transient_error(Exception('Rate limit exceeded')) is True
    assert retry_policy.is_transient_error(Exception('Temporary unavailable')) is True
    assert retry_policy.is_transient_error(Exception('Network error')) is True
    
    # Non-transient errors
    assert retry_policy.is_transient_error(Exception('Invalid credentials')) is False
    assert retry_policy.is_transient_error(Exception('Insufficient funds')) is False


def test_calculate_backoff_delay(retry_policy):
    """Test exponential backoff calculation"""
    # Attempt 1: 1.0 seconds
    delay1 = retry_policy.calculate_backoff_delay(attempt=1)
    assert delay1 == 1.0
    
    # Attempt 2: 2.0 seconds (2^1 * base)
    delay2 = retry_policy.calculate_backoff_delay(attempt=2)
    assert delay2 == 2.0
    
    # Attempt 3: 4.0 seconds (2^2 * base)
    delay3 = retry_policy.calculate_backoff_delay(attempt=3)
    assert delay3 == 4.0
    
    # Should not exceed max_delay (10 seconds default)
    delay_large = retry_policy.calculate_backoff_delay(attempt=10)
    assert delay_large <= 10.0


@pytest.mark.asyncio
async def test_execute_with_retry_success_first_attempt(retry_policy):
    """Test retry succeeds on first attempt"""
    # Mock function that succeeds
    mock_func = AsyncMock(return_value={'deal_id': 'DEAL123', 'status': 'FILLED'})
    
    result = await retry_policy.execute_with_retry(mock_func)
    
    assert result['deal_id'] == 'DEAL123'
    assert mock_func.call_count == 1


@pytest.mark.asyncio
async def test_execute_with_retry_success_after_transient_failures(retry_policy):
    """Test retry succeeds after transient failures"""
    # Mock function that fails twice then succeeds
    call_count = 0
    
    async def mock_func():
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise Exception('Connection timeout')
        return {'deal_id': 'DEAL123', 'status': 'FILLED'}
    
    result = await retry_policy.execute_with_retry(mock_func)
    
    assert result['deal_id'] == 'DEAL123'
    assert call_count == 3  # Failed 2 times, succeeded on 3rd


@pytest.mark.asyncio
async def test_execute_with_retry_fails_after_max_attempts(retry_policy):
    """Test retry gives up after max attempts"""
    # Mock function that always fails with transient error
    mock_func = AsyncMock(side_effect=Exception('Connection timeout'))
    
    with pytest.raises(Exception) as exc_info:
        await retry_policy.execute_with_retry(mock_func)
    
    assert 'Connection timeout' in str(exc_info.value)
    assert mock_func.call_count == 3  # max_attempts


@pytest.mark.asyncio
async def test_execute_with_retry_fails_immediately_on_non_transient_error(retry_policy):
    """Test retry fails immediately on non-transient error"""
    # Mock function that fails with non-transient error
    mock_func = AsyncMock(side_effect=Exception('Invalid credentials'))
    
    with pytest.raises(Exception) as exc_info:
        await retry_policy.execute_with_retry(mock_func)
    
    assert 'Invalid credentials' in str(exc_info.value)
    assert mock_func.call_count == 1  # No retries for non-transient


if __name__ == '__main__':
    pytest.main([__file__, '-v'])

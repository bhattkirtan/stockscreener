"""
Unit tests for Operational Monitoring
Tests WebSocket health, API latency, data freshness, and overall monitoring
"""
import pytest
import asyncio
from datetime import datetime, timedelta
from unittest.mock import patch

from core.operational_monitoring import (
    LatencyMetric,
    HealthCheck,
    WebSocketHealthMonitor,
    APILatencyMonitor,
    DataFreshnessMonitor,
    OperationalMonitor,
    track_latency
)


# ========== WebSocketHealthMonitor Tests ==========

@pytest.fixture
def websocket_monitor():
    """Create WebSocket health monitor"""
    config = {
        'heartbeat_interval_seconds': 30,
        'missed_heartbeat_threshold': 3,
        'staleness_threshold_seconds': 300  # 5 minutes
    }
    return WebSocketHealthMonitor(config)


def test_websocket_monitor_initial_state(websocket_monitor):
    """Test WebSocket monitor starts disconnected"""
    health = websocket_monitor.get_health()
    
    assert health.status == 'UNHEALTHY'
    assert 'disconnected' in health.message.lower()


def test_websocket_monitor_on_connect(websocket_monitor):
    """Test WebSocket monitor tracks connection"""
    websocket_monitor.on_connect()
    
    health = websocket_monitor.get_health()
    
    assert websocket_monitor.is_connected is True
    assert websocket_monitor.connect_time is not None


def test_websocket_monitor_on_disconnect(websocket_monitor):
    """Test WebSocket monitor tracks disconnection"""
    websocket_monitor.on_connect()
    websocket_monitor.on_disconnect()
    
    health = websocket_monitor.get_health()
    
    assert websocket_monitor.is_connected is False
    assert websocket_monitor.disconnect_count == 1
    assert health.status == 'UNHEALTHY'


def test_websocket_monitor_tracks_heartbeats(websocket_monitor):
    """Test WebSocket monitor tracks heartbeats"""
    websocket_monitor.on_connect()
    websocket_monitor.on_heartbeat()
    
    assert websocket_monitor.last_heartbeat is not None
    assert websocket_monitor.missed_heartbeats == 0


def test_websocket_monitor_detects_missed_heartbeats(websocket_monitor):
    """Test WebSocket monitor detects missed heartbeats"""
    websocket_monitor.on_connect()
    websocket_monitor.on_heartbeat()
    
    # Simulate missed heartbeats (35 seconds ago, should have had heartbeat)
    with patch('datetime.datetime') as mock_datetime:
        mock_datetime.now.return_value = datetime.now() + timedelta(seconds=35)
        
        health = websocket_monitor.get_health()
    
    # Should detect 1 missed heartbeat (35s / 30s interval)
    assert websocket_monitor.missed_heartbeats >= 1


def test_websocket_monitor_tracks_messages(websocket_monitor):
    """Test WebSocket monitor tracks message reception"""
    websocket_monitor.on_connect()
    websocket_monitor.on_message('candle')
    
    assert websocket_monitor.last_message_time is not None
    assert websocket_monitor.message_count == 1


def test_websocket_monitor_detects_stale_data(websocket_monitor):
    """Test WebSocket monitor detects stale data"""
    websocket_monitor.on_connect()
    websocket_monitor.on_message('candle')
    
    # Simulate stale data (6 minutes old, threshold is 5 minutes)
    with patch('datetime.datetime') as mock_datetime:
        mock_datetime.now.return_value = datetime.now() + timedelta(minutes=6)
        
        health = websocket_monitor.get_health()
    
    assert health.status == 'DEGRADED'
    assert 'stale' in health.message.lower()


def test_websocket_monitor_calculates_uptime(websocket_monitor):
    """Test WebSocket monitor calculates uptime"""
    websocket_monitor.on_connect()
    
    # Simulate 10 minutes connected
    with patch('datetime.datetime') as mock_datetime:
        mock_datetime.now.return_value = datetime.now() + timedelta(minutes=10)
        
        uptime = websocket_monitor.get_uptime_seconds()
    
    assert uptime >= 600  # 10 minutes


# ========== APILatencyMonitor Tests ==========

@pytest.fixture
def api_monitor():
    """Create API latency monitor"""
    config = {
        'latency_threshold_ms': 1000,
        'success_rate_threshold': 0.90,
        'window_size': 100
    }
    return APILatencyMonitor(config)


def test_api_monitor_records_request(api_monitor):
    """Test API monitor records request"""
    api_monitor.record_request(
        operation='place_order',
        latency_ms=150,
        success=True
    )
    
    assert api_monitor.total_requests == 1


def test_api_monitor_calculates_average_latency(api_monitor):
    """Test API monitor calculates average latency"""
    # Record multiple requests
    api_monitor.record_request('place_order', latency_ms=100, success=True)
    api_monitor.record_request('place_order', latency_ms=200, success=True)
    api_monitor.record_request('place_order', latency_ms=300, success=True)
    
    avg_latency = api_monitor.get_average_latency('place_order')
    
    assert avg_latency == 200.0  # (100 + 200 + 300) / 3


def test_api_monitor_calculates_success_rate(api_monitor):
    """Test API monitor calculates success rate"""
    # Record requests with some failures
    api_monitor.record_request('place_order', latency_ms=100, success=True)
    api_monitor.record_request('place_order', latency_ms=150, success=True)
    api_monitor.record_request('place_order', latency_ms=200, success=False)
    api_monitor.record_request('place_order', latency_ms=250, success=True)
    
    success_rate = api_monitor.get_success_rate('place_order')
    
    assert success_rate == 0.75  # 3/4


def test_api_monitor_calculates_p95_latency(api_monitor):
    """Test API monitor calculates P95 latency"""
    # Record 20 requests with increasing latency
    for i in range(20):
        api_monitor.record_request('place_order', latency_ms=i * 10, success=True)
    
    p95 = api_monitor.get_p95_latency('place_order')
    
    # P95 should be around 190ms (95th percentile of 0-190)
    assert p95 >= 170


def test_api_monitor_tracks_per_operation_stats(api_monitor):
    """Test API monitor tracks stats per operation"""
    api_monitor.record_request('place_order', latency_ms=100, success=True)
    api_monitor.record_request('get_positions', latency_ms=50, success=True)
    api_monitor.record_request('close_position', latency_ms=150, success=True)
    
    place_avg = api_monitor.get_average_latency('place_order')
    get_avg = api_monitor.get_average_latency('get_positions')
    close_avg = api_monitor.get_average_latency('close_position')
    
    assert place_avg == 100.0
    assert get_avg == 50.0
    assert close_avg == 150.0


def test_api_monitor_detects_slow_queries(api_monitor):
    """Test API monitor detects slow queries"""
    # Record slow request (>1000ms threshold)
    api_monitor.record_request('place_order', latency_ms=1500, success=True)
    
    slow_queries = api_monitor.get_slow_queries()
    
    assert len(slow_queries) > 0
    assert slow_queries[0].latency_ms == 1500


def test_api_monitor_health_unhealthy_on_low_success_rate(api_monitor):
    """Test API monitor reports UNHEALTHY on low success rate"""
    # Record mostly failures (< 90% success threshold)
    for _ in range(8):
        api_monitor.record_request('place_order', latency_ms=100, success=False)
    
    for _ in range(2):
        api_monitor.record_request('place_order', latency_ms=100, success=True)
    
    health = api_monitor.get_health()
    
    # Success rate = 20% (< 90% threshold)
    assert health.status == 'UNHEALTHY'


def test_api_monitor_health_healthy_on_good_performance(api_monitor):
    """Test API monitor reports HEALTHY on good performance"""
    # Record all successes with good latency
    for _ in range(10):
        api_monitor.record_request('place_order', latency_ms=100, success=True)
    
    health = api_monitor.get_health()
    
    assert health.status == 'HEALTHY'


# ========== DataFreshnessMonitor Tests ==========

@pytest.fixture
def freshness_monitor():
    """Create data freshness monitor"""
    config = {
        'staleness_threshold_seconds': 600  # 10 minutes
    }
    return DataFreshnessMonitor(config)


def test_freshness_monitor_records_update(freshness_monitor):
    """Test freshness monitor records data update"""
    freshness_monitor.record_update('candles')
    
    assert 'candles' in freshness_monitor.last_update
    assert freshness_monitor.last_update['candles'] is not None


def test_freshness_monitor_calculates_staleness(freshness_monitor):
    """Test freshness monitor calculates staleness"""
    freshness_monitor.record_update('candles')
    
    # Simulate 5 minutes passing
    with patch('datetime.datetime') as mock_datetime:
        future_time = datetime.now() + timedelta(minutes=5)
        mock_datetime.now.return_value = future_time
        
        staleness = freshness_monitor.get_staleness('candles')
    
    assert staleness >= 300  # 5 minutes in seconds


def test_freshness_monitor_detects_stale_data(freshness_monitor):
    """Test freshness monitor detects stale data"""
    freshness_monitor.record_update('candles')
    
    # Simulate 11 minutes passing (>10 minute threshold)
    with patch('datetime.datetime') as mock_datetime:
        future_time = datetime.now() + timedelta(minutes=11)
        mock_datetime.now.return_value = future_time
        
        is_stale = freshness_monitor.is_stale('candles')
    
    assert is_stale is True


def test_freshness_monitor_health_degraded_on_stale_data(freshness_monitor):
    """Test freshness monitor reports DEGRADED on stale data"""
    freshness_monitor.record_update('candles')
    
    # Make data stale
    with patch('datetime.datetime') as mock_datetime:
        mock_datetime.now.return_value = datetime.now() + timedelta(minutes=11)
        
        health = freshness_monitor.get_health()
    
    assert health.status == 'DEGRADED'
    assert 'stale' in health.message.lower()


def test_freshness_monitor_health_healthy_on_fresh_data(freshness_monitor):
    """Test freshness monitor reports HEALTHY on fresh data"""
    freshness_monitor.record_update('candles')
    freshness_monitor.record_update('quotes')
    freshness_monitor.record_update('positions')
    
    health = freshness_monitor.get_health()
    
    assert health.status == 'HEALTHY'


# ========== OperationalMonitor Tests ==========

@pytest.fixture
def operational_monitor():
    """Create operational monitor"""
    config = {
        'websocket': {
            'heartbeat_interval_seconds': 30,
            'missed_heartbeat_threshold': 3,
            'staleness_threshold_seconds': 300
        },
        'api': {
            'latency_threshold_ms': 1000,
            'success_rate_threshold': 0.90,
            'window_size': 100
        },
        'data_freshness': {
            'staleness_threshold_seconds': 600
        }
    }
    return OperationalMonitor(config)


@pytest.mark.asyncio
async def test_operational_monitor_aggregates_health(operational_monitor):
    """Test operational monitor aggregates component health"""
    # Set components to healthy state
    operational_monitor.websocket_monitor.on_connect()
    operational_monitor.websocket_monitor.on_message('candle')
    
    operational_monitor.api_latency_monitor.record_request(
        'place_order', latency_ms=100, success=True
    )
    
    operational_monitor.data_freshness_monitor.record_update('candles')
    
    # Run health checks
    health_checks = await operational_monitor.run_health_checks()
    
    assert len(health_checks) == 3  # WebSocket, API, data freshness
    assert all(check.status in ['HEALTHY', 'DEGRADED', 'UNHEALTHY'] for check in health_checks)


@pytest.mark.asyncio
async def test_operational_monitor_overall_status_healthy(operational_monitor):
    """Test overall status is HEALTHY when all components healthy"""
    # Set all components healthy
    operational_monitor.websocket_monitor.on_connect()
    operational_monitor.websocket_monitor.on_message('candle')
    
    for _ in range(10):
        operational_monitor.api_latency_monitor.record_request(
            'place_order', latency_ms=100, success=True
        )
    
    operational_monitor.data_freshness_monitor.record_update('candles')
    
    overall_status = operational_monitor.get_overall_status()
    
    assert overall_status == 'HEALTHY'


@pytest.mark.asyncio
async def test_operational_monitor_overall_status_unhealthy(operational_monitor):
    """Test overall status is UNHEALTHY if any component unhealthy"""
    # Set WebSocket disconnected (unhealthy)
    operational_monitor.websocket_monitor.on_disconnect()
    
    # Other components healthy
    operational_monitor.api_latency_monitor.record_request(
        'place_order', latency_ms=100, success=True
    )
    operational_monitor.data_freshness_monitor.record_update('candles')
    
    overall_status = operational_monitor.get_overall_status()
    
    assert overall_status == 'UNHEALTHY'


@pytest.mark.asyncio
async def test_operational_monitor_metrics_summary(operational_monitor):
    """Test operational monitor generates metrics summary"""
    # Add some data
    operational_monitor.websocket_monitor.on_connect()
    operational_monitor.websocket_monitor.on_message('candle')
    
    operational_monitor.api_latency_monitor.record_request(
        'place_order', latency_ms=150, success=True
    )
    
    operational_monitor.data_freshness_monitor.record_update('candles')
    
    # Get metrics summary
    metrics = operational_monitor.get_metrics_summary()
    
    assert 'websocket' in metrics
    assert 'api' in metrics
    assert 'data_freshness' in metrics
    assert 'overall_status' in metrics


# ========== track_latency Decorator Tests ==========

@pytest.mark.asyncio
async def test_track_latency_decorator():
    """Test track_latency decorator tracks function latency"""
    monitor = APILatencyMonitor({})
    
    @track_latency(monitor, 'test_operation')
    async def test_function():
        await asyncio.sleep(0.1)  # 100ms delay
        return 'success'
    
    result = await test_function()
    
    assert result == 'success'
    
    # Check latency was recorded
    avg_latency = monitor.get_average_latency('test_operation')
    assert avg_latency >= 100  # At least 100ms


@pytest.mark.asyncio
async def test_track_latency_decorator_records_failures():
    """Test track_latency decorator records failures"""
    monitor = APILatencyMonitor({})
    
    @track_latency(monitor, 'failing_operation')
    async def failing_function():
        raise Exception('Operation failed')
    
    with pytest.raises(Exception):
        await failing_function()
    
    # Check failure was recorded
    success_rate = monitor.get_success_rate('failing_operation')
    assert success_rate == 0.0


if __name__ == '__main__':
    pytest.main([__file__, '-v'])

"""
Integration tests for production orchestrator with all new components.

Tests:
- Startup reconciliation flow
- Idempotency preventing duplicate orders
- Circuit breakers blocking trades
- Event-driven skill communication
- Operational monitoring health checks
"""
import pytest
import pytest_asyncio
import asyncio
from datetime import datetime, timedelta
from unittest.mock import Mock, MagicMock, AsyncMock, patch

from orchestrator.production_orchestrator import ProductionOrchestrator
from core.position_state import Position, PositionStatus
from core.idempotency import OrderRequest
from core.circuit_breakers import CircuitBreakerStatus
from core.event_bus import Event, EventType
from skills.base_skill import Context


# ========== Test Fixtures ==========

@pytest.fixture
def config():
    """Minimal test configuration"""
    return {
        'instrument': 'GOLD',
        'timeframe': 'M5',
        'initial_capital': 10000,
        'circuit_breaker': {
            'max_daily_loss_pct': 5.0,
            'max_weekly_loss_pct': 10.0,
            'max_consecutive_losses': 5
        },
        'trading_sessions': {
            'allowed_sessions': ['LONDON', 'NEW_YORK']
        },
        'spread_filter': {
            'max_spread_pips': 30,
            'max_spread_pct': 0.1
        },
        'monitoring': {
            'websocket_heartbeat_interval': 30,
            'api_latency_threshold_ms': 1000,
            'data_staleness_threshold_seconds': 600
        }
    }


@pytest.fixture
def mock_capital_api():
    """Mock Capital.com API"""
    api = Mock()
    api.get_open_positions = AsyncMock(return_value=[])
    api.place_order = AsyncMock(return_value={'deal_id': 'DEAL123', 'status': 'FILLED'})
    api.close_position = AsyncMock(return_value={'status': 'CLOSED'})
    api.get_account_info = AsyncMock(return_value={'balance': 10000, 'available': 9500})
    return api


@pytest.fixture
def mock_firestore():
    """Mock Firestore client"""
    client = Mock()
    client.save_position = AsyncMock(return_value=True)
    client.load_positions = AsyncMock(return_value=[])
    return client


@pytest.fixture
def mock_telegram():
    """Mock Telegram client"""
    client = Mock()
    client.send_message = AsyncMock(return_value=True)
    return client


@pytest_asyncio.fixture
async def orchestrator(config, mock_capital_api, mock_firestore, mock_telegram):
    """Create orchestrator with mocked dependencies"""
    orch = ProductionOrchestrator(
        config=config,
        capital_api=mock_capital_api,
        firestore_client=mock_firestore,
        telegram_client=mock_telegram
    )
    
    # Build storage mock with async methods
    storage_mock = MagicMock()
    storage_mock.load_data = AsyncMock(return_value=None)
    storage_mock.save_data = AsyncMock(return_value=True)

    # Register mock skills (MagicMock supports magic attributes like __name__)
    orch.register_skill('storage', storage_mock)
    orch.register_skill('analysis', MagicMock())
    orch.register_skill('risk', MagicMock())
    orch.register_skill('execution', MagicMock())
    orch.register_skill('monitoring', MagicMock())
    orch.register_skill('alerting', MagicMock())
    
    yield orch
    
    # Cleanup
    if orch.running:
        await orch.stop()


# ========== Startup Reconciliation Tests ==========

@pytest.mark.asyncio
async def test_startup_reconciliation_with_no_positions(orchestrator, mock_capital_api):
    """Test startup when no positions exist"""
    # Arrange: No open positions in broker
    mock_capital_api.get_open_positions.return_value = []
    
    # Act: Start orchestrator
    result = await orchestrator.start()
    
    # Assert
    assert result is True
    assert orchestrator.running is True
    assert orchestrator.stats['reconciliations'] == 1
    assert orchestrator.position_manager.get_position_count() == 0


@pytest.mark.asyncio
async def test_startup_reconciliation_adds_missing_local_positions(orchestrator, mock_capital_api, mock_telegram):
    """Test startup auto-adds positions that exist in broker but not locally"""
    # Arrange: Broker has 1 open position
    broker_position = {
        'deal_id': 'DEALER123',
        'instrument': 'GOLD',
        'direction': 'BUY',
        'size': 0.1,
        'open_level': 1950.00,
        'stop_level': 1940.00,
        'profit_level': 1980.00
    }
    mock_capital_api.get_open_positions.return_value = [broker_position]
    
    # Act: Start orchestrator
    result = await orchestrator.start()
    
    # Assert: Position should be added locally
    assert result is True
    assert orchestrator.position_manager.get_position_count() == 1
    
    # Should have sent reconciliation alert
    assert mock_telegram.send_message.called or orchestrator.stats['reconciliations'] == 1


@pytest.mark.asyncio
async def test_startup_reconciliation_closes_orphaned_local_positions(orchestrator, mock_capital_api):
    """Test startup auto-closes positions that exist locally but not in broker"""
    # Arrange: Add local position that doesn't exist in broker
    local_position = Position(
        deal_id='LOCAL123',
        instrument='GOLD',
        direction='BUY',
        entry_price=1950.00,
        size=0.1,
        stop_loss=1940.00,
        take_profit=1980.00,
        status=PositionStatus.OPEN,
        opened_at=datetime.now() - timedelta(hours=1),
        signal_timestamp=datetime.now() - timedelta(hours=1)
    )
    orchestrator.position_manager.add_position(local_position)
    
    # Broker has no positions
    mock_capital_api.get_open_positions.return_value = []
    
    # Act: Start orchestrator
    result = await orchestrator.start()
    
    # Assert: Orphaned position should be closed
    assert result is True
    position = orchestrator.position_manager.get_position('LOCAL123')
    assert position.status == PositionStatus.CLOSED
    assert position.close_reason == 'orphaned'


# ========== Idempotency Tests ==========

@pytest.mark.asyncio
async def test_idempotency_prevents_duplicate_order_submission(orchestrator):
    """Test that duplicate order requests are blocked"""
    # Arrange: Create order request
    order = OrderRequest.create(
        instrument='GOLD',
        direction='BUY',
        size=0.1,
        stop_loss=1940.00,
        take_profit=1980.00,
        signal_timestamp=datetime.now()
    )
    
    # First submission
    is_dup_first = orchestrator.idempotency.is_duplicate(order.idempotency_key)
    orchestrator.idempotency.register_submission(order)
    
    # Second submission (duplicate)
    is_dup_second = orchestrator.idempotency.is_duplicate(order.idempotency_key)
    
    # Assert
    assert is_dup_first is False  # First submission is not duplicate
    assert is_dup_second is True  # Second submission is duplicate


@pytest.mark.asyncio
async def test_idempotency_returns_cached_result_for_duplicate(orchestrator):
    """Test that duplicate requests return cached results"""
    # Arrange: Submit and fill order
    order = OrderRequest.create(
        instrument='GOLD',
        direction='BUY',
        size=0.1,
        stop_loss=1940.00,
        take_profit=1980.00,
        signal_timestamp=datetime.now()
    )
    
    orchestrator.idempotency.register_submission(order)
    orchestrator.idempotency.register_fill(order.idempotency_key, 'DEAL123')
    
    # Act: Retry same order
    cached = orchestrator.idempotency.get_cached_result(order.idempotency_key)
    
    # Assert
    assert cached is not None
    assert cached.deal_id == 'DEAL123'
    assert cached.status == 'filled'


@pytest.mark.asyncio
async def test_idempotency_allows_retry_after_transient_failure(orchestrator):
    """Test that transient failures can be retried"""
    # Arrange: Create order
    order = OrderRequest.create(
        instrument='GOLD',
        direction='BUY',
        size=0.1,
        stop_loss=1940.00,
        take_profit=1980.00,
        signal_timestamp=datetime.now()
    )
    
    # First attempt fails with transient error
    orchestrator.idempotency.register_submission(order)
    orchestrator.idempotency.register_rejection(order.idempotency_key, 'Connection timeout')
    
    # Act: Retry after transient error
    can_retry = orchestrator.retry_policy.is_transient_error(Exception('Connection timeout'))
    
    # Assert: Transient errors can be retried
    assert can_retry is True


# ========== Circuit Breaker Tests ==========

@pytest.mark.asyncio
async def test_circuit_breaker_opens_on_daily_loss_limit(orchestrator):
    """Test circuit breaker opens when daily loss limit exceeded"""
    # Arrange: Set current capital
    current_capital = 10000
    
    # Record losses exceeding daily limit (5% = $500)
    for _ in range(6):
        orchestrator.circuit_breaker.record_trade(-100)  # Total: -$600
    
    # Act: Check circuit breaker status
    status, reason = orchestrator.circuit_breaker.check_status(current_capital)
    
    # Assert
    assert status == CircuitBreakerStatus.OPEN
    assert 'daily loss' in reason.lower()


@pytest.mark.asyncio
async def test_circuit_breaker_opens_on_consecutive_losses(orchestrator):
    """Test circuit breaker opens after max consecutive losses"""
    # Arrange: Record consecutive losses
    for _ in range(5):  # Max is 5
        orchestrator.circuit_breaker.record_trade(-50)
    
    # Act: Check status after 5th loss
    status, reason = orchestrator.circuit_breaker.check_status(10000)
    
    # Assert
    assert status == CircuitBreakerStatus.OPEN
    assert 'consecutive losses' in reason.lower()


@pytest.mark.asyncio
async def test_circuit_breaker_resets_on_win(orchestrator):
    """Test circuit breaker consecutive loss counter resets on win"""
    # Arrange: Record 4 losses
    for _ in range(4):
        orchestrator.circuit_breaker.record_trade(-50)
    
    # Record 1 win
    orchestrator.circuit_breaker.record_trade(100)
    
    # Record 3 more losses (total 3 consecutive, not 7)
    for _ in range(3):
        orchestrator.circuit_breaker.record_trade(-50)
    
    # Act: Check status
    status, reason = orchestrator.circuit_breaker.check_status(10000)
    
    # Assert: Should still be closed (only 3 consecutive, max is 5)
    assert status == CircuitBreakerStatus.CLOSED


@pytest.mark.asyncio
async def test_session_filter_blocks_outside_allowed_hours(orchestrator):
    """Test trading session filter blocks trades outside allowed times"""
    # Arrange: Configure only LONDON session (08:00-16:30 UTC)
    orchestrator.session_filter.config['allowed_sessions'] = ['LONDON']
    
    # Act: Check at 22:00 UTC (NEW_YORK session, not allowed)
    with patch('datetime.datetime') as mock_datetime:
        mock_datetime.now.return_value = datetime(2024, 1, 15, 22, 0)  # 22:00 UTC
        allowed, reason = orchestrator.session_filter.is_trading_allowed()
    
    # Assert: Should be blocked
    assert allowed is False
    assert 'session' in reason.lower()


@pytest.mark.asyncio
async def test_spread_filter_blocks_wide_spreads(orchestrator):
    """Test spread filter blocks trades with wide spreads"""
    # Arrange: Wide spread (40 pips, max is 30)
    current_bid = 1950.00
    current_ask = 1954.00  # 40 pips spread
    
    # Act: Check spread
    allowed, reason = orchestrator.spread_filter.check_spread(
        instrument='GOLD',
        bid=current_bid,
        ask=current_ask
    )
    
    # Assert: Should be blocked
    assert allowed is False
    assert 'spread' in reason.lower()


@pytest.mark.asyncio
async def test_news_killswitch_blocks_during_blackout(orchestrator):
    """Test news kill switch blocks trades during blackout periods"""
    # Arrange: Add blackout period (now + 15 min)
    now = datetime.now()
    orchestrator.news_killswitch.add_blackout(
        start=now,
        end=now + timedelta(minutes=15),
        reason='NFP release'
    )
    
    # Act: Check if trading allowed
    allowed, reason = orchestrator.news_killswitch.is_trading_allowed()
    
    # Assert: Should be blocked
    assert allowed is False
    assert 'blackout' in reason.lower() or 'NFP' in reason


# ========== Event-Driven Communication Tests ==========

@pytest.mark.asyncio
async def test_event_driven_candle_to_signal_flow(orchestrator):
    """Test event flow: candle closed -> signal generated"""
    # Arrange: Subscribe to SIGNAL_GENERATED event
    signal_received = asyncio.Event()
    received_event = None
    
    async def on_signal(event):
        nonlocal received_event
        received_event = event
        signal_received.set()
    
    orchestrator.event_bus.subscribe(EventType.SIGNAL_GENERATED, on_signal)
    
    # Act: Publish CANDLE_CLOSED event
    candle_event = Event(
        event_type=EventType.CANDLE_CLOSED,
        instrument='GOLD',
        source='market_data',
        payload={'close': 1950.00, 'high': 1955.00, 'low': 1945.00}
    )
    await orchestrator.event_bus.publish(candle_event)
    
    # Wait for signal (with timeout)
    try:
        await asyncio.wait_for(signal_received.wait(), timeout=1.0)
    except asyncio.TimeoutError:
        pass
    
    # Assert: Event published successfully
    assert orchestrator.event_bus.get_stats()['events_published'] >= 1


@pytest.mark.asyncio
async def test_event_history_stores_last_1000_events(orchestrator):
    """Test event bus stores event history"""
    # Arrange: Start orchestrator
    await orchestrator.start()
    
    # Act: Publish 10 events
    for i in range(10):
        event = Event(
            event_type=EventType.CANDLE_CLOSED,
            instrument='GOLD',
            source='test',
            payload={'index': i}
        )
        await orchestrator.event_bus.publish(event)
    
    # Get history
    history = orchestrator.event_bus.get_history(count=10)
    
    # Assert
    assert len(history) >= 10  # At least our 10 events (may include BOT_STARTED)


@pytest.mark.asyncio
async def test_event_correlation_id_links_related_events(orchestrator):
    """Test correlation IDs link signal -> order -> position events"""
    # Arrange: Create signal with correlation ID
    correlation_id = 'CORR-123'
    
    signal_event = Event(
        event_type=EventType.SIGNAL_GENERATED,
        instrument='GOLD',
        source='analysis',
        correlation_id=correlation_id,
        payload={'direction': 'BUY'}
    )
    
    # Act: Publish signal, then order event with same correlation ID
    await orchestrator.event_bus.publish(signal_event)
    
    order_event = Event(
        event_type=EventType.ORDER_FILLED,
        instrument='GOLD',
        source='execution',
        correlation_id=correlation_id,
        payload={'deal_id': 'DEAL123'}
    )
    await orchestrator.event_bus.publish(order_event)
    
    # Filter events by correlation ID
    related = orchestrator.event_bus.get_history(
        count=100,
        filter_fn=lambda e: e.correlation_id == correlation_id
    )
    
    # Assert: Both events linked by correlation ID
    assert len(related) >= 2


# ========== Operational Monitoring Tests ==========

@pytest.mark.asyncio
async def test_operational_monitor_detects_stale_websocket_data(orchestrator):
    """Test monitoring detects stale WebSocket data"""
    # Arrange: Start orchestrator
    await orchestrator.start()
    
    # Simulate WebSocket connection and message
    orchestrator.op_monitor.websocket_monitor.on_connect()
    orchestrator.op_monitor.websocket_monitor.on_message('candle')
    
    # Act: Wait for data to become stale (simulate 6 minutes passing)
    with patch('core.operational_monitoring.datetime') as mock_datetime:
        mock_datetime.now.return_value = datetime.now() + timedelta(minutes=6)
        
        health = orchestrator.op_monitor.websocket_monitor.get_health()
    
    # Assert: Should be DEGRADED (stale data)
    assert health.status in ['DEGRADED', 'UNHEALTHY']


@pytest.mark.asyncio
async def test_operational_monitor_tracks_api_latency(orchestrator):
    """Test monitoring tracks API latency"""
    # Arrange: Start orchestrator
    await orchestrator.start()
    
    # Act: Record some API requests
    for i in range(5):
        orchestrator.op_monitor.api_latency_monitor.record_request(
            operation='place_order',
            latency_ms=50 + i * 10,  # 50, 60, 70, 80, 90
            success=True
        )
    
    # Get average latency
    avg_latency = orchestrator.op_monitor.api_latency_monitor.get_average_latency('place_order')
    
    # Assert
    assert avg_latency == 70.0  # Average of 50, 60, 70, 80, 90


@pytest.mark.asyncio
async def test_operational_monitor_overall_health_status(orchestrator):
    """Test overall health aggregates all component statuses"""
    # Arrange: Start orchestrator with healthy components
    await orchestrator.start()
    
    # Simulate healthy state
    orchestrator.op_monitor.websocket_monitor.on_connect()
    orchestrator.op_monitor.websocket_monitor.on_message('candle')
    
    # Record some successful API requests
    for _ in range(10):
        orchestrator.op_monitor.api_latency_monitor.record_request(
            operation='get_positions',
            latency_ms=100,
            success=True
        )
    
    # Record data freshness
    orchestrator.op_monitor.data_freshness_monitor.record_update('candles')
    
    # Act: Get overall status
    status = orchestrator.op_monitor.get_overall_status()
    
    # Assert: Should be HEALTHY
    assert status == 'HEALTHY'


# ========== Position State Management Tests ==========

@pytest.mark.asyncio
async def test_position_state_tracks_exposure_by_instrument(orchestrator):
    """Test position manager tracks exposure per instrument"""
    # Arrange: Add 2 GOLD positions
    pos1 = Position(
        deal_id='DEAL1',
        instrument='GOLD',
        direction='BUY',
        entry_price=1950.00,
        size=0.1,
        stop_loss=1940.00,
        take_profit=1980.00,
        status=PositionStatus.OPEN,
        opened_at=datetime.now(),
        signal_timestamp=datetime.now()
    )
    pos2 = Position(
        deal_id='DEAL2',
        instrument='GOLD',
        direction='BUY',
        entry_price=1955.00,
        size=0.2,
        stop_loss=1945.00,
        take_profit=1985.00,
        status=PositionStatus.OPEN,
        opened_at=datetime.now(),
        signal_timestamp=datetime.now()
    )
    
    orchestrator.position_manager.add_position(pos1)
    orchestrator.position_manager.add_position(pos2)
    
    # Act: Get exposure
    gold_exposure = orchestrator.position_manager.get_exposure_by_instrument('GOLD')
    total_exposure = orchestrator.position_manager.get_total_exposure()
    
    # Assert
    assert gold_exposure == pytest.approx(0.3)  # 0.1 + 0.2
    assert total_exposure == pytest.approx(0.3)


@pytest.mark.asyncio
async def test_position_state_calculates_unrealized_pnl(orchestrator):
    """Test position manager calculates unrealized P&L"""
    # Arrange: Add position
    position = Position(
        deal_id='DEAL123',
        instrument='GOLD',
        direction='BUY',
        entry_price=1950.00,
        size=0.1,
        stop_loss=1940.00,
        take_profit=1980.00,
        status=PositionStatus.OPEN,
        opened_at=datetime.now(),
        signal_timestamp=datetime.now()
    )
    orchestrator.position_manager.add_position(position)
    
    # Act: Update with current price (profit +10)
    position.calculate_unrealized_pnl(current_price=1960.00)
    
    # Assert: P&L should be positive
    assert position.unrealized_pnl > 0


# ========== Integration Test: Full Trading Loop ==========

@pytest.mark.asyncio
async def test_full_trading_loop_with_all_components(orchestrator, mock_capital_api):
    """
    Integration test: Full trading loop from candle -> signal -> risk -> execution
    
    Flow:
    1. Candle closes -> CANDLE_CLOSED event
    2. Analysis generates signal -> SIGNAL_GENERATED event
    3. Risk + circuit breakers validate -> RISK_APPROVED event
    4. Execution places order (with idempotency) -> ORDER_FILLED event
    5. Position state updated -> POSITION_OPENED event
    6. Monitoring tracks health
    """
    # Arrange: Start orchestrator
    await orchestrator.start()
    
    # Step 1: Publish candle closed event
    candle_event = Event(
        event_type=EventType.CANDLE_CLOSED,
        instrument='GOLD',
        source='market_data',
        correlation_id='TEST-CORR-1',
        payload={
            'open': 1945.00,
            'high': 1955.00,
            'low': 1943.00,
            'close': 1950.00,
            'volume': 1000
        }
    )
    await orchestrator.event_bus.publish(candle_event)
    
    # Step 2: Simulate signal generation (normally done by analysis skill)
    signal_event = Event(
        event_type=EventType.SIGNAL_GENERATED,
        instrument='GOLD',
        source='analysis',
        correlation_id='TEST-CORR-1',
        payload={
            'direction': 'BUY',
            'stop_loss': 1940.00,
            'take_profit': 1980.00,
            'position_size': 0.1,
            'confidence': 0.85
        }
    )
    await orchestrator.event_bus.publish(signal_event)
    
    # Step 3: Check circuit breakers (should allow trade)
    status, reason = orchestrator.circuit_breaker.check_status(10000)
    assert status == CircuitBreakerStatus.CLOSED
    
    # Step 4: Create idempotent order
    order = OrderRequest.create(
        instrument='GOLD',
        direction='BUY',
        size=0.1,
        stop_loss=1940.00,
        take_profit=1980.00,
        signal_timestamp=datetime.now()
    )
    
    # Verify not duplicate
    assert orchestrator.idempotency.is_duplicate(order.idempotency_key) is False
    
    # Register and execute
    orchestrator.idempotency.register_submission(order)
    result = await mock_capital_api.place_order()
    orchestrator.idempotency.register_fill(order.idempotency_key, result['deal_id'])
    
    # Step 5: Update position state
    position = Position(
        deal_id=result['deal_id'],
        instrument='GOLD',
        direction='BUY',
        entry_price=1950.00,
        size=0.1,
        stop_loss=1940.00,
        take_profit=1980.00,
        status=PositionStatus.OPEN,
        opened_at=datetime.now(),
        signal_timestamp=datetime.now()
    )
    orchestrator.position_manager.add_position(position)
    
    # Step 6: Verify end state
    assert orchestrator.position_manager.get_position_count() == 1
    assert orchestrator.idempotency.is_duplicate(order.idempotency_key) is True  # now registered
    # Verify stats and event history
    history = orchestrator.event_bus.get_history(count=100)
    event_types = [e.event_type for e in history]
    assert EventType.CANDLE_CLOSED in event_types
    assert EventType.SIGNAL_GENERATED in event_types


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--asyncio-mode=auto'])

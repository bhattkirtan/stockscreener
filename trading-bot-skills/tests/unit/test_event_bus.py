"""
Unit tests for Event Bus
Tests pub/sub, event history, correlation IDs, and dead letter queue
"""
import pytest
import asyncio
from datetime import datetime

from core.event_bus import (
    Event, EventType, EventBus, EventFilter,
    create_candle_closed_event,
    create_signal_generated_event,
    create_risk_approved_event,
    create_order_filled_event,
    create_position_closed_event,
    create_bot_error_event
)


# ========== Event Tests ==========

def test_event_creation():
    """Test creating an event"""
    event = Event(
        event_type=EventType.CANDLE_CLOSED,
        instrument='GOLD',
        source='market_data',
        payload={'close': 1950.00, 'high': 1955.00, 'low': 1945.00}
    )
    
    assert event.event_type == EventType.CANDLE_CLOSED
    assert event.instrument == 'GOLD'
    assert event.source == 'market_data'
    assert event.payload['close'] == 1950.00
    assert event.event_id is not None
    assert event.timestamp is not None


def test_event_with_correlation_id():
    """Test event with correlation ID"""
    event = Event(
        event_type=EventType.SIGNAL_GENERATED,
        instrument='GOLD',
        source='analysis',
        correlation_id='CORR-123',
        payload={'direction': 'BUY'}
    )
    
    assert event.correlation_id == 'CORR-123'


# ========== Event Builders Tests ==========

def test_create_candle_closed_event():
    """Test candle closed event builder"""
    candle = {
        'open': 1945.00,
        'high': 1955.00,
        'low': 1943.00,
        'close': 1950.00,
        'volume': 1000
    }
    
    event = create_candle_closed_event(
        candle=candle,
        instrument='GOLD',
        source='market_data'
    )
    
    assert event.event_type == EventType.CANDLE_CLOSED
    assert event.instrument == 'GOLD'
    assert event.payload == candle


def test_create_signal_generated_event():
    """Test signal generated event builder"""
    event = create_signal_generated_event(
        instrument='GOLD',
        signal='BUY',
        stop_loss=1940.00,
        take_profit=1980.00,
        confidence=0.85,
        correlation_id='CORR-123'
    )
    
    assert event.event_type == EventType.SIGNAL_GENERATED
    assert event.instrument == 'GOLD'
    assert event.payload['signal'] == 'BUY'
    assert event.correlation_id == 'CORR-123'


def test_create_risk_approved_event():
    """Test risk approved event builder"""
    event = create_risk_approved_event(
        instrument='GOLD',
        signal='BUY',
        position_size=0.1,
        stop_loss=1940.00,
        take_profit=1980.00,
        correlation_id='CORR-123'
    )
    
    assert event.event_type == EventType.RISK_APPROVED
    assert event.payload['position_size'] == 0.1


def test_create_order_filled_event():
    """Test order filled event builder"""
    event = create_order_filled_event(
        deal_id='DEAL123',
        instrument='GOLD',
        direction='BUY',
        entry_price=1950.00,
        size=0.1,
        stop_loss=1940.00,
        take_profit=1980.00,
        correlation_id='CORR-123'
    )
    
    assert event.event_type == EventType.ORDER_FILLED
    assert event.payload['deal_id'] == 'DEAL123'


def test_create_position_closed_event():
    """Test position closed event builder"""
    event = create_position_closed_event(
        deal_id='DEAL123',
        instrument='GOLD',
        close_price=1980.00,
        pnl=300.00,
        close_reason='take_profit',
        correlation_id='CORR-123'
    )
    
    assert event.event_type == EventType.POSITION_CLOSED
    assert event.payload['pnl'] == 300.00


def test_create_bot_error_event():
    """Test bot error event builder"""
    event = create_bot_error_event(
        error_message='Connection timeout',
        location='execution.place_order',
        severity='HIGH'
    )
    
    assert event.event_type == EventType.BOT_ERROR
    assert event.payload['severity'] == 'HIGH'


# ========== EventBus Tests ==========

@pytest.fixture
def event_bus():
    """Create event bus"""
    return EventBus(history_size=100)


@pytest.mark.asyncio
async def test_subscribe_and_publish(event_bus):
    """Test subscribing to events and publishing"""
    received_events = []
    
    async def handler(event: Event):
        received_events.append(event)
    
    # Subscribe
    event_bus.subscribe(EventType.CANDLE_CLOSED, handler)
    
    # Publish
    event = Event(
        event_type=EventType.CANDLE_CLOSED,
        instrument='GOLD',
        source='market_data',
        payload={'close': 1950.00}
    )
    await event_bus.publish(event)
    
    # Wait for async dispatch
    await asyncio.sleep(0.1)
    
    # Handler should have received event
    assert len(received_events) == 1
    assert received_events[0].instrument == 'GOLD'


@pytest.mark.asyncio
async def test_multiple_subscribers(event_bus):
    """Test multiple subscribers receive same event"""
    received_1 = []
    received_2 = []
    
    async def handler1(event: Event):
        received_1.append(event)
    
    async def handler2(event: Event):
        received_2.append(event)
    
    # Subscribe both handlers
    event_bus.subscribe(EventType.SIGNAL_GENERATED, handler1)
    event_bus.subscribe(EventType.SIGNAL_GENERATED, handler2)
    
    # Publish
    event = Event(
        event_type=EventType.SIGNAL_GENERATED,
        instrument='GOLD',
        source='analysis',
        payload={'direction': 'BUY'}
    )
    await event_bus.publish(event)
    
    # Wait for async dispatch
    await asyncio.sleep(0.1)
    
    # Both handlers should receive event
    assert len(received_1) == 1
    assert len(received_2) == 1


@pytest.mark.asyncio
async def test_event_history_stored(event_bus):
    """Test event bus stores event history"""
    # Publish events
    for i in range(5):
        event = Event(
            event_type=EventType.CANDLE_CLOSED,
            instrument='GOLD',
            source='market_data',
            payload={'index': i}
        )
        await event_bus.publish(event)
    
    # Get history
    history = event_bus.get_history(count=5)
    
    assert len(history) == 5
    assert history[-1].payload['index'] == 4  # Most recent


@pytest.mark.asyncio
async def test_event_history_limited_by_size(event_bus):
    """Test event history limited to max size"""
    # Create event bus with small history
    small_bus = EventBus(history_size=3)
    
    # Publish 5 events
    for i in range(5):
        event = Event(
            event_type=EventType.CANDLE_CLOSED,
            instrument='GOLD',
            source='market_data',
            payload={'index': i}
        )
        await small_bus.publish(event)
    
    # History should only contain last 3
    history = small_bus.get_history(count=10)
    
    assert len(history) == 3
    assert history[0].payload['index'] == 2  # Oldest retained
    assert history[-1].payload['index'] == 4  # Most recent


@pytest.mark.asyncio
async def test_failed_handler_goes_to_dead_letter_queue(event_bus):
    """Test failed handlers tracked in dead letter queue"""
    async def failing_handler(event: Event):
        raise Exception('Handler failed')
    
    # Subscribe failing handler
    event_bus.subscribe(EventType.SIGNAL_GENERATED, failing_handler)
    
    # Publish event
    event = Event(
        event_type=EventType.SIGNAL_GENERATED,
        instrument='GOLD',
        source='analysis',
        payload={'direction': 'BUY'}
    )
    await event_bus.publish(event)
    
    # Wait for async dispatch
    await asyncio.sleep(0.1)
    
    # Check dead letter queue
    dead_letters = event_bus.dead_letter_queue
    
    assert len(dead_letters) > 0


@pytest.mark.asyncio
async def test_one_failing_handler_does_not_break_others(event_bus):
    """Test one failing handler doesn't prevent others from executing"""
    received_good = []
    
    async def failing_handler(event: Event):
        raise Exception('Handler failed')
    
    async def good_handler(event: Event):
        received_good.append(event)
    
    # Subscribe both handlers
    event_bus.subscribe(EventType.SIGNAL_GENERATED, failing_handler)
    event_bus.subscribe(EventType.SIGNAL_GENERATED, good_handler)
    
    # Publish event
    event = Event(
        event_type=EventType.SIGNAL_GENERATED,
        instrument='GOLD',
        source='analysis',
        payload={'direction': 'BUY'}
    )
    await event_bus.publish(event)
    
    # Wait for async dispatch
    await asyncio.sleep(0.1)
    
    # Good handler should still receive event
    assert len(received_good) == 1


@pytest.mark.asyncio
async def test_event_statistics(event_bus):
    """Test event bus statistics tracking"""
    # Subscribe handler
    async def handler(event: Event):
        pass
    
    event_bus.subscribe(EventType.CANDLE_CLOSED, handler)
    
    # Publish events
    for _ in range(3):
        event = Event(
            event_type=EventType.CANDLE_CLOSED,
            instrument='GOLD',
            source='market_data',
            payload={'close': 1950.00}
        )
        await event_bus.publish(event)
    
    # Wait for processing
    await asyncio.sleep(0.1)
    
    # Get stats
    stats = event_bus.get_stats()
    
    assert stats['events_published'] == 3
    assert stats['events_processed'] >= 3


# ========== EventFilter Tests ==========

def test_event_filter_by_instrument():
    """Test filtering events by instrument"""
    event_filter = EventFilter(instrument='GOLD')
    
    gold_event = Event(
        event_type=EventType.CANDLE_CLOSED,
        instrument='GOLD',
        source='market_data',
        payload={}
    )
    
    eurusd_event = Event(
        event_type=EventType.CANDLE_CLOSED,
        instrument='EURUSD',
        source='market_data',
        payload={}
    )
    
    assert event_filter.matches(gold_event) is True
    assert event_filter.matches(eurusd_event) is False


def test_event_filter_by_source():
    """Test filtering events by source"""
    event_filter = EventFilter(source='analysis')
    
    analysis_event = Event(
        event_type=EventType.SIGNAL_GENERATED,
        instrument='GOLD',
        source='analysis',
        payload={}
    )
    
    market_event = Event(
        event_type=EventType.CANDLE_CLOSED,
        instrument='GOLD',
        source='market_data',
        payload={}
    )
    
    assert event_filter.matches(analysis_event) is True
    assert event_filter.matches(market_event) is False


def test_event_filter_by_correlation_id():
    """Test filtering events by correlation ID"""
    event_filter = EventFilter(correlation_id='CORR-123')
    
    correlated_event = Event(
        event_type=EventType.SIGNAL_GENERATED,
        instrument='GOLD',
        source='analysis',
        correlation_id='CORR-123',
        payload={}
    )
    
    other_event = Event(
        event_type=EventType.SIGNAL_GENERATED,
        instrument='GOLD',
        source='analysis',
        correlation_id='CORR-456',
        payload={}
    )
    
    assert event_filter.matches(correlated_event) is True
    assert event_filter.matches(other_event) is False


@pytest.mark.asyncio
async def test_correlation_id_links_events(event_bus):
    """Test correlation IDs link related events"""
    correlation_id = 'FLOW-123'
    
    # Publish related events with same correlation ID
    signal_event = create_signal_generated_event(
        instrument='GOLD',
        signal='BUY',
        stop_loss=1940.00,
        take_profit=1980.00,
        confidence=0.85,
        correlation_id=correlation_id
    )
    
    order_event = create_order_filled_event(
        deal_id='DEAL123',
        instrument='GOLD',
        direction='BUY',
        entry_price=1950.00,
        size=0.1,
        stop_loss=1940.00,
        take_profit=1980.00,
        correlation_id=correlation_id
    )
    
    position_event = create_position_closed_event(
        deal_id='DEAL123',
        instrument='GOLD',
        close_price=1980.00,
        pnl=300.00,
        close_reason='take_profit',
        correlation_id=correlation_id
    )
    
    await event_bus.publish(signal_event)
    await event_bus.publish(order_event)
    await event_bus.publish(position_event)
    
    # Filter events by correlation ID
    history = event_bus.get_history(count=100)
    related = [e for e in history if e.correlation_id == correlation_id]
    
    assert len(related) == 3
    assert related[0].event_type == EventType.SIGNAL_GENERATED
    assert related[1].event_type == EventType.ORDER_FILLED
    assert related[2].event_type == EventType.POSITION_CLOSED


if __name__ == '__main__':
    pytest.main([__file__, '-v'])

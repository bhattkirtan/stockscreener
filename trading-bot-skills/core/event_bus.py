"""
Event Bus - Event-Driven Architecture
Decouples skills through explicit event contracts.
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Set
from enum import Enum
import asyncio
import uuid


class EventType(Enum):
    """
    Canonical event types for trading system.
    Each event represents a state change or action completion.
    """
    # Market Data Events
    CANDLE_CLOSED = "CANDLE_CLOSED"
    QUOTE_UPDATED = "QUOTE_UPDATED"
    MARKET_DATA_STALE = "MARKET_DATA_STALE"
    
    # Analysis Events
    SIGNAL_GENERATED = "SIGNAL_GENERATED"
    SIGNAL_REJECTED = "SIGNAL_REJECTED"
    
    # Risk Events
    RISK_APPROVED = "RISK_APPROVED"
    RISK_REJECTED = "RISK_REJECTED"
    CIRCUIT_BREAKER_OPENED = "CIRCUIT_BREAKER_OPENED"
    CIRCUIT_BREAKER_CLOSED = "CIRCUIT_BREAKER_CLOSED"
    
    # Execution Events
    ORDER_SUBMITTED = "ORDER_SUBMITTED"
    ORDER_ACKNOWLEDGED = "ORDER_ACKNOWLEDGED"
    ORDER_FILLED = "ORDER_FILLED"
    ORDER_REJECTED = "ORDER_REJECTED"
    ORDER_CANCELLED = "ORDER_CANCELLED"
    ORDER_TIMEOUT = "ORDER_TIMEOUT"
    
    # Position Events
    POSITION_OPENED = "POSITION_OPENED"
    POSITION_UPDATED = "POSITION_UPDATED"
    POSITION_CLOSED = "POSITION_CLOSED"
    
    # P&L Events
    PNL_UPDATED = "PNL_UPDATED"
    
    # System Events
    BOT_STARTED = "BOT_STARTED"
    BOT_STOPPED = "BOT_STOPPED"
    BOT_ERROR = "BOT_ERROR"
    HEARTBEAT_MISSED = "HEARTBEAT_MISSED"
    RECONCILIATION_COMPLETED = "RECONCILIATION_COMPLETED"
    RECONCILIATION_FAILED = "RECONCILIATION_FAILED"


@dataclass
class Event:
    """
    Base event with standard fields.
    All events inherit from this structure.
    """
    # Event metadata
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    event_type: EventType = None
    timestamp: datetime = field(default_factory=datetime.now)
    
    # Context
    instrument: Optional[str] = None
    strategy_id: str = "default"
    correlation_id: Optional[str] = None  # Link related events
    
    # Source tracking
    source: str = "unknown"
    payload_version: str = "1.0"
    
    # Payload (event-specific data)
    payload: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for serialization"""
        return {
            'event_id': self.event_id,
            'event_type': self.event_type.value if self.event_type else None,
            'timestamp': self.timestamp.isoformat(),
            'instrument': self.instrument,
            'strategy_id': self.strategy_id,
            'correlation_id': self.correlation_id,
            'source': self.source,
            'payload_version': self.payload_version,
            'payload': self.payload
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'Event':
        """Reconstruct from dictionary"""
        return cls(
            event_id=data.get('event_id'),
            event_type=EventType(data['event_type']) if data.get('event_type') else None,
            timestamp=datetime.fromisoformat(data['timestamp']),
            instrument=data.get('instrument'),
            strategy_id=data.get('strategy_id', 'default'),
            correlation_id=data.get('correlation_id'),
            source=data.get('source', 'unknown'),
            payload_version=data.get('payload_version', '1.0'),
            payload=data.get('payload', {})
        )


# Type alias for event handlers
EventHandler = Callable[[Event], None]
AsyncEventHandler = Callable[[Event], asyncio.Future]


class EventBus:
    """
    Event bus for publish/subscribe messaging between skills.
    
    Features:
    - Async event dispatch
    - Multiple subscribers per event
    - Event filtering
    - Event history/replay
    - Dead letter queue for failed handlers
    
    This decouples skills - they communicate via events, not direct calls.
    """
    
    def __init__(self, history_size: int = 1000):
        """
        Initialize event bus.
        
        Args:
            history_size: Number of events to keep in history
        """
        self.history_size = history_size
        
        # Subscribers: event_type -> list of handlers
        self.subscribers: Dict[EventType, List[AsyncEventHandler]] = {}
        
        # Event history for replay/debugging
        self.event_history: List[Event] = []
        
        # Failed events (dead letter queue)
        self.dead_letter_queue: List[Tuple[Event, Exception]] = []
        
        # Statistics
        self.stats = {
            'events_published': 0,
            'events_processed': 0,
            'handler_failures': 0
        }
    
    def subscribe(self, event_type: EventType, handler: AsyncEventHandler) -> None:
        """
        Subscribe to event type.
        
        Args:
            event_type: Type of event to listen for
            handler: Async function to call when event occurs
        """
        if event_type not in self.subscribers:
            self.subscribers[event_type] = []
        
        self.subscribers[event_type].append(handler)
        print(f"✅ Subscribed to {event_type.value}: {handler.__name__}")
    
    def unsubscribe(self, event_type: EventType, handler: AsyncEventHandler) -> None:
        """Unsubscribe from event type"""
        if event_type in self.subscribers:
            self.subscribers[event_type] = [
                h for h in self.subscribers[event_type] if h != handler
            ]
    
    async def publish(self, event: Event) -> None:
        """
        Publish event to all subscribers.
        
        Args:
            event: Event to publish
        """
        self.stats['events_published'] += 1
        
        # Add to history
        self.event_history.append(event)
        if len(self.event_history) > self.history_size:
            self.event_history.pop(0)
        
        # Get subscribers
        handlers = self.subscribers.get(event.event_type, [])
        
        if not handlers:
            print(f"ℹ️ No subscribers for {event.event_type.value}")
            return
        
        # Dispatch to handlers (in parallel)
        tasks = []
        for handler in handlers:
            try:
                task = asyncio.create_task(self._safe_handler_call(handler, event))
                tasks.append(task)
            except Exception as e:
                print(f"❌ Failed to create task for {handler.__name__}: {e}")
                self.dead_letter_queue.append((event, e))
                self.stats['handler_failures'] += 1
        
        # Wait for all handlers
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        
        self.stats['events_processed'] += 1
    
    async def _safe_handler_call(self, handler: AsyncEventHandler, event: Event) -> None:
        """
        Call handler with error handling.
        
        Prevents one failing handler from breaking others.
        """
        try:
            await handler(event)
        except Exception as e:
            print(f"❌ Handler {handler.__name__} failed for {event.event_type.value}: {e}")
            self.dead_letter_queue.append((event, e))
            self.stats['handler_failures'] += 1
    
    def get_history(self, event_type: Optional[EventType] = None, 
                    limit: int = 100) -> List[Event]:
        """
        Get event history.
        
        Args:
            event_type: Filter by type (None = all)
            limit: Maximum events to return
        
        Returns:
            List of events (newest first)
        """
        events = self.event_history
        
        if event_type:
            events = [e for e in events if e.event_type == event_type]
        
        return list(reversed(events[-limit:]))
    
    def get_stats(self) -> Dict:
        """Get event bus statistics"""
        return {
            **self.stats,
            'subscriber_count': sum(len(handlers) for handlers in self.subscribers.values()),
            'event_types_subscribed': len(self.subscribers),
            'history_size': len(self.event_history),
            'dead_letter_queue_size': len(self.dead_letter_queue)
        }
    
    def clear_history(self) -> None:
        """Clear event history"""
        self.event_history.clear()
    
    def clear_dead_letter_queue(self) -> None:
        """Clear failed events"""
        self.dead_letter_queue.clear()


# ========== Event Builders ==========
# Convenience functions for creating common events

def create_candle_closed_event(candle: Dict, source: str = "market_data") -> Event:
    """Create CANDLE_CLOSED event"""
    return Event(
        event_type=EventType.CANDLE_CLOSED,
        instrument=candle.get('instrument'),
        source=source,
        payload={
            'open': candle['open'],
            'high': candle['high'],
            'low': candle['low'],
            'close': candle['close'],
            'volume': candle.get('volume'),
            'timestamp': candle.get('timestamp')
        }
    )


def create_signal_generated_event(signal: str, entry_price: float, sl: float, tp: float,
                                   instrument: str, source: str = "analysis") -> Event:
    """Create SIGNAL_GENERATED event"""
    correlation_id = str(uuid.uuid4())  # Link signal to subsequent trades
    
    return Event(
        event_type=EventType.SIGNAL_GENERATED,
        instrument=instrument,
        source=source,
        correlation_id=correlation_id,
        payload={
            'signal': signal,
            'entry_price': entry_price,
            'stop_loss': sl,
            'take_profit': tp
        }
    )


def create_risk_approved_event(signal: str, position_size: float, 
                                correlation_id: str, source: str = "risk") -> Event:
    """Create RISK_APPROVED event"""
    return Event(
        event_type=EventType.RISK_APPROVED,
        source=source,
        correlation_id=correlation_id,
        payload={
            'signal': signal,
            'position_size': position_size
        }
    )


def create_order_filled_event(deal_id: str, instrument: str, direction: str,
                               entry_price: float, size: float,
                               correlation_id: str, source: str = "execution") -> Event:
    """Create ORDER_FILLED event"""
    return Event(
        event_type=EventType.ORDER_FILLED,
        instrument=instrument,
        source=source,
        correlation_id=correlation_id,
        payload={
            'deal_id': deal_id,
            'direction': direction,
            'entry_price': entry_price,
            'size': size
        }
    )


def create_position_closed_event(deal_id: str, instrument: str, close_price: float,
                                  realized_pnl: float, close_reason: str,
                                  correlation_id: str, source: str = "execution") -> Event:
    """Create POSITION_CLOSED event"""
    return Event(
        event_type=EventType.POSITION_CLOSED,
        instrument=instrument,
        source=source,
        correlation_id=correlation_id,
        payload={
            'deal_id': deal_id,
            'close_price': close_price,
            'realized_pnl': realized_pnl,
            'close_reason': close_reason
        }
    )


def create_bot_error_event(error_message: str, location: str, 
                           source: str = "orchestrator") -> Event:
    """Create BOT_ERROR event"""
    return Event(
        event_type=EventType.BOT_ERROR,
        source=source,
        payload={
            'error_message': error_message,
            'location': location
        }
    )


# ========== Event Filters ==========

class EventFilter:
    """
    Filter events based on criteria.
    Useful for conditional subscriptions.
    """
    
    @staticmethod
    def by_instrument(instrument: str) -> Callable[[Event], bool]:
        """Filter events by instrument"""
        def filter_func(event: Event) -> bool:
            return event.instrument == instrument
        return filter_func
    
    @staticmethod
    def by_source(source: str) -> Callable[[Event], bool]:
        """Filter events by source"""
        def filter_func(event: Event) -> bool:
            return event.source == source
        return filter_func
    
    @staticmethod
    def by_correlation_id(correlation_id: str) -> Callable[[Event], bool]:
        """Filter events by correlation ID (track related events)"""
        def filter_func(event: Event) -> bool:
            return event.correlation_id == correlation_id
        return filter_func


# ========== Example Usage ==========

async def example_usage():
    """Example of event-driven skill communication"""
    
    # Create event bus
    bus = EventBus()
    
    # Subscribe skills to events
    
    # Analysis skill subscribes to candle events
    async def on_candle_closed(event: Event):
        print(f"Analysis: Processing candle {event.payload['close']}")
        # Generate signal
        signal_event = create_signal_generated_event(
            signal='BUY',
            entry_price=event.payload['close'],
            sl=event.payload['close'] - 10,
            tp=event.payload['close'] + 20,
            instrument=event.instrument
        )
        await bus.publish(signal_event)
    
    bus.subscribe(EventType.CANDLE_CLOSED, on_candle_closed)
    
    # Risk skill subscribes to signals
    async def on_signal_generated(event: Event):
        print(f"Risk: Validating signal {event.payload['signal']}")
        # Approve signal
        approved_event = create_risk_approved_event(
            signal=event.payload['signal'],
            position_size=0.1,
            correlation_id=event.correlation_id
        )
        await bus.publish(approved_event)
    
    bus.subscribe(EventType.SIGNAL_GENERATED, on_signal_generated)
    
    # Execution skill subscribes to approved risks
    async def on_risk_approved(event: Event):
        print(f"Execution: Placing order for {event.payload['signal']}")
        # Simulate order fill
        filled_event = create_order_filled_event(
            deal_id='DEAL123',
            instrument='GOLD',
            direction=event.payload['signal'],
            entry_price=1950.0,
            size=event.payload['position_size'],
            correlation_id=event.correlation_id
        )
        await bus.publish(filled_event)
    
    bus.subscribe(EventType.RISK_APPROVED, on_risk_approved)
    
    # Publish candle event
    candle = {
        'instrument': 'GOLD',
        'open': 1945.0,
        'high': 1952.0,
        'low': 1943.0,
        'close': 1950.0,
        'volume': 1000
    }
    
    candle_event = create_candle_closed_event(candle)
    await bus.publish(candle_event)
    
    # Wait for async handlers
    await asyncio.sleep(0.1)
    
    print(f"\nEvent Bus Stats: {bus.get_stats()}")


if __name__ == '__main__':
    asyncio.run(example_usage())

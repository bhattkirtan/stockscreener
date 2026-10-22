"""
Market Data Skill
Fetches and manages market data from Capital.com WebSocket and REST API.
"""
from typing import Dict, List, Optional
from datetime import datetime, timedelta
from collections import deque
import logging
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from skills.base_skill import Skill, Context, SkillExecutionError

logger = logging.getLogger(__name__)


class M5toM15Aggregator:
    """Aggregates M5 candles to M15 bars (3 M5 candles = 1 M15 bar)"""
    
    def __init__(self):
        self.m5_buffer: deque = deque(maxlen=3)
        self.last_m15_time: Optional[datetime] = None
    
    def add_m5_candle(self, candle: Dict) -> Optional[Dict]:
        """
        Add M5 candle to buffer and return completed M15 bar if ready
        
        Args:
            candle: M5 OHLC candle with timestamp, open, high, low, close, volume
            
        Returns:
            M15 bar if complete, None otherwise
        """
        timestamp = candle.get('timestamp')
        if isinstance(timestamp, str):
            timestamp = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        
        self.m5_buffer.append(candle)
        
        if len(self.m5_buffer) < 3:
            return None
        
        # Check M15 alignment (00, 15, 30, 45 minutes)
        minute = timestamp.minute
        if minute not in [0, 15, 30, 45]:
            return None
        
        # Create M15 bar from 3 M5 candles
        buffer_list = list(self.m5_buffer)
        m15_bar = {
            'timestamp': timestamp,
            'open': buffer_list[0]['open'],
            'high': max(c['high'] for c in buffer_list),
            'low': min(c['low'] for c in buffer_list),
            'close': buffer_list[-1]['close'],
            'volume': sum(c.get('volume', 0) for c in buffer_list)
        }
        
        self.m5_buffer.clear()
        self.last_m15_time = timestamp
        
        return m15_bar


class MarketDataSkill(Skill):
    """
    Market data skill that manages candle history and live quotes.
    
    Responsibilities:
    - Buffer incoming candles (M5 or M15)
    - Maintain rolling history window
    - Aggregate M5 to M15 if needed
    - Deduplicate candles
    - Provide quote updates
    - Publish CANDLE_CLOSED events
    """
    
    def __init__(self, config: Dict, event_bus: Optional['EventBus'] = None):
        super().__init__(config, event_bus)
        
        self.instrument = config.get('instrument', 'GOLD')
        self.symbol = self.instrument  # Alias for tests
        self.timeframe = config.get('timeframe', 'M5')
        self.buffer_size = config.get('buffer_size', 100)
        self.dedup_enabled = config.get('dedup_enabled', True)
        
        # Candle history buffers
        self.m5_history: List[Dict] = []
        self.m15_history: List[Dict] = []
        
        # M5 to M15 aggregator
        self.aggregator = M5toM15Aggregator()
        
        # Deduplication.
        # `last_candle_timestamp` alone only catches an IMMEDIATE repeat. A
        # reconnect that replays the last few bars arrives as e.g. 7,8,9 after
        # 9, and since 7 != 9 the whole replay was accepted: 13 CANDLE_CLOSED
        # events for 10 distinct bars, with duplicates landing in the analysis
        # buffer and skewing every indicator computed over it. A bounded set of
        # the timestamps already seen suppresses the replay exactly.
        self.last_candle_timestamp = None
        self._seen_timestamps: set = set()
        self._seen_order: deque = deque()
        
        # Last quote
        self.last_quote: Optional[Dict] = None
        
        print(f"📊 Market Data Skill initialized: {self.instrument} {self.timeframe}, buffer={self.buffer_size}")
    
    def _is_duplicate_candle(self, candle_ts) -> bool:
        """
        True if this bar has already been processed.

        Returns False (and records the timestamp) for a genuinely new bar. The
        seen-set is capped at the buffer size, with a floor, so a long-running
        bot does not grow it without bound; evicting in arrival order means the
        only timestamps forgotten are ones already trimmed from the buffer.
        """
        if candle_ts in self._seen_timestamps:
            return True

        self._seen_timestamps.add(candle_ts)
        self._seen_order.append(candle_ts)
        cap = max(self.buffer_size, 500)
        while len(self._seen_order) > cap:
            self._seen_timestamps.discard(self._seen_order.popleft())

        self.last_candle_timestamp = candle_ts
        return False

    async def process_candle(self, candle: Dict) -> None:
        """
        Process incoming candle and publish CANDLE_CLOSED event.
        
        Args:
            candle: Dict with timestamp, open, high, low, close, volume
        """
        # Validate candle
        required_fields = ['timestamp', 'open', 'high', 'low', 'close']
        if not all(field in candle for field in required_fields):
            print(f"⚠️ Invalid candle (missing fields): {candle.keys()}")
            return
        
        # Deduplicate
        if self.dedup_enabled:
            candle_ts = candle.get('timestamp')
            if self._is_duplicate_candle(candle_ts):
                logger.debug(f"⏭️ Skipping duplicate candle: {candle_ts}")
                return
        
        # Add to M5 history
        self.m5_history.append(candle)
        
        # Trim buffer
        if len(self.m5_history) > self.buffer_size:
            self.m5_history = self.m5_history[-self.buffer_size:]
        
        # Sort by timestamp to maintain order
        self.m5_history.sort(key=lambda c: c.get('timestamp'))
        
        # If using M15, aggregate M5 to M15
        published_candle = candle
        if self.timeframe == 'M15':
            m15_bar = self.aggregator.add_m5_candle(candle)
            if m15_bar:
                self.m15_history.append(m15_bar)
                if len(self.m15_history) > self.buffer_size:
                    self.m15_history = self.m15_history[-self.buffer_size:]
                
                print(f"✅ M15 bar created: {m15_bar['timestamp']}")
                published_candle = m15_bar
            else:
                # Not enough M5 candles yet for M15 bar
                return  # Don't publish partial M15
        
        # Publish CANDLE_CLOSED event
        if self.event_bus:
            from core.event_bus import Event, EventType
            event = Event(
                event_type=EventType.CANDLE_CLOSED,
                instrument=self.instrument,
                source='market_data',
                payload={
                    'candle': published_candle,
                    'timeframe': self.timeframe
                }
            )
            await self.event_bus.publish(event)
    
    def get_candle_history(self) -> List[Dict]:
        """Get current candle history based on timeframe"""
        if self.timeframe == 'M15':
            return self.m15_history
        else:
            return self.m5_history
    
    async def execute(self, context: Context) -> Context:
        """
        Process incoming market data and update context
        
        Args:
            context: Context with current_candle or quote data
            
        Returns:
            Updated context with candle_history
        """
        # Process candle if present
        if context.current_candle:
            candle = context.current_candle
            
            # Deduplicate — same rule AND same on/off flag as process_candle,
            # so the two agree. NOTE this is the path the live bot actually
            # runs (trading_orchestrator.py:115); `process_candle` has no
            # production callers and is exercised only by tests. The flag used
            # to be ignored here, so `dedup_enabled: false` silently had no
            # effect on live.
            if self.dedup_enabled:
                candle_ts = candle.get('timestamp')
                if self._is_duplicate_candle(candle_ts):
                    logger.debug(f"⏭️ Skipping duplicate candle: {candle_ts}")
                    return context
            
            # Add to M5 history
            self.m5_history.append(candle)
            
            # Trim buffer
            if len(self.m5_history) > self.buffer_size:
                self.m5_history = self.m5_history[-self.buffer_size:]
            
            # If using M15, aggregate M5 to M15
            if self.timeframe == 'M15':
                m15_bar = self.aggregator.add_m5_candle(candle)
                if m15_bar:
                    self.m15_history.append(m15_bar)
                    if len(self.m15_history) > self.buffer_size:
                        self.m15_history = self.m15_history[-self.buffer_size:]
                    
                    print(f"✅ M15 bar created: {m15_bar['timestamp']}")
                    context.candle_history = self.m15_history
                else:
                    # Not enough M5 candles yet for M15 bar
                    context.candle_history = self.m15_history
            else:
                # Using M5 directly
                context.candle_history = self.m5_history
            
        return context
    
    def validate_config(self) -> bool:
        """Validate market data configuration"""
        required = ['instrument', 'timeframe']
        for key in required:
            if key not in self.config:
                raise SkillExecutionError(f"Missing required config: {key}")
        
        if self.timeframe not in ['M5', 'M15', 'H1', 'D1']:
            raise SkillExecutionError(f"Invalid timeframe: {self.timeframe}")
        
        return True


# Example usage
if __name__ == "__main__":
    import asyncio
    
    config = {
        'instrument': 'GOLD',
        'timeframe': 'M5',
        'buffer_size': 100
    }
    
    skill = MarketDataSkill(config)
    
    async def test():
        # Test 1: Add M5 candle
        context = Context(current_candle={
            'timestamp': '2024-01-15T10:00:00',
            'open': 2650.0,
            'high': 2652.0,
            'low': 2649.0,
            'close': 2651.0,
            'volume': 1000
        })
        
        context = await skill.execute(context)
        print(f"History length: {len(context.candle_history)}")
        
        # Test 2: Add duplicate (should be skipped)
        context2 = Context(current_candle={
            'timestamp': '2024-01-15T10:00:00',
            'open': 2650.0,
            'high': 2652.0,
            'low': 2649.0,
            'close': 2651.0,
            'volume': 1000
        })
        
        context2 = await skill.execute(context2)
        print(f"History length after duplicate: {len(context2.candle_history)}")
    
    asyncio.run(test())

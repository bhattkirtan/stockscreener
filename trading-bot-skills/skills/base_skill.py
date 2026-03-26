"""
Base Skill Interface
All skills must implement this abstract base class to ensure consistent interface.

EVENT-DRIVEN ARCHITECTURE:
Skills now subscribe to events via EventBus and handle them with event handler methods.
Example:
    - Analysis skill implements: on_candle_closed(event)
    - Risk skill implements: on_signal_generated(event)  
    - Execution skill implements: on_risk_approved(event)

Skills publish events to communicate with other skills (via EventBus).
"""
from abc import ABC
from typing import Any, Dict, Optional, TYPE_CHECKING
from dataclasses import dataclass
from datetime import datetime

if TYPE_CHECKING:
    from core.event_bus import EventBus


@dataclass
class Context:
    """
    Shared data structure passed between skills.
    Each skill reads/writes to this context during execution.
    """
    # Market data
    current_candle: Optional[Dict] = None
    candle_history: list = None
    
    # Analysis
    indicators: Dict = None
    signal: Optional[str] = None  # 'BUY', 'SELL', 'EXIT', None
    signal_timestamp: Optional[datetime] = None
    
    # Risk
    position_size: float = 0.0
    is_allowed: bool = False
    risk_reason: str = ""
    
    # Execution
    order_id: Optional[str] = None
    deal_id: Optional[str] = None
    current_position: Optional[Dict] = None
    
    # Monitoring
    pnl: float = 0.0
    total_trades: int = 0
    win_rate: float = 0.0
    
    # Metadata
    timestamp: datetime = None
    errors: list = None
    
    def __post_init__(self):
        if self.candle_history is None:
            self.candle_history = []
        if self.indicators is None:
            self.indicators = {}
        if self.timestamp is None:
            self.timestamp = datetime.now()
        if self.errors is None:
            self.errors = []


class Skill(ABC):
    """
    Abstract base class for all trading bot skills.
    
    EVENT-DRIVEN PATTERN:
    Each skill subscribes to events it cares about and handles them:
    
    Example Flow:
    1. Market Data publishes CANDLE_CLOSED event
    2. Analysis skill handles it → publishes SIGNAL_GENERATED event
    3. Risk skill handles it → publishes RISK_APPROVED event
    4. Execution skill handles it → publishes ORDER_FILLED event
    
    Skills should:
    - Subscribe to events via event_bus.subscribe()
    - Implement async event handlers (e.g., on_candle_closed)
    - Publish events via event_bus.publish()
    - Be stateless where possible
    - Be testable in isolation
    - Focus on single responsibility
    """
    
    def __init__(self, config: Dict[str, Any], event_bus: Optional['EventBus'] = None):
        """
        Initialize skill with configuration and event bus.
        
        Args:
            config: Dictionary with skill-specific configuration
            event_bus: EventBus instance for pub/sub communication (optional for testing)
        """
        self.config = config
        self.event_bus = event_bus
        self.enabled = config.get('enabled', True)
        self.name = self.__class__.__name__
    
    # DEPRECATED: execute() method removed in favor of event handlers
    # Skills now implement event-specific handlers like:
    # - async def on_candle_closed(self, event: Event)
    # - async def on_signal_generated(self, event: Event)
    # - async def on_risk_approved(self, event: Event)
    
    def validate_config(self) -> bool:
        """
        Validate that required configuration is present.
        Override in subclass to check skill-specific config.
        
        Returns:
            True if config is valid, False otherwise
        """
        return True
    
    def on_error(self, context: Context, error: Exception):
        """
        Error handler called when execute() raises an exception.
        Override to implement custom error handling.
        
        Args:
            context: Current context
            error: Exception that was raised
        """
        context.errors.append({
            'skill': self.name,
            'error': str(error),
            'timestamp': datetime.now()
        })
    
    def __repr__(self):
        return f"<{self.name} enabled={self.enabled}>"


class SkillExecutionError(Exception):
    """Custom exception for skill execution failures"""
    pass


class SkillConfigError(Exception):
    """Custom exception for skill configuration errors"""
    pass

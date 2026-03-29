"""
Position Manager - Common Logic for Trailing Stop Loss

Provides reusable trailing stop loss logic that works for both:
1. Backtesting (calculate new SL, return value)
2. Live trading (calculate new SL, update via API)

Configuration Options:
- Config 1: Break-even after Z pips profit
- Config 2: Step-based trailing (move X pips after every Y pips profit)
"""

from dataclasses import dataclass
from typing import Optional, Tuple
import logging

logger = logging.getLogger(__name__)


@dataclass
class TrailingStopConfig:
    """Configuration for trailing stop loss strategies"""
    
    # Config 1: Break-even
    breakeven_enabled: bool = False
    breakeven_trigger_pips: float = 0.0  # Move to breakeven after Z pips profit
    
    # Config 2: Step-based trailing
    step_trailing_enabled: bool = False
    trail_step_pips: float = 0.0  # Trigger level: trail after every Y pips
    trail_move_pips: float = 0.0  # Move amount: move SL by X pips each time
    
    def is_enabled(self) -> bool:
        """Check if any trailing strategy is enabled"""
        return self.breakeven_enabled or self.step_trailing_enabled
    
    def validate(self):
        """Validate configuration"""
        if self.breakeven_enabled and self.breakeven_trigger_pips <= 0:
            raise ValueError("breakeven_trigger_pips must be > 0 when break-even is enabled")
        
        if self.step_trailing_enabled:
            if self.trail_step_pips <= 0 or self.trail_move_pips <= 0:
                raise ValueError("trail_step_pips and trail_move_pips must be > 0 when step trailing is enabled")


@dataclass
class PositionTracker:
    """Track position state for trailing stop calculations"""
    
    direction: str  # 'BUY' or 'SELL'
    entry_price: float
    current_sl: float
    current_tp: float
    
    # Tracking state
    highest_price_reached: float = 0.0  # For BUY positions
    lowest_price_reached: float = 0.0  # For SELL positions
    last_trail_level: int = 0  # Track which step level we're at (for step trailing)
    breakeven_applied: bool = False  # Track if break-even has been triggered
    
    def __post_init__(self):
        """Initialize tracking with entry price"""
        if self.direction == 'BUY':
            self.highest_price_reached = self.entry_price
            self.lowest_price_reached = 0.0
        elif self.direction == 'SELL':
            self.lowest_price_reached = self.entry_price
            self.highest_price_reached = 0.0
        else:
            raise ValueError(f"Invalid direction: {self.direction}. Must be 'BUY' or 'SELL'")


class PositionManager:
    """
    Common position management logic for trailing stop loss.
    
    This class is framework-agnostic and can be used by:
    - Backtesting engine (calculate new SL, apply to simulation)
    - Live trading bot (calculate new SL, send API update)
    
    Example Usage:
        >>> config = TrailingStopConfig(
        ...     breakeven_enabled=True,
        ...     breakeven_trigger_pips=20.0,
        ...     step_trailing_enabled=True,
        ...     trail_step_pips=10.0,
        ...     trail_move_pips=5.0
        ... )
        >>> tracker = PositionTracker(
        ...     direction='BUY',
        ...     entry_price=4500.0,
        ...     current_sl=4480.0,
        ...     current_tp=4540.0
        ... )
        >>> manager = PositionManager(config)
        >>> 
        >>> # Update with new price
        >>> new_sl, updated = manager.calculate_trailing_stop(tracker, current_price=4525.0)
        >>> if updated:
        ...     print(f"Move SL to {new_sl}")
    """
    
    def __init__(self, config: TrailingStopConfig):
        """
        Initialize position manager with trailing stop configuration.
        
        Args:
            config: TrailingStopConfig with break-even and step trailing settings
        """
        config.validate()
        self.config = config
        logger.debug(f"🔧 PositionManager initialized: "
                    f"breakeven={'ON' if config.breakeven_enabled else 'OFF'} "
                    f"step_trailing={'ON' if config.step_trailing_enabled else 'OFF'}")
    
    def calculate_trailing_stop(
        self, 
        tracker: PositionTracker, 
        current_price: float
    ) -> Tuple[Optional[float], bool]:
        """
        Calculate new stop loss based on current price and position state.
        
        This method:
        1. Updates the tracker's highest/lowest price reached
        2. Calculates current profit in pips
        3. Checks if break-even should be applied
        4. Checks if step-based trailing should be applied
        5. Returns the most aggressive (protective) new SL
        
        Args:
            tracker: PositionTracker with current position state
            current_price: Current market price
            
        Returns:
            Tuple of (new_sl, should_update):
                - new_sl: New stop loss price (or None if no update)
                - should_update: True if SL should be updated
        """
        if not self.config.is_enabled():
            return None, False
        
        # Update price extremes
        if tracker.direction == 'BUY':
            tracker.highest_price_reached = max(tracker.highest_price_reached, current_price)
            profit_pips = tracker.highest_price_reached - tracker.entry_price
        else:  # SELL
            tracker.lowest_price_reached = min(tracker.lowest_price_reached, current_price)
            profit_pips = tracker.entry_price - tracker.lowest_price_reached
        
        # Only trail when in profit
        if profit_pips <= 0:
            return None, False
        
        # Calculate candidate SL values
        new_sl_candidates = []
        
        # Config 1: Break-even SL
        if self.config.breakeven_enabled and not tracker.breakeven_applied:
            breakeven_sl = self._calculate_breakeven_sl(tracker, profit_pips)
            if breakeven_sl is not None:
                new_sl_candidates.append(('BREAKEVEN', breakeven_sl))
                tracker.breakeven_applied = True
                logger.info(f"🎯 Break-even triggered: {tracker.direction} position moved SL to {breakeven_sl:.2f} "
                           f"(entry: {tracker.entry_price:.2f}, profit: {profit_pips:.2f} pips)")
        
        # Config 2: Step-based trailing SL
        if self.config.step_trailing_enabled:
            step_sl = self._calculate_step_trailing_sl(tracker, profit_pips)
            if step_sl is not None:
                new_sl_candidates.append(('STEP_TRAIL', step_sl))
        
        if not new_sl_candidates:
            return None, False
        
        # Select the most aggressive (protective) SL
        if tracker.direction == 'BUY':
            # For BUY: higher SL is more protective
            best_strategy, best_sl = max(new_sl_candidates, key=lambda x: x[1])
            should_update = best_sl > tracker.current_sl
        else:  # SELL
            # For SELL: lower SL is more protective
            best_strategy, best_sl = min(new_sl_candidates, key=lambda x: x[1])
            should_update = best_sl < tracker.current_sl
        
        if should_update:
            logger.debug(f"🔄 {best_strategy}: New SL {best_sl:.2f} (current: {tracker.current_sl:.2f}) "
                        f"for {tracker.direction} position at {tracker.entry_price:.2f}")
            return best_sl, True
        
        return None, False
    
    def _calculate_breakeven_sl(
        self, 
        tracker: PositionTracker, 
        profit_pips: float
    ) -> Optional[float]:
        """
        Calculate break-even stop loss.
        
        Move SL to entry price when profit reaches trigger threshold.
        
        Args:
            tracker: PositionTracker with position state
            profit_pips: Current profit in pips
            
        Returns:
            New SL price at entry (break-even), or None if threshold not reached
        """
        if profit_pips >= self.config.breakeven_trigger_pips:
            # Move SL to entry price (break-even)
            return tracker.entry_price
        
        return None
    
    def _calculate_step_trailing_sl(
        self, 
        tracker: PositionTracker, 
        profit_pips: float
    ) -> Optional[float]:
        """
        Calculate step-based trailing stop loss.
        
        Every Y pips of profit, move SL by X pips in favorable direction.
        
        Example:
            - trail_step_pips = 10 (trigger every 10 pips profit)
            - trail_move_pips = 5 (move SL by 5 pips each time)
            - Entry: 4500, SL: 4480
            - Price reaches 4510 (10 pips profit) → Move SL to 4485 (4480 + 5)
            - Price reaches 4520 (20 pips profit) → Move SL to 4490 (4485 + 5)
        
        Args:
            tracker: PositionTracker with position state
            profit_pips: Current profit in pips
            
        Returns:
            New SL price, or None if no update needed
        """
        # Calculate which level we should be at
        current_level = int(profit_pips / self.config.trail_step_pips)
        
        if current_level > tracker.last_trail_level:
            # We've crossed into a new level(s)
            levels_gained = current_level - tracker.last_trail_level
            tracker.last_trail_level = current_level
            
            # Move SL by X pips for each level gained
            total_move = levels_gained * self.config.trail_move_pips
            
            if tracker.direction == 'BUY':
                new_sl = tracker.current_sl + total_move
            else:  # SELL
                new_sl = tracker.current_sl - total_move
            
            logger.info(f"📈 Step trailing: Level {current_level} reached "
                       f"(profit: {profit_pips:.2f} pips) → Move SL by {total_move:.2f} pips")
            
            return new_sl
        
        return None
    
    def should_close_position(
        self, 
        tracker: PositionTracker, 
        current_price: float
    ) -> Tuple[bool, Optional[str]]:
        """
        Check if position should be closed (SL or TP hit).
        
        This is a helper method for backtesting and monitoring.
        In live trading, Capital.com handles automatic SL/TP execution.
        
        Args:
            tracker: PositionTracker with position state
            current_price: Current market price
            
        Returns:
            Tuple of (should_close, reason):
                - should_close: True if position should close
                - reason: 'SL_HIT', 'TP_HIT', or None
        """
        if tracker.direction == 'BUY':
            if current_price <= tracker.current_sl:
                return True, 'SL_HIT'
            elif tracker.current_tp and current_price >= tracker.current_tp:
                return True, 'TP_HIT'
        else:  # SELL
            if current_price >= tracker.current_sl:
                return True, 'SL_HIT'
            elif tracker.current_tp and current_price <= tracker.current_tp:
                return True, 'TP_HIT'
        
        return False, None

"""
Order Management System for Trailing Stops
Supports multiple trailing strategies:
1. Breakeven: Move SL to entry after profit threshold
2. Progressive: Step-based trailing (every X profit, move SL by Y)
3. ATR-Based: Trail by volatility-adjusted distance
"""

import logging
import time
from typing import Dict, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class TrailingStrategy(Enum):
    """Available trailing stop strategies"""
    BREAKEVEN = "breakeven"
    PROGRESSIVE = "progressive"
    ATR_BASED = "atr_based"
    ALL = "all"  # Apply all strategies (uses most aggressive)


@dataclass
class TrailingConfig:
    """Configuration for trailing stop strategies"""
    # Breakeven settings
    breakeven_trigger_points: float = 10.0  # Profit points to trigger breakeven
    breakeven_buffer: float = 2.0  # Points above entry to set breakeven SL
    
    # Progressive trailing settings
    progressive_step: float = 5.0  # Profit increment to trail
    progressive_trail_by: float = 3.0  # Points to move SL per step
    
    # ATR-based trailing settings
    atr_trailing_multiplier: float = 1.0  # Trail by X × ATR
    
    # General settings
    enabled_strategies: list = None  # Which strategies to use
    min_update_points: float = 1.0  # Minimum SL movement to trigger update
    min_update_interval_seconds: float = 5.0  # Minimum time between API calls
    price_decimals: int = 2  # Decimal places for price rounding (2 for Gold)
    
    def __post_init__(self):
        if self.enabled_strategies is None:
            self.enabled_strategies = [TrailingStrategy.ALL]


@dataclass
class PositionState:
    """Track position state for trailing logic"""
    deal_id: str
    direction: str  # "BUY" or "SELL"
    entry_price: float
    current_sl: float
    current_tp: float
    size: float
    epic: str = ""  # Track which epic this position belongs to (for multi-epic support)
    highest_profit_points: float = 0.0  # Track highest profit reached
    last_progressive_level: int = 0  # Track progressive trailing level
    breakeven_triggered: bool = False
    last_update_time: float = field(default_factory=time.time)  # Rate limiting


class OrderManager:
    """Manage open positions with trailing stop strategies"""
    
    def __init__(self, config: TrailingConfig, capital_rest_client):
        """
        Initialize order manager
        
        Args:
            config: Trailing stop configuration
            capital_rest_client: Capital.com REST API client
        """
        self.config = config
        self.capital = capital_rest_client
        self.positions: Dict[str, PositionState] = {}
        
        logger.info(f"📊 Order Manager initialized with strategies: {[s.value for s in config.enabled_strategies]}")
    
    def register_position(self, deal_id: str, direction: str, entry_price: float,
                         stop_loss: float, take_profit: float, size: float, epic: str = ""):
        """
        Register a new position for management
        
        Args:
            deal_id: Deal ID from Capital.com
            direction: "BUY" or "SELL"
            entry_price: Entry price
            stop_loss: Initial stop loss
            take_profit: Take profit
            size: Position size
            epic: Epic identifier (e.g., "GOLD") for multi-epic support
        """
        self.positions[deal_id] = PositionState(
            deal_id=deal_id,
            direction=direction,
            entry_price=entry_price,
            current_sl=stop_loss,
            current_tp=take_profit,
            size=size,
            epic=epic
        )
        logger.info(f"📝 Registered position {deal_id}: {direction} @ {entry_price}, SL={stop_loss}, TP={take_profit} ({epic})")
    
    def unregister_position(self, deal_id: str):
        """Remove position from management (closed)"""
        if deal_id in self.positions:
            del self.positions[deal_id]
            logger.info(f"🗑️ Unregistered position {deal_id}")
    
    def update_trailing_stops(self, current_price: float, current_atr: float) -> int:
        """
        Update trailing stops for all open positions
        
        Args:
            current_price: Current market price
            current_atr: Current ATR value
            
        Returns:
            Number of positions with SL updated
        """
        if not self.positions:
            return 0
        
        updates = 0
        current_time = time.time()
        
        for deal_id, pos in list(self.positions.items()):
            # Rate limiting: Skip if updated too recently
            time_since_update = current_time - pos.last_update_time
            if time_since_update < self.config.min_update_interval_seconds:
                continue
            
            new_sl = self._calculate_new_sl(pos, current_price, current_atr)
            
            if new_sl is not None:
                # Round to proper decimal places (2 for Gold)
                new_sl = round(new_sl, self.config.price_decimals)
                
                # Check if update is significant enough
                sl_change = abs(new_sl - pos.current_sl)
                if sl_change >= self.config.min_update_points:
                    success = self._update_stop_loss(deal_id, new_sl)
                    if success:
                        old_sl = pos.current_sl
                        pos.current_sl = new_sl
                        pos.last_update_time = current_time
                        updates += 1
                        logger.info(f"✅ Updated {deal_id} SL: {old_sl:.2f} → {new_sl:.2f} (moved {sl_change:.2f} points)")
        
        return updates
    
    def _calculate_new_sl(self, pos: PositionState, current_price: float, 
                         current_atr: float) -> Optional[float]:
        """
        Calculate new stop loss based on enabled strategies
        
        Args:
            pos: Position state
            current_price: Current market price
            current_atr: Current ATR value
            
        Returns:
            New stop loss price, or None if no update needed
        """
        # Calculate current profit in points
        if pos.direction == "BUY":
            profit_points = current_price - pos.entry_price
        else:  # SELL
            profit_points = pos.entry_price - current_price
        
        # Update highest profit reached
        if profit_points > pos.highest_profit_points:
            pos.highest_profit_points = profit_points
        
        # If losing, don't trail
        if profit_points <= 0:
            return None
        
        # Calculate SL for each enabled strategy
        candidate_sls = []
        
        # Strategy 1: Breakeven
        if self._is_strategy_enabled(TrailingStrategy.BREAKEVEN):
            breakeven_sl = self._calculate_breakeven_sl(pos, profit_points)
            if breakeven_sl is not None:
                candidate_sls.append(("breakeven", breakeven_sl))
        
        # Strategy 2: Progressive Trailing
        if self._is_strategy_enabled(TrailingStrategy.PROGRESSIVE):
            progressive_sl = self._calculate_progressive_sl(pos, profit_points)
            if progressive_sl is not None:
                candidate_sls.append(("progressive", progressive_sl))
        
        # Strategy 3: ATR-Based Trailing
        if self._is_strategy_enabled(TrailingStrategy.ATR_BASED):
            atr_sl = self._calculate_atr_sl(pos, current_price, current_atr)
            if atr_sl is not None:
                candidate_sls.append(("atr", atr_sl))
        
        if not candidate_sls:
            return None
        
        # Use the most aggressive (highest for BUY, lowest for SELL) stop loss
        if pos.direction == "BUY":
            best_strategy, best_sl = max(candidate_sls, key=lambda x: x[1])
            # Only update if new SL is higher than current
            if best_sl > pos.current_sl:
                logger.debug(f"🔄 {pos.deal_id}: Using {best_strategy} trail → {best_sl:.2f}")
                return best_sl
        else:  # SELL
            best_strategy, best_sl = min(candidate_sls, key=lambda x: x[1])
            # Only update if new SL is lower than current
            if best_sl < pos.current_sl:
                logger.debug(f"🔄 {pos.deal_id}: Using {best_strategy} trail → {best_sl:.2f}")
                return best_sl
        
        return None
    
    def _calculate_breakeven_sl(self, pos: PositionState, profit_points: float) -> Optional[float]:
        """Calculate breakeven stop loss"""
        if pos.breakeven_triggered:
            return None  # Already at breakeven
        
        if profit_points >= self.config.breakeven_trigger_points:
            pos.breakeven_triggered = True
            if pos.direction == "BUY":
                new_sl = pos.entry_price + self.config.breakeven_buffer
            else:  # SELL
                new_sl = pos.entry_price - self.config.breakeven_buffer
            
            logger.info(f"🎯 {pos.deal_id}: BREAKEVEN triggered at +{profit_points:.2f} profit")
            return new_sl
        
        return None
    
    def _calculate_progressive_sl(self, pos: PositionState, profit_points: float) -> Optional[float]:
        """Calculate progressive trailing stop loss"""
        # Calculate current trailing level
        current_level = int(profit_points / self.config.progressive_step)
        
        if current_level > pos.last_progressive_level:
            # Move up to new level
            levels_gained = current_level - pos.last_progressive_level
            pos.last_progressive_level = current_level
            
            trail_amount = levels_gained * self.config.progressive_trail_by
            
            if pos.direction == "BUY":
                new_sl = pos.current_sl + trail_amount
            else:  # SELL
                new_sl = pos.current_sl - trail_amount
            
            logger.info(f"📈 {pos.deal_id}: PROGRESSIVE trail to level {current_level} (+{trail_amount:.2f} points)")
            return new_sl
        
        return None
    
    def _calculate_atr_sl(self, pos: PositionState, current_price: float, 
                         current_atr: float) -> Optional[float]:
        """Calculate ATR-based trailing stop loss"""
        trail_distance = current_atr * self.config.atr_trailing_multiplier
        
        if pos.direction == "BUY":
            new_sl = current_price - trail_distance
        else:  # SELL
            new_sl = current_price + trail_distance
        
        return new_sl
    
    def _is_strategy_enabled(self, strategy: TrailingStrategy) -> bool:
        """Check if a strategy is enabled"""
        return (TrailingStrategy.ALL in self.config.enabled_strategies or 
                strategy in self.config.enabled_strategies)
    
    def _update_stop_loss(self, deal_id: str, new_sl: float) -> bool:
        """
        Update stop loss via Capital.com API
        
        Args:
            deal_id: Deal ID
            new_sl: New stop loss price
            
        Returns:
            True if successful
        """
        try:
            # Capital.com REST API call to update position (stop_level parameter)
            result = self.capital.update_position(deal_id, stop_level=new_sl)
            return True
        except Exception as e:
            logger.error(f"❌ Failed to update SL for {deal_id}: {e}")
            return False
    
    def get_position_summary(self) -> Dict:
        """Get summary of all managed positions"""
        return {
            "total_positions": len(self.positions),
            "positions": [
                {
                    "deal_id": pos.deal_id,
                    "direction": pos.direction,
                    "entry": pos.entry_price,
                    "current_sl": pos.current_sl,
                    "highest_profit": pos.highest_profit_points,
                    "breakeven_triggered": pos.breakeven_triggered,
                    "progressive_level": pos.last_progressive_level
                }
                for pos in self.positions.values()
            ]
        }

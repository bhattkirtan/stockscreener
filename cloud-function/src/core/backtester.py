"""
⚠️  SIMULATION ONLY - NO REAL ORDERS ⚠️

Tick-level backtester for trading strategies
Uses 1-minute data as tick-level for accurate SL/TP execution
Capital.com API limitation: 1-minute is the finest resolution available

🔒 SAFETY GUARANTEE:
   - Pure in-memory simulation
   - Does NOT connect to Capital.com API
   - Does NOT place real trades
   - All trades are simulated using historical data
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)

# Import event blocking components (optional - only if configured)
try:
    from .event_blocker import EventBlocker
    from ..data.trading_economics_adapter import TradingEconomicsAdapter
except ImportError:
    EventBlocker = None
    TradingEconomicsAdapter = None
    logger.debug("Event blocking components not available")


class NoEntryBeforeEOD:
    """Blocks new entries X hours before EOD close."""
    
    def __init__(self, no_entry_hours_before_eod: int = 1, eod_hour: int = 16, enabled: bool = True):
        self.no_entry_hours_before_eod = no_entry_hours_before_eod
        self.eod_hour = eod_hour
        self.blackout_start_hour = eod_hour - no_entry_hours_before_eod
        self.enabled = enabled
    
    def can_enter_trade(self, current_time):
        """Returns False if in blackout window before EOD."""
        if not self.enabled:
            return True  # Always allow entry if disabled
        current_hour = current_time.hour + current_time.minute / 60.0
        return current_hour < self.blackout_start_hour


class FridayFilter:
    """Blocks new entries on Friday after specified hour (e.g., 3 PM / 15:00)."""
    
    def __init__(self, friday_cutoff_hour: int = 15, enabled: bool = False):
        """
        Args:
            friday_cutoff_hour: Hour (0-23) after which no entries on Friday (default: 15 = 3 PM)
            enabled: Whether filter is active
        """
        self.friday_cutoff_hour = friday_cutoff_hour
        self.enabled = enabled
    
    def can_enter_trade(self, current_time):
        """Returns False if it's Friday after cutoff hour."""
        if not self.enabled:
            return True  # Always allow if disabled
        
        # Check if it's Friday (weekday 4 = Friday in Python)
        if current_time.weekday() == 4:
            # Block entries on/after cutoff hour
            if current_time.hour >= self.friday_cutoff_hour:
                return False
        
        return True


class IntraDayTimeExit:
    """Force close positions that exceed max holding time."""
    
    def __init__(self, max_hours: int = 4, enabled: bool = True):
        self.max_hours = max_hours
        self.enabled = enabled
    
    def check_time_exit(self, entry_time, current_time):
        """Returns True if position should be closed due to time."""
        if not self.enabled:
            return False
        hours_open = (current_time - entry_time).total_seconds() / 3600
        return hours_open >= self.max_hours


class EndOfDayClose:
    """Force close all positions at eod_close_hour."""
    
    def __init__(self, close_hour: int = 16, enabled: bool = True):
        self.close_hour = close_hour
        self.enabled = enabled
    
    def should_close_eod(self, current_time):
        """Returns True if we've hit EOD close hour."""
        if not self.enabled:
            return False
        return current_time.hour >= self.close_hour


class PartialExit:
    """Exit positions gradually at multiple TP levels."""
    
    def __init__(self, enabled: bool = True,
                 tp1_pips: float = 10, tp1_percentage: float = 0.5,
                 tp2_pips: float = 20, tp2_percentage: float = 0.5):
        self.enabled = enabled
        self.tp1_pips = tp1_pips
        self.tp1_percentage = tp1_percentage
        self.tp2_pips = tp2_pips
        self.tp2_percentage = tp2_percentage
        self.tp1_hit = False
    
    def reset(self):
        """Reset state for new trade."""
        self.tp1_hit = False
    
    def check_partial_exit(self, entry_price, current_price, direction, position_size):
        """Check if we should partially close position.
        
        Returns:
            (exit_reason, close_size) tuple
            exit_reason: 'TP1', 'TP2', or None
            close_size: number of contracts to close
        """
        if not self.enabled:
            return None, position_size
        
        pips_moved = abs(current_price - entry_price)
        
        # Check TP1 (first partial exit)
        if not self.tp1_hit and pips_moved >= self.tp1_pips:
            close_size = position_size * self.tp1_percentage
            self.tp1_hit = True
            return 'TP1', close_size
        
        # Check TP2 (remaining position)
        if self.tp1_hit and pips_moved >= self.tp2_pips:
            remaining_size = position_size * (1 - self.tp1_percentage)
            return 'TP2', remaining_size
        
        return None, position_size


class OrderSide(Enum):
    BUY = 'BUY'
    SELL = 'SELL'


class OrderStatus(Enum):
    OPEN = 'OPEN'
    CLOSED = 'CLOSED'


@dataclass
class Trade:
    """Represents a single trade"""
    entry_time: datetime
    entry_price: float
    side: OrderSide
    size: float
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    
    # Exit information
    exit_time: Optional[datetime] = None
    exit_price: Optional[float] = None
    exit_reason: Optional[str] = None
    status: OrderStatus = OrderStatus.OPEN
    
    # P&L
    pnl: float = 0.0
    pnl_pct: float = 0.0
    
    # Costs
    spread_cost: float = 0.0
    slippage_cost: float = 0.0
    
    def calculate_pnl(self):
        """Calculate P&L for the trade"""
        if self.exit_price is None:
            return
        
        if self.side == OrderSide.BUY:
            pnl_points = self.exit_price - self.entry_price
        else:  # SELL
            pnl_points = self.entry_price - self.exit_price
        
        # Subtract costs
        total_costs = self.spread_cost + self.slippage_cost
        pnl_points -= total_costs
        
        self.pnl = pnl_points * self.size
        self.pnl_pct = (pnl_points / self.entry_price) * 100
    
    def to_dict(self):
        """Convert trade to dictionary"""
        return {
            'entry_time': self.entry_time,
            'entry_price': self.entry_price,
            'side': self.side.value,
            'size': self.size,
            'stop_loss': self.stop_loss,
            'take_profit': self.take_profit,
            'exit_time': self.exit_time,
            'exit_price': self.exit_price,
            'exit_reason': self.exit_reason,
            'status': self.status.value,
            'pnl': self.pnl,
            'pnl_pct': self.pnl_pct,
            'spread_cost': self.spread_cost,
            'slippage_cost': self.slippage_cost
        }


@dataclass
class BacktestConfig:
    """Configuration for backtesting"""
    initial_capital: float = 10000.0
    
    # Transaction costs (fixed in USD for realistic simulation)
    spread_cost_usd: float = 0.50    # Capital.com Gold spread: $0.50 per contract (real market data)
    slippage_cost_usd: float = 0.05  # Slippage per trade: $0.05 (10% of spread, conservative estimate)
    pip_value: float = 1.0           # For GOLD: 1.0 (full dollar points), Forex: 0.0001
    
    # Legacy pip-based costs (kept for backward compatibility, but not recommended)
    spread_pips: Optional[float] = None   # If set, overrides spread_cost_usd
    slippage_pips: Optional[float] = None # If set, overrides slippage_cost_usd
    
    # Position sizing
    default_position_size: float = 1.0  # 1 contract
    use_kelly_criterion: bool = False
    
    # Compounding (dynamic position sizing based on current equity)
    use_compounding: bool = False        # Enable/disable compounding
    compounding_pct: float = 0.10       # % of current equity per trade (0.10 = 10%)
    
    # Tick data settings
    use_tick_data: bool = True       # Use 1-minute data for SL/TP checks
    fallback_to_ohlc: bool = True    # If tick data unavailable, use OHLC simulation
    kelly_fraction: float = 0.25     # Use 25% of Kelly for safety
    
    # Risk management (as percentage of account)
    max_risk_per_trade: float = 0.02  # 2% risk per trade
    max_positions: int = 1            # Maximum concurrent positions
    
    # Stop loss / Take profit
    default_stop_loss_pips: Optional[float] = None
    default_take_profit_pips: Optional[float] = None
    
    # Time-based intraday parameters (ALL OPTIONAL - test with/without)
    enable_time_exit: bool = False           # Enable/disable max_holding_hours
    max_holding_hours: Optional[int] = None  # Max hours before forced exit
    
    enable_eod_close: bool = False           # Enable/disable EOD close
    eod_close_hour: int = 16                 # Hour to close all positions (4 PM)
    
    enable_eod_blackout: bool = False        # Enable/disable entry blackout
    no_entry_before_eod_hours: int = 1       # Blackout window size (hours before EOD)
    
    # Friday filter (avoid trading late Friday due to weekend risk)
    enable_friday_filter: bool = False       # Enable/disable Friday cutoff
    friday_cutoff_hour: int = 15             # No entries on Friday after this hour (default: 3 PM)
    
    # Partial exit parameters (scale out: 50% @ TP1, 50% @ TP2)
    enable_partial_exit: bool = False        # Enable/disable partial exits
    partial_exit_tp1_pips: float = 10        # First TP level (pips)
    partial_exit_tp1_pct: float = 0.5        # % to close at TP1 (0.5 = 50%)
    partial_exit_tp2_pips: float = 20        # Second TP level (pips)
    partial_exit_tp2_pct: float = 0.5        # % to close at TP2 (remaining 50%)
    
    # Event blocking (strategy.md Section 13)
    enable_event_blocking: bool = False      # Enable/disable calendar event blocking
    calendar_path: Optional[str] = None      # Path to economic calendar JSON file
    event_blocker: Optional[object] = None   # EventBlocker instance (passed from outside)
    event_pre_window_minutes: int = 15       # Block before high-impact event (15 min)
    event_post_window_minutes: int = 15      # Block after high-impact event (15 min)
    
    # Logging
    verbose: bool = True
    trade_log_file: Optional[str] = None  # Path to write per-order trace CSV (None = disabled)


class IntraCandleBacktester:
    """
    Backtester that simulates intra-candle price movement for accurate SL/TP execution
    
    DOES NOT REQUIRE TICK DATA OR 1-SECOND BARS!
    Uses high/low of strategy timeframe candles to simulate realistic price paths.
    
    Why we don't use 1-second data:
    - Capital.com API limit: 1000 bars = only 16 minutes of 1-second data
    - To backtest 1 day would need ~5400 API calls FOR EACH DAY
    - Impractical and would hit rate limits quickly
    
    How intra-candle simulation works:
    - Each candle has: open, high, low, close
    - We simulate path: open -> low/high -> close (depending on candle direction)
    - Check if SL or TP was hit at each point
    - Example: Candle (open=2000, high=2020, low=1990, close=2005)
      * SL=1995: HIT (low=1990 < 1995)
      * TP=2015: HIT (high=2020 > 2015)
      * But close=2005 would miss both!
    
    RECOMMENDED: Use M5/M15/H1 timeframe for strategy signals
    """
    
    def __init__(self, config: BacktestConfig = None, tick_data: Optional[pd.DataFrame] = None):
        self.config = config or BacktestConfig()
        self.tick_data = tick_data  # 1-minute data for tick-level simulation

        # Set up trade log file for per-order tracing
        self._trade_log_fh = None
        if self.config.trade_log_file:
            import csv, os
            os.makedirs(os.path.dirname(os.path.abspath(self.config.trade_log_file)), exist_ok=True)
            self._trade_log_fh = open(self.config.trade_log_file, 'w', newline='', buffering=1)
            self._trade_log_writer = csv.writer(self._trade_log_fh)
            self._trade_log_writer.writerow([
                'event', 'timestamp', 'direction', 'entry_price', 'stop_loss', 'take_profit',
                'size', 'exit_price', 'exit_reason', 'pnl'
            ])
            logger.info(f"📝 Trade log file: {self.config.trade_log_file}")

        # Auto-create EventBlocker if enabled and calendar_path provided
        if self.config.enable_event_blocking and self.config.calendar_path and not self.config.event_blocker:
            try:
                from ..data.manual_calendar_adapter import ManualCalendarAdapter
                from .event_blocker import EventBlocker
                
                calendar = ManualCalendarAdapter(self.config.calendar_path)
                self.config.event_blocker = EventBlocker(
                    calendar_adapter=calendar,
                    pre_event_minutes=15,
                    post_event_minutes=15
                )
                logger.info(f"✅ Event blocker created from {self.config.calendar_path}")
            except Exception as e:
                logger.warning(f"⚠️  Failed to create event blocker: {e}")
                self.config.enable_event_blocking = False
        
        self.reset()
    
    def reset(self):
        """Reset backtest state"""
        self.capital = self.config.initial_capital
        self.equity_curve = []
        self.trades: List[Trade] = []
        self.open_positions: List[Trade] = []
        self.closed_positions: List[Trade] = []
        
        # Performance tracking
        self.total_pnl = 0.0
        self.total_trades = 0
        self.winning_trades = 0
        self.losing_trades = 0
        self.max_equity = self.config.initial_capital
        self.max_drawdown = 0.0
        self.max_drawdown_pct = 0.0
    
    def _simulate_intra_candle_price_path(self, open_price: float, high: float, low: float, close: float) -> List[float]:
        """
        Simulate realistic price path within a candle (fallback when tick data unavailable)
        
        We don't have tick data, but we can make reasonable assumptions:
        1. Price moved from open to high and/or low
        2. Final move was to close
        
        NOTE: This is less accurate than using 1-minute tick data.
        Use tick_data parameter in run() for better accuracy.
        
        Returns:
            List of price points representing the path
        """
        # Determine which extreme was hit first
        # If close > open (bullish candle), likely hit low first then high
        # If close < open (bearish candle), likely hit high first then low
        
        if close >= open_price:
            # Bullish candle: open -> low -> high -> close
            path = [open_price, low, high, close]
        else:
            # Bearish candle: open -> high -> low -> close
            path = [open_price, high, low, close]
        
        return path
    
    def _get_tick_data_for_candle(self, candle_start: datetime, candle_end: datetime) -> Optional[pd.DataFrame]:
        """
        Get 1-minute tick data for a specific candle period
        
        Args:
            candle_start: Start time of the candle
            candle_end: End time of the candle
            
        Returns:
            DataFrame with 1-minute ticks, or None if unavailable
        """
        if self.tick_data is None or self.tick_data.empty:
            return None
        
        # Filter tick data for this candle period
        # Support both DatetimeIndex and a 'timestamp' column
        if isinstance(self.tick_data.index, pd.DatetimeIndex):
            mask = (self.tick_data.index >= candle_start) & (self.tick_data.index < candle_end)
        else:
            mask = (self.tick_data['timestamp'] >= candle_start) & (self.tick_data['timestamp'] < candle_end)
        ticks = self.tick_data[mask].copy()
        
        if ticks.empty:
            return None
        
        return ticks
    
    def _check_exit_within_candle(
        self, 
        trade: Trade, 
        candle_open: float,
        candle_high: float, 
        candle_low: float, 
        candle_close: float,
        timestamp: datetime,
        candle_start: Optional[datetime] = None,
        candle_end: Optional[datetime] = None
    ) -> Tuple[bool, Optional[float], Optional[str]]:
        """
        Check if trade should be exited within this candle
        
        Uses 1-minute tick data if available for accurate SL/TP execution.
        Falls back to OHLC simulation if tick data is unavailable.
        
        Returns:
            (should_exit, exit_price, exit_reason)
        """
        # Try to use 1-minute tick data first
        if self.config.use_tick_data and candle_start and candle_end:
            ticks = self._get_tick_data_for_candle(candle_start, candle_end)
            
            if ticks is not None and not ticks.empty:
                # Use actual 1-minute price movements
                for idx, tick in ticks.iterrows():
                    tick_high = tick['high']
                    tick_low = tick['low']
                    tick_ts = idx  # timestamp is the DatetimeIndex
                    
                    # Check stop loss
                    if trade.stop_loss is not None:
                        if trade.side == OrderSide.BUY and tick_low <= trade.stop_loss:
                            if self.config.verbose:
                                logger.debug(f"   Stop Loss hit at {tick_ts}: {trade.stop_loss:.2f}")
                            return True, trade.stop_loss, 'Stop Loss'
                        elif trade.side == OrderSide.SELL and tick_high >= trade.stop_loss:
                            if self.config.verbose:
                                logger.debug(f"   Stop Loss hit at {tick_ts}: {trade.stop_loss:.2f}")
                            return True, trade.stop_loss, 'Stop Loss'
                    
                    # Check take profit
                    if trade.take_profit is not None:
                        if trade.side == OrderSide.BUY and tick_high >= trade.take_profit:
                            if self.config.verbose:
                                logger.debug(f"   Take Profit hit at {tick_ts}: {trade.take_profit:.2f}")
                            return True, trade.take_profit, 'Take Profit'
                        elif trade.side == OrderSide.SELL and tick_low <= trade.take_profit:
                            if self.config.verbose:
                                logger.debug(f"   Take Profit hit at {tick_ts}: {trade.take_profit:.2f}")
                            return True, trade.take_profit, 'Take Profit'
                
                # No exit triggered in tick data
                return False, None, None
        
        # Fallback to OHLC simulation
        if self.config.fallback_to_ohlc:
            if self.config.verbose:
                logger.debug(f"   Using OHLC simulation (tick data unavailable)")
            price_path = self._simulate_intra_candle_price_path(candle_open, candle_high, candle_low, candle_close)
            
            # Check each point in the path
            for price in price_path:
                # Check stop loss
                if trade.stop_loss is not None:
                    if trade.side == OrderSide.BUY and price <= trade.stop_loss:
                        return True, trade.stop_loss, 'Stop Loss'
                    elif trade.side == OrderSide.SELL and price >= trade.stop_loss:
                        return True, trade.stop_loss, 'Stop Loss'
                
                # Check take profit
                if trade.take_profit is not None:
                    if trade.side == OrderSide.BUY and price >= trade.take_profit:
                        return True, trade.take_profit, 'Take Profit'
                    elif trade.side == OrderSide.SELL and price <= trade.take_profit:
                        return True, trade.take_profit, 'Take Profit'
        
        # No exit triggered within candle
        return False, None, None
    
    def _calculate_position_size(self, price: float, stop_loss: Optional[float] = None) -> float:
        """
        Calculate position size based on risk management rules
        
        Args:
            price: Entry price
            stop_loss: Stop loss price (if None, uses default size)
            
        Returns:
            Position size
        """
        # Compounding: position size scales with current equity
        if self.config.use_compounding:
            # Calculate how many contracts we can trade with X% of current capital
            # Example: $15,000 equity * 10% = $1,500 → 1.5 contracts at $1000/contract
            available_capital = self.capital * self.config.compounding_pct
            
            # For Gold: assuming ~$2500/oz, 1 contract ≈ $2500 notional
            # So position_size = available_capital / current_price
            position_size = available_capital / price
            
            # Minimum 0.1 contract, maximum 10x default for safety
            position_size = max(0.1, min(position_size, self.config.default_position_size * 10))
            
            return position_size
        
        # Kelly Criterion: risk-based sizing
        if self.config.use_kelly_criterion:
            # If using Kelly and we have stop loss, calculate size based on risk
            if stop_loss is not None:
                risk_per_unit = abs(price - stop_loss)
                max_risk_amount = self.capital * self.config.max_risk_per_trade
                position_size = max_risk_amount / risk_per_unit
                
                # Cap at default size for safety
                return min(position_size, self.config.default_position_size * 2)
        
        # Default: fixed position size
        return self.config.default_position_size
    
    def _calculate_costs(self, price: float) -> Tuple[float, float]:
        """
        Calculate spread and slippage costs
        
        Returns:
            (spread_cost, slippage_cost) in price units
        """
        # Use fixed USD costs (recommended) or legacy pip-based calculation
        if self.config.spread_pips is not None:
            # Legacy mode: scale with pip_value (can cause issues with large pip_value)
            spread_cost = self.config.spread_pips * self.config.pip_value
        else:
            # Fixed USD mode: transaction costs don't scale with pip_value
            spread_cost = self.config.spread_cost_usd
            
        if self.config.slippage_pips is not None:
            slippage_cost = self.config.slippage_pips * self.config.pip_value
        else:
            slippage_cost = self.config.slippage_cost_usd
            
        return spread_cost, slippage_cost
    
    def open_position(
        self, 
        timestamp: datetime,
        price: float,
        side: OrderSide,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        size: Optional[float] = None
    ) -> Optional[Trade]:
        """
        Open a new position
        
        Returns:
            Trade object if opened, None if rejected
        """
        # Check if we can open more positions — hard enforcement, never allow > max
        if len(self.open_positions) >= self.config.max_positions:
            raise RuntimeError(
                f"Attempted to open a new position while {len(self.open_positions)} "
                f"position(s) already open (max_positions={self.config.max_positions}). "
                f"Close the existing trade before opening a new one."
            )
        
        # Calculate position size
        if size is None:
            size = self._calculate_position_size(price, stop_loss)
        
        # Calculate costs
        spread_cost, slippage_cost = self._calculate_costs(price)
        
        # Adjust entry price for slippage
        if side == OrderSide.BUY:
            adjusted_price = price + slippage_cost
        else:
            adjusted_price = price - slippage_cost
        
        # Enforce stop loss — fall back to default_stop_loss_pips if not provided
        if stop_loss is None and self.config.default_stop_loss_pips is not None:
            sl_distance = self.config.default_stop_loss_pips * self.config.pip_value
            if side == OrderSide.BUY:
                stop_loss = adjusted_price - sl_distance
            else:
                stop_loss = adjusted_price + sl_distance
            logger.debug(f"⚠️  No SL provided — applied default {self.config.default_stop_loss_pips} pips → {stop_loss:.2f}")
        elif stop_loss is None:
            logger.warning(f"⚠️  ORDER OPENED WITHOUT STOP LOSS at {timestamp} {side.value} @ {adjusted_price:.2f}  — SL is None, risk is unlimited")

        # Create trade
        trade = Trade(
            entry_time=timestamp,
            entry_price=adjusted_price,
            side=side,
            size=size,
            stop_loss=stop_loss,
            take_profit=take_profit,
            spread_cost=spread_cost,
            slippage_cost=slippage_cost
        )

        self.open_positions.append(trade)
        self.trades.append(trade)
        assert len(self.open_positions) <= self.config.max_positions, \
            f"BUG: {len(self.open_positions)} open positions exceed max_positions={self.config.max_positions}"

        if self.config.verbose:
            logger.info(f"📊 Opened {side.value} position: {size} @ {adjusted_price:.2f} (SL: {stop_loss}, TP: {take_profit})")

        # Write to trade log file for tracing
        if self._trade_log_fh is not None:
            self._trade_log_writer.writerow([
                'OPEN', timestamp, side.value, f"{adjusted_price:.5f}",
                f"{stop_loss:.5f}" if stop_loss is not None else 'NONE',
                f"{take_profit:.5f}" if take_profit is not None else 'NONE',
                size, '', '', ''
            ])

        return trade
    
    def close_position(
        self,
        trade: Trade,
        timestamp: datetime,
        price: float,
        reason: str = 'Manual Close'
    ):
        """Close an open position"""
        if trade.status == OrderStatus.CLOSED:
            logger.warning(f"Trade already closed")
            return
        
        # SL/TP exits fill at the exact trigger level — price is already the live SL/TP price.
        # Slippage only applies to discretionary market closes (EOD, reverse signal, end of backtest).
        market_close_reasons = {'End of Backtest', 'EOD_CLOSE', 'TIME_EXIT', 'Reverse Signal', 'Manual Close'}
        if reason in market_close_reasons:
            _, slippage_cost = self._calculate_costs(price)
            adjusted_price = price - slippage_cost if trade.side == OrderSide.BUY else price + slippage_cost
        else:
            adjusted_price = price  # SL / TP: fill at the exact level
        
        # Update trade
        trade.exit_time = timestamp
        trade.exit_price = adjusted_price
        trade.exit_reason = reason
        trade.status = OrderStatus.CLOSED
        trade.calculate_pnl()
        
        # Update capital
        self.capital += trade.pnl
        self.total_pnl += trade.pnl
        
        # Track win/loss
        if trade.pnl > 0:
            self.winning_trades += 1
        elif trade.pnl < 0:
            self.losing_trades += 1
        
        self.total_trades += 1
        
        # Move to closed positions
        self.open_positions.remove(trade)
        self.closed_positions.append(trade)
        
        if self.config.verbose:
            logger.info(f"💰 Closed {trade.side.value} position: P&L={trade.pnl:.2f} ({trade.pnl_pct:.2f}%) - Reason: {reason}")

        # Write to trade log file for tracing
        if self._trade_log_fh is not None:
            self._trade_log_writer.writerow([
                'CLOSE', timestamp, trade.side.value,
                f"{trade.entry_price:.5f}",
                f"{trade.stop_loss:.5f}" if trade.stop_loss is not None else 'NONE',
                f"{trade.take_profit:.5f}" if trade.take_profit is not None else 'NONE',
                trade.size, f"{adjusted_price:.5f}", reason, f"{trade.pnl:.4f}"
            ])
    
    def update_equity_curve(self, timestamp: datetime, current_prices: Dict[str, float]):
        """
        Update equity curve with current unrealized P&L
        
        Args:
            timestamp: Current timestamp
            current_prices: Dict of instrument -> current price
        """
        # Calculate unrealized P&L for open positions
        unrealized_pnl = 0.0
        for trade in self.open_positions:
            # For simplicity, assume single instrument (extend for multi-instrument)
            current_price = list(current_prices.values())[0] if current_prices else trade.entry_price
            
            if trade.side == OrderSide.BUY:
                pnl_points = current_price - trade.entry_price
            else:
                pnl_points = trade.entry_price - current_price
            
            # Subtract costs
            pnl_points -= (trade.spread_cost + trade.slippage_cost)
            unrealized_pnl += pnl_points * trade.size
        
        total_equity = self.capital + unrealized_pnl
        
        self.equity_curve.append({
            'timestamp': timestamp,
            'capital': self.capital,
            'unrealized_pnl': unrealized_pnl,
            'total_equity': total_equity,
            'open_positions': len(self.open_positions)
        })
        
        # Track max equity and drawdown
        if total_equity > self.max_equity:
            self.max_equity = total_equity
        
        drawdown = self.max_equity - total_equity
        drawdown_pct = (drawdown / self.max_equity) * 100 if self.max_equity > 0 else 0
        
        if drawdown_pct > self.max_drawdown_pct:
            self.max_drawdown = drawdown
            self.max_drawdown_pct = drawdown_pct
    
    def run(
        self, 
        df: pd.DataFrame, 
        signals: pd.DataFrame,
        tick_data: Optional[pd.DataFrame] = None,
        timeframe_minutes: int = 5
    ) -> Dict:
        """
        Run backtest on historical data with signals
        
        Args:
            df: DataFrame with OHLCV data (columns: open, high, low, close, volume)
                Index should be datetime for proper tick alignment
            signals: DataFrame with trading signals (columns: signal, stop_loss, take_profit)
                     signal: 1 (BUY), -1 (SELL), 0 (no signal)
           tick_data: Optional 1-minute DataFrame for accurate SL/TP checks
                       If None, falls back to OHLC simulation
            timeframe_minutes: Timeframe of signal data (e.g., 5 for 5-minute candles)
                     
        Returns:
            Dictionary with backtest results
        """
        self.reset()
        
        # Initialize time-based intraday classes (optional based on config)
        time_exit = IntraDayTimeExit(
            max_hours=self.config.max_holding_hours if self.config.max_holding_hours else 4,
            enabled=self.config.enable_time_exit
        )
        
        eod_close = EndOfDayClose(
            close_hour=self.config.eod_close_hour,
            enabled=self.config.enable_eod_close
        )
        
        no_entry_eod = NoEntryBeforeEOD(
            no_entry_hours_before_eod=self.config.no_entry_before_eod_hours,
            eod_hour=self.config.eod_close_hour,
            enabled=self.config.enable_eod_blackout
        )
        
        friday_filter = FridayFilter(
            friday_cutoff_hour=self.config.friday_cutoff_hour,
            enabled=self.config.enable_friday_filter
        )
        
        partial_exit = PartialExit(
            enabled=self.config.enable_partial_exit,
            tp1_pips=self.config.partial_exit_tp1_pips,
            tp1_percentage=self.config.partial_exit_tp1_pct,
            tp2_pips=self.config.partial_exit_tp2_pips,
            tp2_percentage=self.config.partial_exit_tp2_pct
        )
        
        # Event blocker (optional - from strategy.md Section 13)
        event_blocker = self.config.event_blocker if self.config.enable_event_blocking else None
        if event_blocker and self.config.enable_event_blocking:
            logger.info(f"📅 Event Blocking: Enabled (±{self.config.event_pre_window_minutes}min window)")
        else:
            logger.debug("📅 Event Blocking: Disabled")
        
        # Store tick data for this run
        if tick_data is not None:
            self.tick_data = tick_data
            logger.info(f"📊 Using 1-minute tick data: {len(tick_data)} ticks")
        else:
            self.tick_data = None
            logger.info(f"📊 No tick data provided, using OHLC simulation")
        
        # Log intraday features status
        if self.config.enable_time_exit:
            logger.info(f"⏰ Time Exit: Enabled (max {self.config.max_holding_hours}h)")
        if self.config.enable_eod_close:
            logger.info(f"🔒 EOD Close: Enabled (close by {self.config.eod_close_hour}:00)")
        if self.config.enable_eod_blackout:
            logger.info(f"🚫 Entry Blackout: Enabled ({self.config.no_entry_before_eod_hours}h before EOD)")
        if self.config.enable_partial_exit:
            logger.info(f"📊 Partial Exit: Enabled (TP1:{self.config.partial_exit_tp1_pips}p @ {self.config.partial_exit_tp1_pct*100}%, TP2:{self.config.partial_exit_tp2_pips}p)")
        
        logger.info(f"🚀 Starting tick-level backtest")
        logger.info(f"   Data: {len(df)} candles from {df.index[0]} to {df.index[-1]}")
        logger.info(f"   Timeframe: {timeframe_minutes} minutes")
        logger.info(f"   Initial capital: ${self.config.initial_capital:,.2f}")
        logger.info(f"   Spread: {self.config.spread_pips} pips, Slippage: {self.config.slippage_pips} pips")
        
        # Align data and signals
        df = df.copy()
        signals = signals.copy()
        
        if len(df) != len(signals):
            logger.warning(f"Data length mismatch: {len(df)} candles vs {len(signals)} signals")
            # Align by index
            df, signals = df.align(signals, join='inner', axis=0)
        
        # Iterate through each candle
        for i in range(len(df)):
            timestamp = df.index[i]
            candle = df.iloc[i]
            signal = signals.iloc[i]
            
            # Calculate candle period for tick data lookup
            candle_start = timestamp
            candle_end = timestamp + timedelta(minutes=timeframe_minutes)
            
            # Get signal values
            signal_value = signal.get('signal', 0)
            stop_loss = signal.get('stop_loss', None)
            take_profit = signal.get('take_profit', None)
            
            # 1. Check time-based exits FIRST (override SL/TP if needed)
            for trade in self.open_positions.copy():
                # Check: Time exit (max holding hours)
                if time_exit.check_time_exit(trade.entry_time, timestamp):
                    exit_price = candle['close']
                    self.close_position(trade, timestamp, exit_price, 'TIME_EXIT')
                    continue
                
                # Check: End of day close
                if eod_close.should_close_eod(timestamp):
                    exit_price = candle['close']
                    self.close_position(trade, timestamp, exit_price, 'EOD_CLOSE')
                    continue
            
            # 2. Check regular exits (SL/TP within candle)
            for trade in self.open_positions.copy():  # Copy to avoid modification during iteration
                should_exit, exit_price, exit_reason = self._check_exit_within_candle(
                    trade,
                    candle['open'],
                    candle['high'],
                    candle['low'],
                    candle['close'],
                    timestamp,
                    candle_start,
                    candle_end
                )
                
                if should_exit:
                    self.close_position(trade, timestamp, exit_price, exit_reason)
            
            # 3. Check for new signal (with EOD blackout check)
            #    Reverse signal: if holding a BUY and a SELL fires (or vice versa),
            #    close the existing position at the current candle open before entering.
            #    Same-direction signals while already in a trade are silently skipped
            #    (max_positions=1 guard in open_position() will raise if violated).
            if signal_value == 1:
                for trade in self.open_positions.copy():
                    if trade.side == OrderSide.SELL:
                        self.close_position(trade, timestamp, candle['open'], 'Reverse Signal')
            elif signal_value == -1:
                for trade in self.open_positions.copy():
                    if trade.side == OrderSide.BUY:
                        self.close_position(trade, timestamp, candle['open'], 'Reverse Signal')

            if signal_value == 1:  # BUY signal
                # Check EOD blackout window
                if not no_entry_eod.can_enter_trade(timestamp):
                    if self.config.verbose:
                        logger.debug(f"🚫 Skipping BUY signal at {timestamp}: In EOD blackout window")
                # Check Friday filter
                elif not friday_filter.can_enter_trade(timestamp):
                    if self.config.verbose:
                        logger.debug(f"🚫 Skipping BUY signal at {timestamp}: Friday after {self.config.friday_cutoff_hour}:00")
                # Check event blocking (if enabled)
                elif event_blocker is not None and self.config.enable_event_blocking:
                    is_allowed, block_reason = event_blocker.is_trading_allowed(timestamp)
                    if not is_allowed:
                        if self.config.verbose:
                            logger.debug(f"🚫 Skipping BUY signal at {timestamp}: {block_reason}")
                    elif len(self.open_positions) < self.config.max_positions:
                        # Reset partial exit state for new trade
                        partial_exit.reset()
                        # Enter at close price (or open of next candle in real-time)
                        self.open_position(
                            timestamp=timestamp,
                            price=candle['close'],
                            side=OrderSide.BUY,
                            stop_loss=stop_loss,
                            take_profit=take_profit
                        )
                # Only open if no positions or we allow multiple
                elif len(self.open_positions) < self.config.max_positions:
                    # Reset partial exit state for new trade
                    partial_exit.reset()
                    # Enter at close price (or open of next candle in real-time)
                    self.open_position(
                        timestamp=timestamp,
                        price=candle['close'],
                        side=OrderSide.BUY,
                        stop_loss=stop_loss,
                        take_profit=take_profit
                    )
            
            elif signal_value == -1:  # SELL signal
                # Check EOD blackout window
                if not no_entry_eod.can_enter_trade(timestamp):
                    if self.config.verbose:
                        logger.debug(f"🚫 Skipping SELL signal at {timestamp}: In EOD blackout window")
                # Check Friday filter
                elif not friday_filter.can_enter_trade(timestamp):
                    if self.config.verbose:
                        logger.debug(f"🚫 Skipping SELL signal at {timestamp}: Friday after {self.config.friday_cutoff_hour}:00")
                # Check event blocking (if enabled)
                elif event_blocker is not None and self.config.enable_event_blocking:
                    is_allowed, block_reason = event_blocker.is_trading_allowed(timestamp)
                    if not is_allowed:
                        if self.config.verbose:
                            logger.debug(f"🚫 Skipping SELL signal at {timestamp}: {block_reason}")
                    elif len(self.open_positions) < self.config.max_positions:
                        # Reset partial exit state for new trade
                        partial_exit.reset()
                        self.open_position(
                            timestamp=timestamp,
                            price=candle['close'],
                            side=OrderSide.SELL,
                            stop_loss=stop_loss,
                            take_profit=take_profit
                        )
                elif len(self.open_positions) < self.config.max_positions:
                    # Reset partial exit state for new trade
                    partial_exit.reset()
                    self.open_position(
                        timestamp=timestamp,
                        price=candle['close'],
                        side=OrderSide.SELL,
                        stop_loss=stop_loss,
                        take_profit=take_profit
                    )
            
            # 4. Update equity curve
            self.update_equity_curve(timestamp, {'instrument': candle['close']})
        
        # Close any remaining open positions at end of backtest
        final_price = df.iloc[-1]['close']
        final_timestamp = df.index[-1]
        for trade in self.open_positions.copy():
            self.close_position(trade, final_timestamp, final_price, 'End of Backtest')
        
        # Calculate final metrics
        results = self._calculate_metrics()
        
        logger.info(f"\n{'='*70}")
        logger.info(f"📊 Backtest Results")
        logger.info(f"{'='*70}")
        logger.info(f"Total Trades: {results['total_trades']}")
        logger.info(f"Win Rate: {results['win_rate']:.2f}%")
        logger.info(f"Total P&L: ${results['total_pnl']:.2f}")
        logger.info(f"Sharpe Ratio: {results['sharpe_ratio']:.2f}")
        logger.info(f"Max Drawdown: {results['max_drawdown_pct']:.2f}%")
        logger.info(f"Final Capital: ${results['final_capital']:.2f}")
        logger.info(f"{'='*70}\n")
        
        return results
    
    def _calculate_metrics(self) -> Dict:
        """Calculate performance metrics"""
        if len(self.closed_positions) == 0:
            return {
                'total_trades': 0,
                'winning_trades': 0,
                'losing_trades': 0,
                'win_rate': 0.0,
                'total_pnl': 0.0,
                'avg_win': 0.0,
                'avg_loss': 0.0,
                'profit_factor': 0.0,
                'sharpe_ratio': 0.0,
                'max_drawdown': 0.0,
                'max_drawdown_pct': 0.0,
                'final_capital': self.capital,
                'return_pct': 0.0
            }
        
        # Calculate wins and losses
        wins = [t.pnl for t in self.closed_positions if t.pnl > 0]
        losses = [t.pnl for t in self.closed_positions if t.pnl < 0]
        
        avg_win = np.mean(wins) if wins else 0
        avg_loss = np.mean(losses) if losses else 0
        
        # Profit factor
        total_wins = sum(wins) if wins else 0
        total_losses = abs(sum(losses)) if losses else 0
        profit_factor = total_wins / total_losses if total_losses > 0 else 0
        
        # Win rate
        win_rate = (len(wins) / len(self.closed_positions)) * 100 if self.closed_positions else 0
        
        # Sharpe ratio (using equity curve)
        if len(self.equity_curve) > 1:
            equity = pd.Series([e['total_equity'] for e in self.equity_curve])
            returns = equity.pct_change().dropna()
            sharpe_ratio = (returns.mean() / returns.std()) * np.sqrt(252) if returns.std() > 0 else 0
        else:
            sharpe_ratio = 0
        
        # Return percentage
        return_pct = ((self.capital - self.config.initial_capital) / self.config.initial_capital) * 100
        
        return {
            'total_trades': len(self.closed_positions),
            'winning_trades': len(wins),
            'losing_trades': len(losses),
            'win_rate': win_rate,
            'total_pnl': self.total_pnl,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'profit_factor': profit_factor,
            'sharpe_ratio': sharpe_ratio,
            'max_drawdown': self.max_drawdown,
            'max_drawdown_pct': self.max_drawdown_pct,
            'final_capital': self.capital,
            'return_pct': return_pct,
            'equity_curve': pd.DataFrame(self.equity_curve),
            'trades': [t.to_dict() for t in self.closed_positions]
        }
    
    def get_trades_df(self) -> pd.DataFrame:
        """Get all closed trades as DataFrame"""
        if not self.closed_positions:
            return pd.DataFrame()
        
        return pd.DataFrame([t.to_dict() for t in self.closed_positions])
    
    def get_equity_curve_df(self) -> pd.DataFrame:
        """Get equity curve as DataFrame"""
        if not self.equity_curve:
            return pd.DataFrame()
        
        return pd.DataFrame(self.equity_curve).set_index('timestamp')


# Backward compatibility alias (renamed from TickLevelBacktester to IntraCandleBacktester)
TickLevelBacktester = IntraCandleBacktester

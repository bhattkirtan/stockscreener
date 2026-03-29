"""
Circuit Breakers and Risk Controls
Advanced risk management beyond entry validation.
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta, time
from typing import Dict, List, Optional, Tuple
from enum import Enum


class CircuitBreakerStatus(Enum):
    """Circuit breaker states"""
    CLOSED = "CLOSED"  # Trading allowed
    OPEN = "OPEN"      # Trading blocked
    HALF_OPEN = "HALF_OPEN"  # Testing recovery


@dataclass
class LossTracker:
    """Tracks losses over time periods"""
    period_start: datetime = field(default_factory=datetime.now)
    window_hours: int = 24
    total_pnl: float = 0.0
    winning_trades: int = 0
    losing_trades: int = 0
    consecutive_losses: int = 0
    max_consecutive_losses: int = 0
    _trade_log: list = field(default_factory=list)  # [(timestamp, pnl), ...]

    def get_win_count(self) -> int:
        return self.winning_trades

    def get_loss_count(self) -> int:
        return self.losing_trades

    def get_total_pnl(self) -> float:
        """Return total P&L within the window"""
        cutoff = datetime.now() - timedelta(hours=self.window_hours)
        return sum(pnl for ts, pnl in self._trade_log if ts >= cutoff)

    def record_trade(self, pnl: float, timestamp: Optional[datetime] = None) -> None:
        """Record trade result"""
        ts = timestamp or datetime.now()
        self._trade_log.append((ts, pnl))
        self.total_pnl += pnl

        if pnl > 0:
            self.winning_trades += 1
            self.consecutive_losses = 0
        else:
            self.losing_trades += 1
            self.consecutive_losses += 1
            self.max_consecutive_losses = max(
                self.max_consecutive_losses,
                self.consecutive_losses
            )

    def get_loss(self) -> float:
        """Get sum of losses within the window (negative values only)"""
        cutoff = datetime.now() - timedelta(hours=self.window_hours)
        return sum(pnl for ts, pnl in self._trade_log if ts >= cutoff and pnl < 0)

    def reset(self) -> None:
        """Reset tracker for new period"""
        self.period_start = datetime.now()
        self.total_pnl = 0.0
        self.winning_trades = 0
        self.losing_trades = 0
        self.consecutive_losses = 0
        self._trade_log.clear()
        self.consecutive_losses = 0


class CircuitBreaker:
    """
    Circuit breaker pattern for trading risk management.
    
    Opens (blocks trading) when:
    - Max daily loss exceeded
    - Max weekly loss exceeded
    - Max consecutive losses hit
    - Execution failures exceed threshold
    
    Automatically resets based on time periods.
    """
    
    def __init__(self, config: Dict):
        """
        Initialize circuit breaker.
        
        Config keys:
        - max_daily_loss_pct: Daily loss limit (% of capital)
        - max_weekly_loss_pct: Weekly loss limit (% of capital)
        - max_consecutive_losses: Max losing trades in a row
        - max_execution_failures: Max API failures before circuit opens
        - initial_capital: Starting capital for percentage calculations
        - auto_reset: Whether to auto-reset daily/weekly
        """
        self.config = config
        self.status = CircuitBreakerStatus.CLOSED
        
        # Loss tracking
        self.daily_tracker = LossTracker(period_start=datetime.now())
        self.weekly_tracker = LossTracker(period_start=datetime.now())
        
        # Execution failure tracking
        self.execution_failures: List[datetime] = []
        self.failure_window_minutes = 30
        
        # Manual override
        self._manual_override_active = False
        self.override_reason: Optional[str] = None
    
    def check_status(self, current_capital: float) -> Tuple[CircuitBreakerStatus, Optional[str]]:
        """
        Check circuit breaker status and return reason if open.
        
        Args:
            current_capital: Current account capital
        
        Returns:
            (status, reason) tuple
        """
        # Manual override always takes precedence
        if self._manual_override_active:
            return CircuitBreakerStatus.OPEN, f"Manual override: {self.override_reason}"
        
        # Auto-reset if new period
        self._check_period_reset()
        
        # Check daily loss limit
        max_daily_loss = current_capital * (self.config.get('max_daily_loss_pct', 5.0) / 100)
        if abs(self.daily_tracker.get_loss()) >= max_daily_loss:
            self.status = CircuitBreakerStatus.OPEN
            return self.status, f"Daily loss limit exceeded: ${abs(self.daily_tracker.get_loss()):.2f} >= ${max_daily_loss:.2f}"
        
        # Check weekly loss limit
        max_weekly_loss = current_capital * (self.config.get('max_weekly_loss_pct', 10.0) / 100)
        if abs(self.weekly_tracker.get_loss()) >= max_weekly_loss:
            self.status = CircuitBreakerStatus.OPEN
            return self.status, f"Weekly loss limit exceeded: ${abs(self.weekly_tracker.get_loss()):.2f} >= ${max_weekly_loss:.2f}"
        
        # Check consecutive losses
        max_consecutive = self.config.get('max_consecutive_losses', 5)
        if self.daily_tracker.consecutive_losses >= max_consecutive:
            self.status = CircuitBreakerStatus.OPEN
            return self.status, f"Max consecutive losses hit: {self.daily_tracker.consecutive_losses} trades"
        
        # Check execution failures
        recent_failures = self._count_recent_failures()
        max_failures = self.config.get('max_execution_failures', 10)
        if recent_failures >= max_failures:
            self.status = CircuitBreakerStatus.OPEN
            return self.status, f"Too many execution failures: {recent_failures} in last {self.failure_window_minutes}min"
        
        # All checks passed
        self.status = CircuitBreakerStatus.CLOSED
        return self.status, ''
    
    def record_trade(self, pnl: float) -> None:
        """
        Record completed trade.
        
        Args:
            pnl: Realized P&L
        """
        self.daily_tracker.record_trade(pnl)
        self.weekly_tracker.record_trade(pnl)
        
        print(f"📊 Circuit Breaker Trade Recorded:")
        print(f"  P&L: ${pnl:.2f}")
        print(f"  Daily: ${self.daily_tracker.total_pnl:.2f} ({self.daily_tracker.winning_trades}W/{self.daily_tracker.losing_trades}L)")
        print(f"  Weekly: ${self.weekly_tracker.total_pnl:.2f}")
        print(f"  Consecutive Losses: {self.daily_tracker.consecutive_losses}")
    
    def record_execution_failure(self) -> None:
        """Record execution API failure"""
        self.execution_failures.append(datetime.now())
        
        # Cleanup old failures
        cutoff = datetime.now() - timedelta(minutes=self.failure_window_minutes)
        self.execution_failures = [f for f in self.execution_failures if f > cutoff]
        
        print(f"⚠️ Execution failure recorded: {len(self.execution_failures)} in last {self.failure_window_minutes}min")
    
    def _count_recent_failures(self) -> int:
        """Count execution failures in recent window"""
        cutoff = datetime.now() - timedelta(minutes=self.failure_window_minutes)
        self.execution_failures = [f for f in self.execution_failures if f > cutoff]
        return len(self.execution_failures)
    
    def _check_period_reset(self) -> None:
        """Auto-reset trackers for new periods"""
        if not self.config.get('auto_reset', True):
            return
        
        now = datetime.now()
        
        # Reset daily tracker at midnight
        if now.date() > self.daily_tracker.period_start.date():
            print(f"🔄 Daily tracker reset (new day)")
            self.daily_tracker.reset()
        
        # Reset weekly tracker on Monday
        if (now.weekday() == 0 and  # Monday
            now.date() > self.weekly_tracker.period_start.date()):
            print(f"🔄 Weekly tracker reset (new week)")
            self.weekly_tracker.reset()
    
    def manual_override(self, reason: str) -> None:
        """
        Manually open circuit breaker (emergency stop).

        Args:
            reason: Reason for manual intervention
        """
        self._manual_override_active = True
        self.override_reason = reason
        self.status = CircuitBreakerStatus.OPEN
        print(f"🚨 Circuit breaker manually opened: {reason}")

    def manual_open(self, reason: str) -> None:
        """Alias for manual_override"""
        self.manual_override(reason)

    def manual_close(self) -> None:
        """Reset manual override and allow trading"""
        self._manual_override_active = False
        self.override_reason = None
        self.status = CircuitBreakerStatus.CLOSED
        print(f"✅ Circuit breaker manually closed - trading resumed")

    def reset_daily(self) -> None:
        """Force reset daily loss tracker"""
        self.daily_tracker.reset()

    def reset_weekly(self) -> None:
        """Force reset weekly loss tracker"""
        self.weekly_tracker.reset()
    
    def get_stats(self) -> Dict:
        """Get circuit breaker statistics"""
        return {
            'status': self.status.value,
            'manual_override': self.manual_override,
            'daily': {
                'pnl': self.daily_tracker.total_pnl,
                'wins': self.daily_tracker.winning_trades,
                'losses': self.daily_tracker.losing_trades,
                'consecutive_losses': self.daily_tracker.consecutive_losses
            },
            'weekly': {
                'pnl': self.weekly_tracker.total_pnl,
                'wins': self.weekly_tracker.winning_trades,
                'losses': self.weekly_tracker.losing_trades
            },
            'execution_failures_recent': self._count_recent_failures()
        }


class TradingSessionFilter:
    """
    Filter trades based on trading hours and sessions.
    
    Prevents trading during:
    - Off-market hours
    - Low liquidity periods
    - Pre-defined blackout times
    """
    
    def __init__(self, config: Dict):
        """
        Initialize session filter.
        
        Config keys:
        - enabled: Whether session filtering is active
        - allowed_sessions: List of session names (ASIAN, LONDON, NEW_YORK)
        - allowed_hours_utc: List of (start_hour, end_hour) tuples
        - blackout_hours: List of (start_hour, end_hour) tuples to avoid
        """
        self.config = config
        # Auto-enable if allowed_sessions or allowed_hours_utc is provided
        self.enabled = config.get('enabled', bool(
            config.get('allowed_sessions') or config.get('allowed_hours_utc')
        ))

        # Session definitions (UTC)
        self.sessions = {
            'ASIAN': (time(23, 0), time(8, 0)),      # 11 PM - 8 AM UTC
            'LONDON': (time(8, 0), time(16, 30)),    # 8 AM - 4:30 PM UTC
            'NEW_YORK': (time(13, 0), time(22, 0))   # 1 PM - 10 PM UTC
        }
    
    def is_trading_allowed(self, timestamp: Optional[datetime] = None) -> Tuple[bool, str]:
        """
        Check if trading is allowed at given time.
        
        Args:
            timestamp: Time to check (default: now)
        
        Returns:
            (allowed, reason) tuple
        """
        if not self.enabled:
            return True, "Session filter disabled"
        
        if timestamp is None:
            timestamp = datetime.utcnow()
        
        current_time = timestamp.time()
        
        # Check allowed sessions
        allowed_sessions = self.config.get('allowed_sessions', [])
        if allowed_sessions:
            in_session = any(
                self._is_time_in_range(current_time, *self.sessions[session])
                for session in allowed_sessions
                if session in self.sessions
            )
            
            if not in_session:
                return False, f"Outside allowed trading sessions: {allowed_sessions}"
        
        # Check allowed hours
        allowed_hours = self.config.get('allowed_hours_utc', [])
        if allowed_hours:
            in_hours = any(
                self._is_time_in_range(current_time, time(start, 0), time(end, 0))
                for start, end in allowed_hours
            )
            
            if not in_hours:
                return False, f"Outside allowed trading hours"
        
        # Check blackout periods — support both tuple format and dict format
        blackout_hours = self.config.get('blackout_hours', [])
        blackout_periods = self.config.get('blackout_periods', [])
        # Normalize blackout_periods dicts ({start_hour, end_hour}) to tuples
        for bp in blackout_periods:
            if isinstance(bp, dict):
                blackout_hours.append((bp['start_hour'], bp['end_hour']))
            else:
                blackout_hours.append(bp)
        for start, end in blackout_hours:
            if self._is_time_in_range(current_time, time(start, 0), time(end, 0)):
                return False, f"In blackout period: {start}:00-{end}:00 UTC"
        
        return True, "Trading session allowed"
    
    def _is_time_in_range(self, current: time, start: time, end: time) -> bool:
        """
        Check if time is in range (handles overnight ranges).
        
        Args:
            current: Time to check
            start: Range start
            end: Range end
        
        Returns:
            True if time is in range
        """
        if start <= end:
            # Normal range (e.g., 8:00 - 16:00)
            return start <= current <= end
        else:
            # Overnight range (e.g., 23:00 - 8:00)
            return current >= start or current <= end


class SpreadSlippageFilter:
    """
    Filter trades based on spread and expected slippage.
    
    Prevents trading when:
    - Bid/ask spread is too wide
    - Market volatility suggests high slippage
    """
    
    def __init__(self, config: Dict):
        """
        Initialize spread/slippage filter.
        
        Config keys:
        - max_spread_pips: Maximum allowed spread in pips
        - max_spread_pct: Maximum allowed spread as % of price
        - max_expected_slippage_pips: Maximum acceptable slippage
        """
        self.config = config
        self.max_spread_pips = config.get('max_spread_pips', 30)
        self.max_spread_pct = config.get('max_spread_pct', 0.1)
        self.max_slippage_pips = config.get('max_expected_slippage_pips', 10)
    
    def check_spread(self, bid: float, ask: float, instrument: str) -> Tuple[bool, str]:
        """
        Check if spread is acceptable.
        
        Args:
            bid: Bid price
            ask: Ask price
            instrument: Trading instrument
        
        Returns:
            (allowed, reason) tuple
        """
        spread = ask - bid
        spread_pct = (spread / ask) * 100
        
        # Convert to pips (1 pip = 0.0001 for forex, 0.1 for gold, 0.01 for others)
        if 'USD' in instrument or 'EUR' in instrument or 'GBP' in instrument or 'JPY' in instrument:
            pip_size = 0.0001  # Forex pairs
        elif 'GOLD' in instrument or 'XAU' in instrument:
            pip_size = 0.1  # Gold (~10 cents per pip)
        else:
            pip_size = 0.01  # Other commodities / indices
        spread_pips = spread / pip_size
        
        # Check limits
        if spread_pips > self.max_spread_pips:
            return False, f"Spread too wide: {spread_pips:.1f} pips > {self.max_spread_pips} pip limit"
        
        if spread_pct > self.max_spread_pct:
            return False, f"Spread too wide: {spread_pct:.3f}% > {self.max_spread_pct}% limit"
        
        return True, f"Spread acceptable: {spread_pips:.1f} pips"


class NewsEventKillSwitch:
    """
    Prevent trading during news events and high-impact announcements.
    
    Can integrate with:
    - Economic calendar API
    - Manual blackout periods
    - Volatility spike detection
    """
    
    def __init__(self, config: Dict):
        """
        Initialize news kill switch.
        
        Config keys:
        - enabled: Whether kill switch is active
        - blackout_window_minutes: Minutes before/after news
        - high_impact_only: Only block high-impact events
        """
        self.config = config
        self.enabled = config.get('enabled', True)
        self.blackout_window = config.get('blackout_window_minutes', 15)

        # Manual blackout periods: stored as (start, end, reason)
        self.manual_blackouts: List[Tuple[datetime, datetime, str]] = []
    
    def is_trading_allowed(self, timestamp: Optional[datetime] = None) -> Tuple[bool, str]:
        """
        Check if trading is allowed (no news events).
        
        Args:
            timestamp: Time to check (default: now)
        
        Returns:
            (allowed, reason) tuple
        """
        if not self.enabled:
            return True, "News kill switch disabled"
        
        if timestamp is None:
            timestamp = datetime.now()
        
        # Check manual blackouts
        for entry in self.manual_blackouts:
            start, end = entry[0], entry[1]
            if start <= timestamp <= end:
                return False, f"Manual news blackout: {start} - {end}"
        
        # TODO: Integrate with economic calendar API
        # For now, check known high-impact times (e.g., NFP = first Friday 8:30 AM ET)
        
        return True, "No news events scheduled"
    
    @property
    def blackout_periods(self) -> List[Tuple[datetime, datetime, str]]:
        """Return manual blackout periods (alias for manual_blackouts)"""
        return self.manual_blackouts

    def add_blackout(self, start: datetime, end: datetime, reason: str = "News event") -> None:
        """
        Add manual blackout period.

        Args:
            start: Blackout start time
            end: Blackout end time
            reason: Reason for blackout
        """
        self.manual_blackouts.append((start, end, reason))
        print(f"🚫 News blackout added: {start} - {end} ({reason})")

    def remove_blackout(self, reason: str) -> bool:
        """Remove blackout period by reason. Returns True if found and removed."""
        before = len(self.manual_blackouts)
        self.manual_blackouts = [
            entry for entry in self.manual_blackouts
            if not (len(entry) > 2 and entry[2] == reason)
        ]
        return len(self.manual_blackouts) < before

    def clear_expired_blackouts(self) -> None:
        """Remove expired blackout periods"""
        now = datetime.now()
        self.manual_blackouts = [
            entry for entry in self.manual_blackouts
            if entry[1] > now
        ]

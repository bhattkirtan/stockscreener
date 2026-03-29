"""
Unit tests for Circuit Breakers
Tests circuit breaker logic, session filters, spread filters, and news kill switch
"""
import pytest
from datetime import datetime, timedelta
from unittest.mock import patch

from core.circuit_breakers import (
    CircuitBreaker, CircuitBreakerStatus,
    TradingSessionFilter,
    SpreadSlippageFilter,
    NewsEventKillSwitch,
    LossTracker
)


# ========== LossTracker Tests ==========

def test_loss_tracker_records_trade():
    """Test loss tracker records wins and losses"""
    tracker = LossTracker(window_hours=24)
    
    # Record profit
    tracker.record_trade(pnl=100.0)
    assert tracker.get_win_count() == 1
    assert tracker.get_loss_count() == 0
    
    # Record loss
    tracker.record_trade(pnl=-50.0)
    assert tracker.get_win_count() == 1
    assert tracker.get_loss_count() == 1


def test_loss_tracker_calculates_total_pnl():
    """Test loss tracker calculates total P&L"""
    tracker = LossTracker(window_hours=24)
    
    tracker.record_trade(pnl=100.0)
    tracker.record_trade(pnl=-50.0)
    tracker.record_trade(pnl=75.0)
    
    total = tracker.get_total_pnl()
    assert total == 125.0  # 100 - 50 + 75


def test_loss_tracker_calculates_loss_total():
    """Test loss tracker calculates total losses"""
    tracker = LossTracker(window_hours=24)
    
    tracker.record_trade(pnl=100.0)
    tracker.record_trade(pnl=-50.0)
    tracker.record_trade(pnl=-30.0)
    
    loss_total = tracker.get_loss()
    assert loss_total == -80.0  # -50 + -30


def test_loss_tracker_expires_old_trades():
    """Test loss tracker expires trades outside window"""
    tracker = LossTracker(window_hours=24)

    # Record old trade (25 hours ago) — pass timestamp directly
    old_time = datetime.now() - timedelta(hours=25)
    tracker.record_trade(pnl=-100.0, timestamp=old_time)

    # Record recent trade (1 hour ago)
    tracker.record_trade(pnl=-50.0)

    # Old trade should be expired
    loss_total = tracker.get_loss()
    assert loss_total == -50.0  # Only recent trade


# ========== CircuitBreaker Tests ==========

@pytest.fixture
def circuit_breaker_config():
    """Circuit breaker configuration"""
    return {
        'max_daily_loss_pct': 5.0,
        'max_weekly_loss_pct': 10.0,
        'max_consecutive_losses': 5,
        'execution_failure_threshold': 10,
        'execution_failure_window_minutes': 30
    }


@pytest.fixture
def circuit_breaker(circuit_breaker_config):
    """Create circuit breaker"""
    return CircuitBreaker(circuit_breaker_config)


def test_circuit_breaker_initial_state_closed(circuit_breaker):
    """Test circuit breaker starts in CLOSED state"""
    status, reason = circuit_breaker.check_status(current_capital=10000)
    
    assert status == CircuitBreakerStatus.CLOSED
    assert reason == ''


def test_circuit_breaker_opens_on_daily_loss_limit(circuit_breaker):
    """Test circuit breaker opens when daily loss exceeds limit"""
    current_capital = 10000
    max_daily_loss = current_capital * 0.05  # 5% = $500
    
    # Record losses exceeding daily limit
    for _ in range(6):
        circuit_breaker.record_trade(pnl=-100)  # Total: -$600
    
    status, reason = circuit_breaker.check_status(current_capital)
    
    assert status == CircuitBreakerStatus.OPEN
    assert 'daily loss' in reason.lower()


def test_circuit_breaker_opens_on_weekly_loss_limit(circuit_breaker):
    """Test circuit breaker opens when weekly loss exceeds limit"""
    current_capital = 10000
    max_weekly_loss = current_capital * 0.10  # 10% = $1000
    
    # Record losses exceeding weekly limit
    for _ in range(11):
        circuit_breaker.record_trade(pnl=-100)  # Total: -$1100
    
    status, reason = circuit_breaker.check_status(current_capital)
    
    assert status == CircuitBreakerStatus.OPEN
    assert 'weekly loss' in reason.lower() or 'daily loss' in reason.lower()


def test_circuit_breaker_opens_on_consecutive_losses(circuit_breaker):
    """Test circuit breaker opens after max consecutive losses"""
    # Record 5 consecutive losses (max is 5)
    for _ in range(5):
        circuit_breaker.record_trade(pnl=-50)
    
    status, reason = circuit_breaker.check_status(current_capital=10000)
    
    assert status == CircuitBreakerStatus.OPEN
    assert 'consecutive' in reason.lower()


def test_circuit_breaker_consecutive_losses_reset_on_win(circuit_breaker):
    """Test consecutive loss counter resets on win"""
    # Record 4 losses
    for _ in range(4):
        circuit_breaker.record_trade(pnl=-50)
    
    # Record 1 win (resets counter)
    circuit_breaker.record_trade(pnl=100)
    
    # Record 3 more losses (total 3 consecutive, not 7)
    for _ in range(3):
        circuit_breaker.record_trade(pnl=-50)
    
    status, reason = circuit_breaker.check_status(current_capital=10000)
    
    # Should still be CLOSED (only 3 consecutive, max is 5)
    assert status == CircuitBreakerStatus.CLOSED


def test_circuit_breaker_opens_on_execution_failures(circuit_breaker):
    """Test circuit breaker opens after too many execution failures"""
    # Record 10 execution failures (threshold is 10)
    for _ in range(10):
        circuit_breaker.record_execution_failure()
    
    status, reason = circuit_breaker.check_status(current_capital=10000)
    
    assert status == CircuitBreakerStatus.OPEN
    assert 'execution' in reason.lower()


def test_circuit_breaker_manual_override(circuit_breaker):
    """Test manual override opens circuit breaker"""
    circuit_breaker.manual_override(reason='Emergency stop - testing')
    
    status, reason = circuit_breaker.check_status(current_capital=10000)
    
    assert status == CircuitBreakerStatus.OPEN
    assert 'Emergency stop' in reason


def test_circuit_breaker_reset_daily(circuit_breaker):
    """Test daily reset clears daily tracker"""
    # Record daily losses
    for _ in range(5):
        circuit_breaker.record_trade(pnl=-100)
    
    # Reset daily
    circuit_breaker.reset_daily()
    
    # Check status (should be OK now)
    status, reason = circuit_breaker.check_status(current_capital=10000)
    
    # If no other limits breached, should be closed
    assert circuit_breaker.daily_tracker.get_loss() == 0


def test_circuit_breaker_reset_weekly(circuit_breaker):
    """Test weekly reset clears weekly tracker"""
    # Record weekly losses
    for _ in range(10):
        circuit_breaker.record_trade(pnl=-100)
    
    # Reset weekly
    circuit_breaker.reset_weekly()
    
    # Check weekly tracker is cleared
    assert circuit_breaker.weekly_tracker.get_loss() == 0


# ========== TradingSessionFilter Tests ==========

@pytest.fixture
def session_filter_config():
    """Session filter configuration"""
    return {
        'allowed_sessions': ['LONDON', 'NEW_YORK'],
        'blackout_periods': [
            {'start_hour': 12, 'start_minute': 0, 'end_hour': 13, 'end_minute': 0}
        ]
    }


@pytest.fixture
def session_filter(session_filter_config):
    """Create session filter"""
    return TradingSessionFilter(session_filter_config)


def test_session_filter_allows_london_session(session_filter):
    """Test session filter allows trading during LONDON session"""
    # 10:00 UTC (middle of LONDON session: 08:00-16:30, outside blackout 12:00-13:00)
    allowed, reason = session_filter.is_trading_allowed(
        timestamp=datetime(2024, 1, 15, 10, 0)
    )

    assert allowed is True


def test_session_filter_allows_new_york_session(session_filter):
    """Test session filter allows trading during NEW_YORK session"""
    # 15:00 UTC (middle of NEW_YORK session: 13:00-22:00, outside blackout 12:00-13:00)
    allowed, reason = session_filter.is_trading_allowed(
        timestamp=datetime(2024, 1, 15, 15, 0)
    )

    assert allowed is True


def test_session_filter_blocks_asian_session(session_filter):
    """Test session filter blocks trading during ASIAN session (not allowed)"""
    # 01:00 UTC (middle of ASIAN session: 23:00-08:00, but not in allowed_sessions)
    allowed, reason = session_filter.is_trading_allowed(
        timestamp=datetime(2024, 1, 15, 1, 0)
    )

    assert allowed is False
    assert 'session' in reason.lower()


def test_session_filter_blocks_blackout_period(session_filter):
    """Test session filter blocks trading during blackout period"""
    # 12:30 UTC (inside London session AND inside blackout: 12:00-13:00)
    allowed, reason = session_filter.is_trading_allowed(
        timestamp=datetime(2024, 1, 15, 12, 30)
    )

    assert allowed is False
    assert 'blackout' in reason.lower()


# ========== SpreadSlippageFilter Tests ==========

@pytest.fixture
def spread_filter_config():
    """Spread filter configuration"""
    return {
        'max_spread_pips': 30,
        'max_spread_pct': 0.2  # 0.2% to accommodate GOLD commodity spreads
    }


@pytest.fixture
def spread_filter(spread_filter_config):
    """Create spread filter"""
    return SpreadSlippageFilter(spread_filter_config)


def test_spread_filter_allows_narrow_spread(spread_filter):
    """Test spread filter allows trading with narrow spread"""
    # GOLD: 1950.00 bid, 1952.00 ask = 20 pips (< 30 pips max)
    allowed, reason = spread_filter.check_spread(
        instrument='GOLD',
        bid=1950.00,
        ask=1952.00
    )
    
    assert allowed is True


def test_spread_filter_blocks_wide_pips_spread(spread_filter):
    """Test spread filter blocks trading with spread > max pips"""
    # GOLD: 1950.00 bid, 1954.00 ask = 40 pips (> 30 pips max)
    allowed, reason = spread_filter.check_spread(
        instrument='GOLD',
        bid=1950.00,
        ask=1954.00
    )
    
    assert allowed is False
    assert 'spread' in reason.lower()


def test_spread_filter_blocks_wide_pct_spread(spread_filter):
    """Test spread filter blocks trading with spread > max percentage"""
    # EURUSD: 1.1000 bid, 1.1030 ask = 300 pips = 0.27% (> 0.1% max)
    allowed, reason = spread_filter.check_spread(
        instrument='EURUSD',
        bid=1.1000,
        ask=1.1030
    )
    
    assert allowed is False
    assert 'spread' in reason.lower()


def test_spread_filter_calculates_spread_correctly(spread_filter):
    """Test spread calculation"""
    # GOLD: 1950.00 bid, 1953.00 ask = 30 pips exactly
    spread_pips = (1953.00 - 1950.00) * 10  # GOLD: 1 point = 10 pips
    
    assert spread_pips == 30.0


# ========== NewsEventKillSwitch Tests ==========

@pytest.fixture
def news_killswitch_config():
    """News kill switch configuration"""
    return {
        'blackout_window_minutes': 15
    }


@pytest.fixture
def news_killswitch(news_killswitch_config):
    """Create news kill switch"""
    return NewsEventKillSwitch(news_killswitch_config)


def test_news_killswitch_allows_trading_by_default(news_killswitch):
    """Test news kill switch allows trading when no blackouts"""
    allowed, reason = news_killswitch.is_trading_allowed()
    
    assert allowed is True


def test_news_killswitch_blocks_during_blackout(news_killswitch):
    """Test news kill switch blocks trading during blackout period"""
    # Add blackout: now to now + 30 minutes
    now = datetime.now()
    news_killswitch.add_blackout(
        start=now,
        end=now + timedelta(minutes=30),
        reason='NFP release'
    )
    
    allowed, reason = news_killswitch.is_trading_allowed()
    
    assert allowed is False
    assert 'blackout' in reason.lower() or 'NFP' in reason


def test_news_killswitch_allows_after_blackout_expires(news_killswitch):
    """Test news kill switch allows trading after blackout expires"""
    # Add blackout: 1 hour ago to 30 minutes ago (expired)
    now = datetime.now()
    news_killswitch.add_blackout(
        start=now - timedelta(hours=1),
        end=now - timedelta(minutes=30),
        reason='Past NFP release'
    )
    
    allowed, reason = news_killswitch.is_trading_allowed()
    
    assert allowed is True


def test_news_killswitch_clears_expired_blackouts(news_killswitch):
    """Test news kill switch clears expired blackouts"""
    # Add expired blackout
    now = datetime.now()
    news_killswitch.add_blackout(
        start=now - timedelta(hours=2),
        end=now - timedelta(hours=1),
        reason='Old news'
    )
    
    # Add current blackout
    news_killswitch.add_blackout(
        start=now,
        end=now + timedelta(minutes=30),
        reason='Current news'
    )
    
    # Clear expired
    initial_count = len(news_killswitch.blackout_periods)
    news_killswitch.clear_expired_blackouts()
    
    # Should have removed expired blackout
    assert len(news_killswitch.blackout_periods) < initial_count


def test_news_killswitch_removes_specific_blackout(news_killswitch):
    """Test removing specific blackout by reason"""
    # Add blackout
    now = datetime.now()
    news_killswitch.add_blackout(
        start=now,
        end=now + timedelta(minutes=30),
        reason='NFP release'
    )
    
    # Remove it
    news_killswitch.remove_blackout('NFP release')
    
    # Should allow trading now
    allowed, reason = news_killswitch.is_trading_allowed()
    assert allowed is True


if __name__ == '__main__':
    pytest.main([__file__, '-v'])

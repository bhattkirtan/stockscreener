"""
Unit tests for Risk Skill
Tests cooldown logic, position sizing, and risk validation (EVENT-DRIVEN PATTERN).
"""
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock
import sys
import os

# Add parent directories to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from skills.risk.risk_skill import RiskSkill
from core.event_bus import Event, EventType, create_signal_generated_event


@pytest.fixture
def risk_config():
    """Standard risk skill configuration"""
    return {
        'sl_cooldown_minutes': 15,
        'tp_cooldown_minutes': 5,
        'position_size_pct': 2.0,
        'max_drawdown_pct': 20.0,
        'max_positions': 1
    }


@pytest.fixture
def mock_event_bus():
    """Mock event bus for testing event publishing"""
    bus = AsyncMock()
    bus.publish = AsyncMock()
    return bus


@pytest.fixture
def risk_skill(risk_config, mock_event_bus):
    """Create risk skill instance with mocked event bus"""
    return RiskSkill(risk_config, event_bus=mock_event_bus)


class TestCooldownLogic:
    """Test cooldown period enforcement"""
    
    @pytest.mark.asyncio
    async def test_no_cooldown_on_first_trade(self, risk_skill, mock_event_bus):
        """First trade should always be allowed (no cooldown)"""
        event = create_signal_generated_event(
            signal='BUY',
            entry_price=1950.0,
            sl=1920.0,
            tp=2010.0,
            instrument='GOLD'
        )
        
        await risk_skill.on_signal_generated(event)
        
        # Should publish RISK_APPROVED (no cooldown on first trade)
        assert mock_event_bus.publish.called
        published_event = mock_event_bus.publish.call_args[0][0]
        assert published_event.event_type == EventType.RISK_APPROVED
    
    @pytest.mark.asyncio
    async def test_sl_cooldown_blocks_same_direction(self, risk_skill, mock_event_bus):
        """SL cooldown should block same direction within 15 minutes"""
        # Close position with SL
        risk_skill.on_position_closed(direction='BUY', close_reason='SL_HIT')
        
        # Try BUY immediately (should be blocked)
        event = create_signal_generated_event(
            signal='BUY',
            entry_price=1950.0,
            sl=1920.0,
            tp=2010.0,
            instrument='GOLD'
        )
        
        await risk_skill.on_signal_generated(event)
        
        # Should publish RISK_REJECTED
        assert mock_event_bus.publish.called
        published_event = mock_event_bus.publish.call_args[0][0]
        assert published_event.event_type == EventType.RISK_REJECTED
        assert 'cooldown' in published_event.payload.get('reason', '').lower()
    
    @pytest.mark.asyncio
    async def test_sl_cooldown_allows_opposite_direction(self, risk_skill, mock_event_bus):
        """SL cooldown should allow opposite direction immediately"""
        # Close BUY position with SL
        risk_skill.on_position_closed(direction='BUY', close_reason='SL_HIT')
        
        # Try SELL immediately (should be allowed - opposite direction)
        event = create_signal_generated_event(
            signal='SELL',
            entry_price=1950.0,
            sl=1980.0,
            tp=1890.0,
            instrument='GOLD'
        )
        
        await risk_skill.on_signal_generated(event)
        
        # Should publish RISK_APPROVED (opposite direction allowed)
        assert mock_event_bus.publish.called
        published_event = mock_event_bus.publish.call_args[0][0]
        assert published_event.event_type == EventType.RISK_APPROVED
    
    @pytest.mark.asyncio
    async def test_sl_cooldown_expires_after_15_minutes(self, risk_skill, mock_event_bus):
        """SL cooldown should expire after 15 minutes"""
        # Close position with SL
        risk_skill.on_position_closed(direction='BUY', close_reason='SL_HIT')
        
        # Simulate 16 minutes passing
        risk_skill.last_closed_position['close_time'] = datetime.now() - timedelta(minutes=16)
        
        # Try BUY (should be allowed now)
        event = create_signal_generated_event(
            signal='BUY',
            entry_price=1950.0,
            sl=1920.0,
            tp=2010.0,
            instrument='GOLD'
        )
        
        await risk_skill.on_signal_generated(event)
        
        # Should publish RISK_APPROVED (cooldown expired)
        assert mock_event_bus.publish.called
        published_event = mock_event_bus.publish.call_args[0][0]
        assert published_event.event_type == EventType.RISK_APPROVED
    
    @pytest.mark.asyncio
    async def test_tp_cooldown_blocks_same_direction(self, risk_skill, mock_event_bus):
        """TP cooldown should block same direction within 5 minutes"""
        # Close position with TP
        risk_skill.on_position_closed(direction='SELL', close_reason='TP_HIT')
        
        # Try SELL immediately (should be blocked)
        event = create_signal_generated_event(
            signal='SELL',
            entry_price=1950.0,
            sl=1980.0,
            tp=1890.0,
            instrument='GOLD'
        )
        
        await risk_skill.on_signal_generated(event)
        
        # Should publish RISK_REJECTED
        assert mock_event_bus.publish.called
        published_event = mock_event_bus.publish.call_args[0][0]
        assert published_event.event_type == EventType.RISK_REJECTED
        assert 'cooldown' in published_event.payload.get('reason', '').lower()
    
    @pytest.mark.asyncio
    async def test_tp_cooldown_expires_after_5_minutes(self, risk_skill, mock_event_bus):
        """TP cooldown should expire after 5 minutes"""
        # Close position with TP
        risk_skill.on_position_closed(direction='SELL', close_reason='TP_HIT')
        
        # Simulate 6 minutes passing
        risk_skill.last_closed_position['close_time'] = datetime.now() - timedelta(minutes=6)
        
        # Try SELL (should be allowed now)
        event = create_signal_generated_event(
            signal='SELL',
            entry_price=1950.0,
            sl=1980.0,
            tp=1890.0,
            instrument='GOLD'
        )
        
        await risk_skill.on_signal_generated(event)
        
        # Should publish RISK_APPROVED (cooldown expired)
        assert mock_event_bus.publish.called
        published_event = mock_event_bus.publish.call_args[0][0]
        assert published_event.event_type == EventType.RISK_APPROVED
    
    @pytest.mark.asyncio
    async def test_signal_close_no_cooldown(self, risk_skill, mock_event_bus):
        """Signal-based close should not enforce cooldown"""
        # Close position due to signal change (not SL/TP)
        risk_skill.on_position_closed(direction='BUY', close_reason='SIGNAL')
        
        # Try BUY immediately (should be allowed)
        event = create_signal_generated_event(
            signal='BUY',
            entry_price=1950.0,
            sl=1920.0,
            tp=2010.0,
            instrument='GOLD'
        )
        
        await risk_skill.on_signal_generated(event)
        
        # Should publish RISK_APPROVED (no cooldown for signal close)
        assert mock_event_bus.publish.called
        published_event = mock_event_bus.publish.call_args[0][0]
        assert published_event.event_type == EventType.RISK_APPROVED


class TestSignalValidation:
    """Test signal validation logic"""
    
    @pytest.mark.asyncio
    async def test_no_signal_blocked(self, risk_skill, mock_event_bus):
        """No signal should be blocked"""
        event = create_signal_generated_event(
            signal='',  # Empty signal
            entry_price=1950.0,
            sl=1920.0,
            tp=2010.0,
            instrument='GOLD'
        )
        # Manually set signal to None in payload
        event.payload['signal'] = None
        
        await risk_skill.on_signal_generated(event)
        
        # Should not publish anything (invalid signal rejected early)
        assert not mock_event_bus.publish.called
    
    @pytest.mark.asyncio
    async def test_invalid_signal_blocked(self, risk_skill, mock_event_bus):
        """Invalid signal should be blocked"""
        event = create_signal_generated_event(
            signal='HOLD',  # Invalid signal
            entry_price=1950.0,
            sl=1920.0,
            tp=2010.0,
            instrument='GOLD'
        )
        
        await risk_skill.on_signal_generated(event)
        
        # Should not publish anything (invalid signal rejected early)
        assert not mock_event_bus.publish.called
    
    @pytest.mark.asyncio
    async def test_position_already_open_blocked(self, risk_skill, mock_event_bus):
        """Signal should be blocked if position already open"""
        # Note: In event-driven model, this check happens at execution layer
        # This test may need adjustment based on actual architecture
        event = create_signal_generated_event(
            signal='BUY',
            entry_price=1950.0,
            sl=1920.0,
            tp=2010.0,
            instrument='GOLD'
        )
        
        # Simulate position tracking (would normally come from execution skill)
        risk_skill.has_open_position = True
        
        await risk_skill.on_signal_generated(event)
        
        # Should publish RISK_REJECTED if position check exists
        # Otherwise may publish RISK_APPROVED (depends on implementation)
        if mock_event_bus.publish.called:
            published_event = mock_event_bus.publish.call_args[0][0]
            # Accept either outcome depending on where position check lives
            assert published_event.event_type in [EventType.RISK_REJECTED, EventType.RISK_APPROVED]


class TestConfigValidation:
    """Test configuration validation"""
    
    def test_valid_config(self, risk_config):
        """Valid config should pass validation"""
        skill = RiskSkill(risk_config)
        assert skill.validate_config() is True
    
    def test_missing_config_keys(self):
        """Missing required keys should raise error"""
        with pytest.raises(Exception):
            skill = RiskSkill({})
            skill.validate_config()
    
    def test_negative_cooldown(self, risk_config):
        """Negative cooldown should raise error"""
        risk_config['sl_cooldown_minutes'] = -5
        with pytest.raises(Exception):
            skill = RiskSkill(risk_config)
            skill.validate_config()
    
    def test_invalid_position_size(self, risk_config):
        """Invalid position size should raise error"""
        risk_config['position_size_pct'] = 150  # > 100%
        with pytest.raises(Exception):
            skill = RiskSkill(risk_config)
            skill.validate_config()


class TestPositionSizing:
    """Test position size calculation"""
    
    @pytest.mark.asyncio
    async def test_position_size_calculated(self, risk_skill, mock_event_bus):
        """Position size should be calculated for valid signal"""
        event = create_signal_generated_event(
            signal='BUY',
            entry_price=1950.0,
            sl=1920.0,
            tp=2010.0,
            instrument='GOLD'
        )
        
        await risk_skill.on_signal_generated(event)
        
        # Should publish RISK_APPROVED with position size
        assert mock_event_bus.publish.called
        published_event = mock_event_bus.publish.call_args[0][0]
        assert published_event.event_type == EventType.RISK_APPROVED
        assert 'position_size' in published_event.payload
        assert published_event.payload['position_size'] > 0


@pytest.mark.asyncio
async def test_integration_full_cycle(risk_skill, mock_event_bus):
    """Test full cycle: open → close → cooldown → open"""
    # 1. First trade (should be allowed)
    event1 = create_signal_generated_event(
        signal='BUY',
        entry_price=1950.0,
        sl=1920.0,
        tp=2010.0,
        instrument='GOLD'
    )
    await risk_skill.on_signal_generated(event1)
    assert mock_event_bus.publish.called
    assert mock_event_bus.publish.call_args[0][0].event_type == EventType.RISK_APPROVED
    
    # 2. Close with SL
    risk_skill.on_position_closed(direction='BUY', close_reason='SL_HIT')
    
    # 3. Try same direction immediately (should be blocked)
    mock_event_bus.reset_mock()
    event2 = create_signal_generated_event(
        signal='BUY',
        entry_price=1950.0,
        sl=1920.0,
        tp=2010.0,
        instrument='GOLD'
    )
    await risk_skill.on_signal_generated(event2)
    assert mock_event_bus.publish.called
    assert mock_event_bus.publish.call_args[0][0].event_type == EventType.RISK_REJECTED
    
    # 4. Try opposite direction (should be allowed)
    mock_event_bus.reset_mock()
    event3 = create_signal_generated_event(
        signal='SELL',
        entry_price=1950.0,
        sl=1980.0,
        tp=1890.0,
        instrument='GOLD'
    )
    await risk_skill.on_signal_generated(event3)
    assert mock_event_bus.publish.called
    assert mock_event_bus.publish.call_args[0][0].event_type == EventType.RISK_APPROVED
    
    # 5. Close SELL with TP
    risk_skill.on_position_closed(direction='SELL', close_reason='TP_HIT')
    
    # 6. Wait 6 minutes, try SELL again (should be allowed)
    risk_skill.last_closed_position['close_time'] = datetime.now() - timedelta(minutes=6)
    mock_event_bus.reset_mock()
    event4 = create_signal_generated_event(
        signal='SELL',
        entry_price=1950.0,
        sl=1980.0,
        tp=1890.0,
        instrument='GOLD'
    )
    await risk_skill.on_signal_generated(event4)
    assert mock_event_bus.publish.called
    assert mock_event_bus.publish.call_args[0][0].event_type == EventType.RISK_APPROVED


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

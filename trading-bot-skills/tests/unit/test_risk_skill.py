"""
Unit tests for Risk Skill
Tests cooldown logic, position sizing, and risk validation.
"""
import pytest
from datetime import datetime, timedelta
import sys
import os

# Add parent directories to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from skills.risk.risk_skill import RiskSkill
from skills.base_skill import Context


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
def risk_skill(risk_config):
    """Create risk skill instance"""
    return RiskSkill(risk_config)


class TestCooldownLogic:
    """Test cooldown period enforcement"""
    
    @pytest.mark.asyncio
    async def test_no_cooldown_on_first_trade(self, risk_skill):
        """First trade should always be allowed (no cooldown)"""
        context = Context(signal='BUY')
        result = await risk_skill.execute(context)
        
        assert result.is_allowed is True
        assert "No cooldown active" in result.risk_reason
    
    @pytest.mark.asyncio
    async def test_sl_cooldown_blocks_same_direction(self, risk_skill):
        """SL cooldown should block same direction within 15 minutes"""
        # Close position with SL
        risk_skill.on_position_closed(direction='BUY', close_reason='SL_HIT')
        
        # Try BUY immediately (should be blocked)
        context = Context(signal='BUY')
        result = await risk_skill.execute(context)
        
        assert result.is_allowed is False
        assert "SL cooldown" in result.risk_reason
    
    @pytest.mark.asyncio
    async def test_sl_cooldown_allows_opposite_direction(self, risk_skill):
        """SL cooldown should allow opposite direction immediately"""
        # Close BUY position with SL
        risk_skill.on_position_closed(direction='BUY', close_reason='SL_HIT')
        
        # Try SELL immediately (should be allowed - opposite direction)
        context = Context(signal='SELL')
        result = await risk_skill.execute(context)
        
        assert result.is_allowed is True
        assert "Different direction" in result.risk_reason
    
    @pytest.mark.asyncio
    async def test_sl_cooldown_expires_after_15_minutes(self, risk_skill):
        """SL cooldown should expire after 15 minutes"""
        # Close position with SL
        risk_skill.on_position_closed(direction='BUY', close_reason='SL_HIT')
        
        # Simulate 16 minutes passing
        risk_skill.last_closed_position['close_time'] = datetime.now() - timedelta(minutes=16)
        
        # Try BUY (should be allowed now)
        context = Context(signal='BUY')
        result = await risk_skill.execute(context)
        
        assert result.is_allowed is True
        assert "cooldown passed" in result.risk_reason.lower()
    
    @pytest.mark.asyncio
    async def test_tp_cooldown_blocks_same_direction(self, risk_skill):
        """TP cooldown should block same direction within 5 minutes"""
        # Close position with TP
        risk_skill.on_position_closed(direction='SELL', close_reason='TP_HIT')
        
        # Try SELL immediately (should be blocked)
        context = Context(signal='SELL')
        result = await risk_skill.execute(context)
        
        assert result.is_allowed is False
        assert "TP cooldown" in result.risk_reason
    
    @pytest.mark.asyncio
    async def test_tp_cooldown_expires_after_5_minutes(self, risk_skill):
        """TP cooldown should expire after 5 minutes"""
        # Close position with TP
        risk_skill.on_position_closed(direction='SELL', close_reason='TP_HIT')
        
        # Simulate 6 minutes passing
        risk_skill.last_closed_position['close_time'] = datetime.now() - timedelta(minutes=6)
        
        # Try SELL (should be allowed now)
        context = Context(signal='SELL')
        result = await risk_skill.execute(context)
        
        assert result.is_allowed is True
        assert "cooldown passed" in result.risk_reason.lower()
    
    @pytest.mark.asyncio
    async def test_signal_close_no_cooldown(self, risk_skill):
        """Signal-based close should not enforce cooldown"""
        # Close position due to signal change (not SL/TP)
        risk_skill.on_position_closed(direction='BUY', close_reason='SIGNAL')
        
        # Try BUY immediately (should be allowed)
        context = Context(signal='BUY')
        result = await risk_skill.execute(context)
        
        assert result.is_allowed is True


class TestSignalValidation:
    """Test signal validation logic"""
    
    @pytest.mark.asyncio
    async def test_no_signal_blocked(self, risk_skill):
        """No signal should be blocked"""
        context = Context(signal=None)
        result = await risk_skill.execute(context)
        
        assert result.is_allowed is False
        assert "No valid signal" in result.risk_reason
    
    @pytest.mark.asyncio
    async def test_invalid_signal_blocked(self, risk_skill):
        """Invalid signal should be blocked"""
        context = Context(signal='HOLD')
        result = await risk_skill.execute(context)
        
        assert result.is_allowed is False
        assert "No valid signal" in result.risk_reason
    
    @pytest.mark.asyncio
    async def test_position_already_open_blocked(self, risk_skill):
        """Signal should be blocked if position already open"""
        context = Context(
            signal='BUY',
            current_position={'deal_id': 'DEAL123', 'direction': 'BUY'}
        )
        result = await risk_skill.execute(context)
        
        assert result.is_allowed is False
        assert "already open" in result.risk_reason.lower()


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
    async def test_position_size_calculated(self, risk_skill):
        """Position size should be calculated for valid signal"""
        context = Context(signal='BUY')
        result = await risk_skill.execute(context)
        
        assert result.is_allowed is True
        assert result.position_size > 0


@pytest.mark.asyncio
async def test_integration_full_cycle(risk_skill):
    """Test full cycle: open → close → cooldown → open"""
    # 1. First trade (should be allowed)
    context1 = Context(signal='BUY')
    result1 = await risk_skill.execute(context1)
    assert result1.is_allowed is True
    
    # 2. Close with SL
    risk_skill.on_position_closed(direction='BUY', close_reason='SL_HIT')
    
    # 3. Try same direction immediately (should be blocked)
    context2 = Context(signal='BUY')
    result2 = await risk_skill.execute(context2)
    assert result2.is_allowed is False
    
    # 4. Try opposite direction (should be allowed)
    context3 = Context(signal='SELL')
    result3 = await risk_skill.execute(context3)
    assert result3.is_allowed is True
    
    # 5. Close SELL with TP
    risk_skill.on_position_closed(direction='SELL', close_reason='TP_HIT')
    
    # 6. Wait 6 minutes, try SELL again (should be allowed)
    risk_skill.last_closed_position['close_time'] = datetime.now() - timedelta(minutes=6)
    context4 = Context(signal='SELL')
    result4 = await risk_skill.execute(context4)
    assert result4.is_allowed is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

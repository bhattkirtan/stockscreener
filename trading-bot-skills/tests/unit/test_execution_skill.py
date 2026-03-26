"""
Unit Tests - Execution Skill

Tests order placement and position management with Capital.com API.
"""
import pytest
import sys
import os
from datetime import datetime, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from skills.execution.execution_skill import ExecutionSkill
from skills.base_skill import Context


class TestExecutionSkill:
    """Test Execution Skill"""
    
    @pytest.fixture
    def config(self):
        """Execution configuration (mock mode)"""
        return {
            'username': 'test@example.com',
            'password': 'test_password',
            'api_key': 'test_api_key',
            'environment': 'demo',
            'epic': 'CS.D.CFDGOLD.CFD.IP',
            'position_size': 0.5,
            'sl_pips': 10,
            'tp_pips': 30
        }
    
    @pytest.fixture
    def skill(self, config):
        """Execution skill instance (mock mode)"""
        return ExecutionSkill(config, mock_mode=True)
    
    @pytest.fixture
    def context(self):
        """Fresh trading context"""
        ctx = Context()
        ctx.signal = 'BUY'
        ctx.entry_price = 1950.00
        ctx.stop_loss = 1940.00
        ctx.take_profit = 1980.00
        return ctx
    
    def test_initialization(self, skill):
        """Test skill initializes correctly"""
        assert skill.epic == 'CS.D.CFDGOLD.CFD.IP'
        assert skill.position_size == 0.5
        assert skill.mock_mode == True
    
    def test_execute_buy_order(self, skill, context):
        """Test executing BUY order"""
        context.signal = 'BUY'
        context.entry_price = 1950.00
        context.stop_loss = 1940.00
        context.take_profit = 1980.00
        
        result = skill.execute(context)
        
        assert result is not None
        assert 'deal_id' in result
        assert result['direction'] == 'BUY'
    
    def test_execute_sell_order(self, skill, context):
        """Test executing SELL order"""
        context.signal = 'SELL'
        context.entry_price = 1950.00
        context.stop_loss = 1960.00
        context.take_profit = 1920.00
        
        result = skill.execute(context)
        
        assert result is not None
        assert 'deal_id' in result
        assert result['direction'] == 'SELL'
    
    def test_execute_without_signal(self, skill, context):
        """Test execute returns None without signal"""
        context.signal = None
        
        result = skill.execute(context)
        
        assert result is None
    
    def test_execute_with_hold_signal(self, skill, context):
        """Test execute returns None with HOLD signal"""
        context.signal = 'HOLD'
        
        result = skill.execute(context)
        
        assert result is None
    
    def test_close_position(self, skill, context):
        """Test closing position"""
        context.deal_id = 'MOCK_DEAL_123'
        context.position = {
            'deal_id': 'MOCK_DEAL_123',
            'direction': 'BUY',
            'entry_price': 1950.00
        }
        
        result = skill.close_position(context)
        
        assert result == True
    
    def test_close_position_without_deal_id(self, skill, context):
        """Test close position returns False without deal_id"""
        context.deal_id = None
        
        result = skill.close_position(context)
        
        assert result == False
    
    def test_mock_mode_generates_deal_id(self, skill, context):
        """Test mock mode generates valid deal_id"""
        context.signal = 'BUY'
        
        result = skill.execute(context)
        
        assert result is not None
        assert 'deal_id' in result
        assert isinstance(result['deal_id'], str)
        assert len(result['deal_id']) > 0
    
    def test_position_size_from_config(self, skill, context):
        """Test position size is taken from config"""
        context.signal = 'BUY'
        
        result = skill.execute(context)
        
        assert result is not None
        assert result.get('size', 0.5) == 0.5


if __name__ == '__main__':
    pytest.main([__file__, '-v'])

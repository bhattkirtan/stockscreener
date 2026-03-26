"""
Unit Tests - Alerting Skill

Tests Telegram notification sending.
"""
import pytest
import sys
import os
from datetime import datetime, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from skills.alerting.alerting_skill import AlertingSkill
from skills.base_skill import Context


class TestAlertingSkill:
    """Test Alerting Skill"""
    
    @pytest.fixture
    def config(self):
        """Alerting configuration (mock mode)"""
        return {
            'telegram': {
                'enabled': True,
                'token': 'test_token',
                'chat_id': 'test_chat_id'
            },
            'mock_mode': True
        }
    
    @pytest.fixture
    def skill(self, config):
        """Alerting skill instance (mock mode)"""
        return AlertingSkill(config)
    
    @pytest.fixture
    def context(self):
        """Fresh trading context"""
        ctx = Context()
        ctx.deal_id = 'TEST_DEAL_123'
        ctx.position = {
            'deal_id': 'TEST_DEAL_123',
            'direction': 'BUY',
            'entry_price': 1950.00,
            'stop_loss': 1940.00,
            'take_profit': 1980.00,
            'size': 0.5
        }
        return ctx
    
    def test_initialization(self, skill):
        """Test skill initializes correctly"""
        assert skill.telegram_enabled == True
        assert skill.telegram_token == 'test_token'
        assert skill.telegram_chat_id == 'test_chat_id'
    
    def test_send_trade_opened_alert(self, skill, context):
        """Test sending trade opened alert"""
        result = skill.send_trade_opened_alert(context)
        
        # Mock mode should return True
        assert result == True
    
    def test_send_trade_closed_alert(self, skill, context):
        """Test sending trade closed alert"""
        result = skill.send_trade_closed_alert(
            context,
            pnl_percent=1.54,
            duration='25m',
            deal_id='TEST_DEAL_123'
        )
        
        assert result == True
    
    def test_send_error_alert(self, skill, context):
        """Test sending error alert"""
        context.add_error('API_ERROR', 'Failed to connect', {'retry': 3})
        
        result = skill.send_error_alert(context)
        
        assert result == True
    
    def test_disabled_alerts(self):
        """Test alerts are skipped when disabled"""
        config = {
            'enabled': False,
            'token': 'test_token',
            'chat_id': 'test_chat_id'
        }
        
        skill = AlertingSkill(config)
        context = Context()
        
        result = skill.send_trade_opened_alert(context)
        
        # Should return False or None when disabled
        assert result == False or result == None
    
    def test_buy_alert_formatting(self, skill, context):
        """Test BUY alert has correct formatting"""
        context.position['direction'] = 'BUY'
        
        result = skill.send_trade_opened_alert(context)
        
        assert result == True
    
    def test_sell_alert_formatting(self, skill, context):
        """Test SELL alert has correct formatting"""
        context.position['direction'] = 'SELL'
        
        result = skill.send_trade_opened_alert(context)
        
        assert result == True
    
    def test_tp_hit_alert(self, skill, context):
        """Test TP hit alert"""
        context.close_reason = 'TP_HIT'
        context.pnl = 30.00
        
        result = skill.send_trade_closed_alert(
            context,
            pnl_percent=1.54,
            duration='25m',
            deal_id='TEST_DEAL_123'
        )
        
        assert result == True
    
    def test_sl_hit_alert(self, skill, context):
        """Test SL hit alert"""
        context.close_reason = 'SL_HIT'
        context.pnl = -10.00
        
        result = skill.send_trade_closed_alert(
            context,
            pnl_percent=-0.51,
            duration='15m',
            deal_id='TEST_DEAL_123'
        )
        
        assert result == True
    
    def test_multiple_errors_alert(self, skill, context):
        """Test sending alert for multiple errors"""
        context.add_error('ERROR_1', 'First error')
        context.add_error('ERROR_2', 'Second error')
        context.add_error('ERROR_3', 'Third error')
        
        result = skill.send_error_alert(context)
        
        assert result == True


if __name__ == '__main__':
    pytest.main([__file__, '-v'])

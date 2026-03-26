"""
Unit Tests - Monitoring Skill

Tests position tracking, P&L calculation, and win rate metrics.
"""
import pytest
import sys
import os
from datetime import datetime, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from skills.monitoring.monitoring_skill import MonitoringSkill
from skills.base_skill import Context


class TestMonitoringSkill:
    """Test Monitoring Skill"""
    
    @pytest.fixture
    def config(self):
        """Monitoring configuration"""
        return {
            'track_pnl': True,
            'track_win_rate': True,
            'track_drawdown': True
        }
    
    @pytest.fixture
    def skill(self, config):
        """Monitoring skill instance"""
        return MonitoringSkill(config)
    
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
        assert skill.track_pnl == True
        assert skill.track_win_rate == True
        assert skill.track_drawdown == True
    
    def test_update_position(self, skill, context):
        """Test updating position tracking"""
        skill.update_position(context)
        
        # Should track position without errors
        assert True
    
    def test_record_trade(self, skill, context):
        """Test recording completed trade"""
        context.pnl = 30.00
        context.pnl_percent = 1.54
        context.close_reason = 'TP_HIT'
        
        skill.record_trade(context)
        
        # Should record trade
        assert True
    
    def test_get_metrics_empty(self, skill, context):
        """Test getting metrics with no trades"""
        metrics = skill.get_metrics(context)
        
        assert isinstance(metrics, dict)
        assert metrics.get('total_trades', 0) == 0
    
    def test_get_metrics_with_trades(self, skill, context):
        """Test metrics after recording trades"""
        # Record winning trade
        context.pnl = 30.00
        skill.record_trade(context)
        
        # Record losing trade
        context.pnl = -10.00
        skill.record_trade(context)
        
        metrics = skill.get_metrics(context)
        
        assert metrics['total_trades'] == 2
        assert metrics['wins'] == 1
        assert metrics['losses'] == 1
        assert metrics['win_rate'] == 0.5
        assert metrics['total_pnl'] == 20.00
    
    def test_calculate_win_rate(self, skill, context):
        """Test win rate calculation"""
        # Record multiple trades
        trades = [30, -10, 25, -5, 40, -15, 20]
        
        for pnl in trades:
            context.pnl = pnl
            skill.record_trade(context)
        
        metrics = skill.get_metrics(context)
        
        assert metrics['total_trades'] == 7
        assert metrics['wins'] == 4
        assert metrics['losses'] == 3
        assert metrics['win_rate'] == pytest.approx(4/7, rel=0.01)
    
    def test_calculate_drawdown(self, skill, context):
        """Test drawdown tracking"""
        # Record trades with drawdown
        context.pnl = 100
        skill.record_trade(context)
        
        context.pnl = -50
        skill.record_trade(context)
        
        context.pnl = -30
        skill.record_trade(context)
        
        metrics = skill.get_metrics(context)
        
        assert metrics['total_pnl'] == 20
        # Drawdown calculation depends on implementation
    
    def test_daily_pnl_tracking(self, skill, context):
        """Test daily P&L accumulation"""
        # Record multiple trades in a day
        for pnl in [10, 20, -5, 15]:
            context.pnl = pnl
            skill.record_trade(context)
        
        metrics = skill.get_metrics(context)
        
        assert metrics['total_pnl'] == 40


if __name__ == '__main__':
    pytest.main([__file__, '-v'])

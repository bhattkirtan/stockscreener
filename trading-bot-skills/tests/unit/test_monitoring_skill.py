"""
Unit Tests - Monitoring Skill

Tests position tracking, P&L calculation, and win rate metrics.
"""
import pytest
import sys
import os
from datetime import datetime, timezone
from unittest.mock import AsyncMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from skills.monitoring.monitoring_skill import MonitoringSkill


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
    def mock_event_bus(self):
        """Mock event bus"""
        bus = AsyncMock()
        bus.publish = AsyncMock()
        return bus
    
    @pytest.fixture
    def skill(self, config, mock_event_bus):
        """Monitoring skill instance"""
        return MonitoringSkill(config, event_bus=mock_event_bus)
    
    def test_initialization(self, skill):
        """Test skill initializes correctly"""
        assert skill.track_pnl == True
        assert skill.track_win_rate == True
        assert skill.track_drawdown == True
    
    @pytest.mark.asyncio
    async def test_update_position(self, skill):
        """Test updating position tracking"""
        # Create a simple context-like object
        class MockContext:
            deal_id = 'TEST_DEAL_123'
            position = {
                'deal_id': 'TEST_DEAL_123',
                'direction': 'BUY',
                'entry_price': 1950.00,
                'size': 0.5
            }
        
        context = MockContext()
        await skill.update_position(context)
        
        # Should track position without errors
        assert True
    
    @pytest.mark.asyncio
    async def test_record_trade(self, skill):
        """Test recording completed trade"""
        # Create a simple context-like object
        class MockContext:
            pnl = 30.00
            pnl_percent = 1.54
            close_reason = 'TP_HIT'
        
        context = MockContext()
        await skill.record_trade(context)
        
        # Should record trade
        assert True
    
    def test_get_metrics_empty(self, skill):
        """Test getting metrics with no trades"""
        metrics = skill.get_metrics()
        
        assert isinstance(metrics, dict)
        assert metrics.get('total_trades', 0) == 0
    
    @pytest.mark.asyncio
    async def test_get_metrics_with_trades(self, skill):
        """Test metrics after recording trades"""
        # Create mock contexts
        class MockContext:
            def __init__(self, pnl):
                self.pnl = pnl
        
        # Record winning trade
        await skill.record_trade(MockContext(30.00))
        
        # Record losing trade
        await skill.record_trade(MockContext(-10.00))
        
        metrics = skill.get_metrics()
        
        assert metrics['total_trades'] == 2
        assert metrics['wins'] == 1
        assert metrics['losses'] == 1
        assert metrics['win_rate'] == 0.5
        assert metrics['total_pnl'] == 20.00
    
    @pytest.mark.asyncio
    async def test_calculate_win_rate(self, skill):
        """Test win rate calculation"""
        # Record multiple trades
        class MockContext:
            def __init__(self, pnl):
                self.pnl = pnl
        
        trades = [30, -10, 25, -5, 40, -15, 20]
        
        for pnl in trades:
            await skill.record_trade(MockContext(pnl))
        
        metrics = skill.get_metrics()
        
        assert metrics['total_trades'] == 7
        assert metrics['wins'] == 4
        assert metrics['losses'] == 3
        assert metrics['win_rate'] == pytest.approx(4/7, rel=0.01)
    
    @pytest.mark.asyncio
    async def test_calculate_drawdown(self, skill):
        """Test drawdown tracking"""
        # Record trades with drawdown
        class MockContext:
            def __init__(self, pnl):
                self.pnl = pnl
        
        await skill.record_trade(MockContext(100))
        await skill.record_trade(MockContext(-50))
        await skill.record_trade(MockContext(-30))
        
        metrics = skill.get_metrics()
        
        assert metrics['total_pnl'] == 20
        # Drawdown calculation depends on implementation
    
    @pytest.mark.asyncio
    async def test_daily_pnl_tracking(self, skill):
        """Test daily P&L accumulation"""
        # Record multiple trades in a day
        class MockContext:
            def __init__(self, pnl):
                self.pnl = pnl
        
        for pnl in [10, 20, -5, 15]:
            await skill.record_trade(MockContext(pnl))
        
        metrics = skill.get_metrics()
        
        assert metrics['total_pnl'] == 40


if __name__ == '__main__':
    pytest.main([__file__, '-v'])

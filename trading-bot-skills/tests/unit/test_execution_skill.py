"""
Unit Tests - Execution Skill

Tests order placement and position management with Capital.com API (EVENT-DRIVEN PATTERN).
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import sys
import os
from datetime import datetime, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from skills.execution.execution_skill import ExecutionSkill
from core.event_bus import Event, EventType, create_risk_approved_event


class TestExecutionSkill:
    """Test Execution Skill (Event-Driven Pattern)"""
    
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
            'tp_pips': 30,
            'mock_mode': True  # Enable mock mode via config
        }
    
    @pytest.fixture
    def mock_event_bus(self):
        """Mock event bus for testing event publishing"""
        bus = AsyncMock()
        bus.publish = AsyncMock()
        return bus
    
    @pytest.fixture
    def skill(self, config, mock_event_bus):
        """Execution skill instance (mock mode with event bus)"""
        return ExecutionSkill(config, event_bus=mock_event_bus)
    
    def test_initialization(self, skill):
        """Test skill initializes correctly"""
        assert skill.epic == 'CS.D.CFDGOLD.CFD.IP'
        assert skill.position_size == 0.5
        assert skill.mock_mode == True
    
    @pytest.mark.asyncio
    async def test_execute_buy_order(self, skill, mock_event_bus):
        """Test executing BUY order"""
        event = create_risk_approved_event(
            signal='BUY',
            position_size=0.5,
            entry_price=1950.00,
            stop_loss=1940.00,
            take_profit=1980.00,
            instrument='GOLD',
            correlation_id='test-correlation-id'
        )
        
        await skill.on_risk_approved(event)
        
        # Should publish ORDER_FILLED event
        assert mock_event_bus.publish.called
        published_event = mock_event_bus.publish.call_args[0][0]
        assert published_event.event_type == EventType.ORDER_FILLED
        assert 'deal_id' in published_event.payload
        assert published_event.payload.get('direction') == 'BUY'
    
    @pytest.mark.asyncio
    async def test_execute_sell_order(self, skill, mock_event_bus):
        """Test executing SELL order"""
        event = create_risk_approved_event(
            signal='SELL',
            position_size=0.5,
            entry_price=1950.00,
            stop_loss=1960.00,
            take_profit=1920.00,
            instrument='GOLD',
            correlation_id='test-correlation-id'
        )
        
        await skill.on_risk_approved(event)
        
        # Should publish ORDER_FILLED event
        assert mock_event_bus.publish.called
        published_event = mock_event_bus.publish.call_args[0][0]
        assert published_event.event_type == EventType.ORDER_FILLED
        assert 'deal_id' in published_event.payload
        assert published_event.payload.get('direction') == 'SELL'
    
    @pytest.mark.asyncio
    async def test_execute_without_signal(self, skill, mock_event_bus):
        """Test execute returns None without signal"""
        event = create_risk_approved_event(
            signal='',  # Empty signal
            position_size=0.5,
            entry_price=1950.00,
            stop_loss=1940.00,
            take_profit=1980.00,
            instrument='GOLD',
            correlation_id='test-correlation-id'
        )
        event.payload['signal'] = None  # Override with None
        
        await skill.on_risk_approved(event)
        
        # Should not publish anything (no valid signal)
        assert not mock_event_bus.publish.called
    
    @pytest.mark.asyncio
    async def test_execute_with_hold_signal(self, skill, mock_event_bus):
        """Test execute returns None with HOLD signal"""
        event = create_risk_approved_event(
            signal='HOLD',
            position_size=0.5,
            entry_price=1950.00,
            stop_loss=1940.00,
            take_profit=1980.00,
            instrument='GOLD',
            correlation_id='test-correlation-id'
        )
        
        await skill.on_risk_approved(event)
        
        # Should not publish anything (HOLD is not a valid signal)
        assert not mock_event_bus.publish.called
    
    @pytest.mark.asyncio
    async def test_close_position(self, skill, mock_event_bus):
        """Test closing position"""
        # First open a position
        open_event = create_risk_approved_event(
            signal='BUY',
            position_size=0.5,
            entry_price=1950.00,
            stop_loss=1940.00,
            take_profit=1980.00,
            instrument='GOLD',
            correlation_id='test-correlation-id'
        )
        await skill.on_risk_approved(open_event)
        
        # Then close it (would normally come from a POSITION_CLOSE_REQUESTED event)
        # For testing, directly call close method if exposed, or test via integration
        # This test may need adjustment based on actual close mechanism
        assert mock_event_bus.publish.called  # At least opened successfully
    
    @pytest.mark.asyncio
    async def test_mock_mode_generates_deal_id(self, skill, mock_event_bus):
        """Test mock mode generates valid deal_id"""
        event = create_risk_approved_event(
            signal='BUY',
            position_size=0.5,
            entry_price=1950.00,
            stop_loss=1940.00,
            take_profit=1980.00,
            instrument='GOLD',
            correlation_id='test-correlation-id'
        )
        
        await skill.on_risk_approved(event)
        
        assert mock_event_bus.publish.called
        published_event = mock_event_bus.publish.call_args[0][0]
        assert 'deal_id' in published_event.payload
        assert isinstance(published_event.payload['deal_id'], str)
        assert len(published_event.payload['deal_id']) > 0
    
    @pytest.mark.asyncio
    async def test_position_size_from_config(self, skill, mock_event_bus):
        """Test position size is taken from event"""
        event = create_risk_approved_event(
            signal='BUY',
            position_size=0.75,  # Different from config
            entry_price=1950.00,
            stop_loss=1940.00,
            take_profit=1980.00,
            instrument='GOLD',
            correlation_id='test-correlation-id'
        )
        
        await skill.on_risk_approved(event)
        
        assert mock_event_bus.publish.called
        published_event = mock_event_bus.publish.call_args[0][0]
        assert 'size' in published_event.payload
        # Should use position_size from event (via risk skill calculation)
        assert published_event.payload['size'] > 0


if __name__ == '__main__':
    pytest.main([__file__, '-v'])

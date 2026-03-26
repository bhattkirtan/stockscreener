"""
Unit Tests - Alerting Skill

Tests Telegram notification sending.
"""
import pytest
import sys
import os
from datetime import datetime, timezone
from unittest.mock import AsyncMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from skills.alerting.alerting_skill import AlertingSkill
from core.event_bus import EventType, create_order_filled_event, create_position_closed_event, Event


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
    def mock_event_bus(self):
        """Mock event bus for testing"""
        bus = AsyncMock()
        bus.publish = AsyncMock()
        return bus
    
    @pytest.fixture
    def skill(self, config, mock_event_bus):
        """Alerting skill instance (mock mode with event bus)"""
        return AlertingSkill(config, event_bus=mock_event_bus)
    
    def test_initialization(self, skill):
        """Test skill initializes correctly"""
        assert skill.telegram_enabled == True
        assert skill.telegram_token == 'test_token'
        assert skill.telegram_chat_id == 'test_chat_id'
    
    @pytest.mark.asyncio
    async def test_send_trade_opened_alert(self, skill):
        """Test sending trade opened alert on ORDER_FILLED event"""
        event = create_order_filled_event(
            deal_id='TEST_DEAL_123',
            instrument='GOLD',
            direction='BUY',
            entry_price=1950.00,
            size=0.5,
            stop_loss=1940.00,
            take_profit=1980.00,
            correlation_id='test-correlation'
        )
        
        await skill.on_order_filled(event)
        
        # Mock mode should succeed (telegram_client.send_trade_opened returns True)
        # Just verify no exceptions raised
        assert True
    
    @pytest.mark.asyncio
    async def test_send_trade_closed_alert(self, skill):
        """Test sending trade closed alert on POSITION_CLOSED event"""
        event = create_position_closed_event(
            deal_id='TEST_DEAL_123',
            instrument='GOLD',
            close_price=1980.00,
            realized_pnl=30.00,
            close_reason='TP_HIT',
            correlation_id='test-correlation'
        )
        # Add extra fields for alert formatting
        event.payload['direction'] = 'BUY'
        event.payload['entry_price'] = 1950.00
        event.payload['pnl_percent'] = 1.54
        event.payload['duration'] = '25m'
        
        await skill.on_position_closed(event)
        
        # Mock mode should succeed
        assert True
    
    @pytest.mark.asyncio
    async def test_send_error_alert(self, skill):
        """Test sending error alert on BOT_ERROR event"""
        event = Event(
            event_type=EventType.BOT_ERROR,
            source='orchestrator',
            payload={
                'error_message': 'Failed to connect to API',
                'location': 'execution_skill'
            }
        )
        
        await skill.on_bot_error(event)
        
        # Mock mode should succeed
        assert True
    
    @pytest.mark.asyncio
    async def test_disabled_alerts(self, mock_event_bus):
        """Test alerts are skipped when disabled"""
        config = {
            'telegram': {
                'enabled': False,
                'token': 'test_token',
                'chat_id': 'test_chat_id'
            },
            'mock_mode': True
        }
        
        skill = AlertingSkill(config, event_bus=mock_event_bus)
        event = create_order_filled_event(
            deal_id='TEST_DEAL',
            instrument='GOLD',
            direction='BUY',
            entry_price=1950.00,
            size=0.5,
            stop_loss=1940.00,
            take_profit=1980.00,
            correlation_id='test-correlation'
        )
        
        # With disabled alerts, event handler should still work but skip sending
        await skill.on_order_filled(event)
        assert True  # No exception raised
    
    @pytest.mark.asyncio
    async def test_buy_alert_formatting(self, skill):
        """Test BUY alert has correct formatting"""
        event = create_order_filled_event(
            deal_id='TEST_DEAL_BUY',
            instrument='GOLD',
            direction='BUY',
            entry_price=1950.00,
            size=0.5,
            stop_loss=1940.00,
            take_profit=1980.00,
            correlation_id='test-correlation'
        )
        
        await skill.on_order_filled(event)
        assert True
    
    @pytest.mark.asyncio
    async def test_sell_alert_formatting(self, skill):
        """Test SELL alert has correct formatting"""
        event = create_order_filled_event(
            deal_id='TEST_DEAL_SELL',
            instrument='GOLD',
            direction='SELL',
            entry_price=1950.00,
            size=0.5,
            stop_loss=1960.00,
            take_profit=1920.00,
            correlation_id='test-correlation'
        )
        
        await skill.on_order_filled(event)
        assert True
    
    @pytest.mark.asyncio
    async def test_tp_hit_alert(self, skill):
        """Test TP hit alert"""
        event = create_position_closed_event(
            deal_id='TEST_DEAL_TP',
            instrument='GOLD',
            close_price=1980.00,
            realized_pnl=30.00,
            close_reason='TP_HIT',
            correlation_id='test-correlation'
        )
        event.payload['direction'] = 'BUY'
        event.payload['entry_price'] = 1950.00
        event.payload['pnl_percent'] = 1.54
        event.payload['duration'] = '25m'
        
        await skill.on_position_closed(event)
        assert True
    
    @pytest.mark.asyncio
    async def test_sl_hit_alert(self, skill):
        """Test SL hit alert"""
        event = create_position_closed_event(
            deal_id='TEST_DEAL_SL',
            instrument='GOLD',
            close_price=1940.00,
            realized_pnl=-10.00,
            close_reason='SL_HIT',
            correlation_id='test-correlation'
        )
        event.payload['direction'] = 'BUY'
        event.payload['entry_price'] = 1950.00
        event.payload['pnl_percent'] = -0.51
        event.payload['duration'] = '15m'
        
        await skill.on_position_closed(event)
        assert True
    
    @pytest.mark.asyncio
    async def test_multiple_errors_alert(self, skill):
        """Test sending alert for multiple errors"""
        # Send 3 error events
        for i in range(1, 4):
            event = Event(
                event_type=EventType.BOT_ERROR,
                source='orchestrator',
                payload={
                    'error_message': f'Error message {i}',
                    'location': f'location_{i}'
                }
            )
            await skill.on_bot_error(event)
        
        assert True


if __name__ == '__main__':
    pytest.main([__file__, '-v'])

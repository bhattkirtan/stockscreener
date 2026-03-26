"""
Unit Tests - Storage Skill

Tests Firestore persistence operations.
"""
import pytest
import sys
import os
from datetime import datetime, timezone
from unittest.mock import AsyncMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from skills.storage.storage_skill import StorageSkill
from core.event_bus import EventType, create_signal_generated_event, create_order_filled_event, create_position_closed_event


class TestStorageSkill:
    """Test Storage Skill"""
    
    @pytest.fixture
    def config(self):
        """Storage configuration (mock mode)"""
        return {
            'project_id': 'test-project',
            'collections': {
                'positions': 'test_positions',
                'signals': 'test_signals',
                'trade_history': 'test_trades',
                'bot_status': 'test_status'
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
        """Storage skill instance (mock mode with event bus)"""
        return StorageSkill(config, event_bus=mock_event_bus)
    
    def test_initialization(self, skill):
        """Test skill initializes correctly"""
        assert skill.project_id == 'test-project'
        assert skill.positions_collection == 'test_positions'
    
    @pytest.mark.asyncio
    async def test_save_position(self, skill):
        """Test saving position on ORDER_FILLED event"""
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
        # Mock mode - should succeed without exceptions
        assert True
    
    @pytest.mark.asyncio
    async def test_save_position_without_deal_id(self, skill):
        """Test save position handles missing deal_id gracefully"""
        event = create_order_filled_event(
            deal_id='',  # Empty deal_id
            instrument='GOLD',
            direction='BUY',
            entry_price=1950.00,
            size=0.5,
            stop_loss=1940.00,
            take_profit=1980.00,
            correlation_id='test-correlation'
        )
        event.payload['deal_id'] = None  # Override with None
        
        await skill.on_order_filled(event)
        # Should log warning but not crash
        assert True
    
    @pytest.mark.asyncio
    async def test_close_position(self, skill):
        """Test closing position (CRITICAL: in finally block)"""
        event = create_position_closed_event(
            deal_id='TEST_DEAL_123',
            instrument='GOLD',
            close_price=1980.00,
            realized_pnl=30.00,
            close_reason='TP_HIT',
            correlation_id='test-correlation'
        )
        
        # Should always succeed (finally block behavior)
        await skill.on_position_closed(event)
        assert True
    
    @pytest.mark.asyncio
    async def test_close_position_never_raises(self, skill):
        """Test close position never raises exceptions"""
        event = create_position_closed_event(
            deal_id='',  # Invalid
            instrument='GOLD',
            close_price=1980.00,
            realized_pnl=30.00,
            close_reason='TP_HIT',
            correlation_id='test-correlation'
        )
        event.payload['deal_id'] = None  # Override with None
        
        try:
            await skill.on_position_closed(event)
            # Should not raise
            assert True
        except Exception as e:
            pytest.fail(f"on_position_closed raised exception: {e}")
    
    @pytest.mark.asyncio
    async def test_log_signal(self, skill):
        """Test logging trading signal on SIGNAL_GENERATED event"""
        event = create_signal_generated_event(
            signal='BUY',
            entry_price=1950.00,
            sl=1940.00,
            tp=1980.00,
            instrument='GOLD'
        )
        
        await skill.on_signal_generated(event)
        # Mock mode - should succeed
        assert True
    
    @pytest.mark.asyncio
    async def test_log_trade(self, skill):
        """Test logging completed trade on POSITION_CLOSED event"""
        event = create_position_closed_event(
            deal_id='TEST_DEAL_123',
            instrument='GOLD',
            close_price=1980.00,
            realized_pnl=30.00,
            close_reason='TP_HIT',
            correlation_id='test-correlation'
        )
        # Add extra fields
        event.payload['pnl_percent'] = 1.54
        
        await skill.on_position_closed(event)
        # Mock mode - should succeed
        assert True
    
    @pytest.mark.asyncio
    async def test_multiple_save_operations(self, skill):
        """Test multiple save operations work"""
        # Save position
        open_event = create_order_filled_event(
            deal_id='TEST_DEAL_123',
            instrument='GOLD',
            direction='BUY',
            entry_price=1950.00,
            size=0.5,
            stop_loss=1940.00,
            take_profit=1980.00,
            correlation_id='test-correlation'
        )
        await skill.on_order_filled(open_event)
        
        # Update position (another save with same deal_id)
        update_event = create_order_filled_event(
            deal_id='TEST_DEAL_123',
            instrument='GOLD',
            direction='BUY',
            entry_price=1950.00,
            size=0.5,
            stop_loss=1945.00,  # Updated SL
            take_profit=1980.00,
            correlation_id='test-correlation'
        )
        await skill.on_order_filled(update_event)
        
        # Close position
        close_event = create_position_closed_event(
            deal_id='TEST_DEAL_123',
            instrument='GOLD',
            close_price=1980.00,
            realized_pnl=30.00,
            close_reason='TP_HIT',
            correlation_id='test-correlation'
        )
        await skill.on_position_closed(close_event)
        
        # All operations should succeed
        assert True


if __name__ == '__main__':
    pytest.main([__file__, '-v'])

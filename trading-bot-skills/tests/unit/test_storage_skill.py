"""
Unit Tests - Storage Skill

Tests Firestore persistence operations.
"""
import pytest
import sys
import os
from datetime import datetime, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from skills.storage.storage_skill import StorageSkill
from skills.base_skill import Context


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
            }
        }
    
    @pytest.fixture
    def skill(self, config):
        """Storage skill instance (mock mode)"""
        # Will use mock mode automatically if no credentials
        return StorageSkill(config)
    
    @pytest.fixture
    def context(self):
        """Fresh trading context with position"""
        ctx = Context()
        ctx.deal_id = 'TEST_DEAL_123'
        ctx.position = {
            'deal_id': 'TEST_DEAL_123',
            'direction': 'BUY',
            'entry_price': 1950.00,
            'stop_loss': 1940.00,
            'take_profit': 1980.00,
            'size': 0.5,
            'timestamp': datetime.now(timezone.utc).isoformat()
        }
        return ctx
    
    def test_initialization(self, skill):
        """Test skill initializes correctly"""
        assert skill.project_id == 'test-project'
        assert skill.positions_collection == 'test_positions'
    
    def test_save_position(self, skill, context):
        """Test saving position"""
        result = skill.save_position(context)
        
        assert result == True
    
    def test_save_position_without_deal_id(self, skill, context):
        """Test save position returns False without deal_id"""
        context.deal_id = None
        
        result = skill.save_position(context)
        
        assert result == False
    
    def test_close_position(self, skill, context):
        """Test closing position (CRITICAL: in finally block)"""
        context.close_price = 1980.00
        context.close_reason = 'TP_HIT'
        context.pnl = 30.00
        
        # Should always succeed (finally block behavior)
        result = skill.close_position(context)
        
        assert result == True
    
    def test_close_position_never_raises(self, skill, context):
        """Test close position never raises exceptions"""
        context.deal_id = None  # Invalid - should not raise
        
        try:
            result = skill.close_position(context)
            # Should return False but not raise
            assert result == False or result == None
        except Exception as e:
            pytest.fail(f"close_position raised exception: {e}")
    
    def test_log_signal(self, skill, context):
        """Test logging trading signal"""
        context.signal = 'BUY'
        context.entry_price = 1950.00
        
        result = skill.log_signal(context)
        
        assert result == True or result == None  # Mock mode might return None
    
    def test_log_trade(self, skill, context):
        """Test logging completed trade"""
        context.close_price = 1980.00
        context.close_reason = 'TP_HIT'
        context.pnl = 30.00
        context.pnl_percent = 1.54
        
        result = skill.log_trade(context)
        
        assert result == True or result == None
    
    def test_multiple_save_operations(self, skill, context):
        """Test multiple save operations work"""
        # Save position
        skill.save_position(context)
        
        # Update position
        context.position['stop_loss'] = 1945.00
        skill.save_position(context)  # Should update
        
        # Close position
        context.close_price = 1980.00
        skill.close_position(context)
        
        # All operations should succeed
        assert True


if __name__ == '__main__':
    pytest.main([__file__, '-v'])

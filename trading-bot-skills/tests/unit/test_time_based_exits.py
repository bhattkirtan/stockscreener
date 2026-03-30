"""
Unit tests for Time-Based Exits
Tests IntraDayTimeExit and EndOfDayClose functionality.

Critical for Gold trading to avoid overnight exposure and manage intraday risk.
Matches backtester behavior in cloud-function/src/core/backtester.py
"""
import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from orchestrator.production_orchestrator import ProductionOrchestrator, IntraDayTimeExit, EndOfDayClose
from core.event_bus import Event, EventType
from core.position_state import Position, PositionStatus


# ========== Fixtures ==========

@pytest.fixture
def config():
    """Test configuration with time-based exits enabled"""
    return {
        'instrument': 'GOLD',
        'timeframe': 'M5',
        'initial_capital': 10000,
        'sl_cooldown_minutes': 15,
        'tp_cooldown_minutes': 5,
        'circuit_breaker': {},
        'trading_sessions': {},
        'spread_filter': {},
        'monitoring': {},
        'time_based_exits': {
            'max_hours': 4,
            'intraday_enabled': True,
            'eod_hour': 16,
            'eod_enabled': True
        }
    }


@pytest.fixture
def mock_execution_skill():
    """Mock execution skill with close_position method"""
    skill = MagicMock()
    skill.close_position = AsyncMock(return_value=True)
    return skill


@pytest.fixture
def mock_event_bus():
    """Mock event bus"""
    bus = AsyncMock()
    bus.publish = AsyncMock()
    return bus


# ========== IntraDayTimeExit Tests ==========

class TestIntraDayTimeExit:
    """Test intraday time-based position closure"""
    
    def test_position_open_less_than_max_no_close(self):
        """Position open < max hours → Not closed"""
        time_exit = IntraDayTimeExit(max_hours=4, enabled=True)
        
        position = Position(
            deal_id='DEAL_123',
            instrument='GOLD',
            direction='BUY',
            entry_price=2650.0,
            size=0.5,
            stop_loss=2630.0,
            take_profit=2690.0,
            status=PositionStatus.OPEN,
            opened_at=datetime.now() - timedelta(hours=2),  # 2 hours ago
            signal_timestamp=datetime.now()
        )
        
        should_close = time_exit.should_close_time(position, datetime.now())
        assert should_close is False
    
    def test_position_open_exactly_max_hours_closes(self):
        """Position open = max hours → Closed"""
        time_exit = IntraDayTimeExit(max_hours=4, enabled=True)
        
        position = Position(
            deal_id='DEAL_123',
            instrument='GOLD',
            direction='BUY',
            entry_price=2650.0,
            size=0.5,
            stop_loss=2630.0,
            take_profit=2690.0,
            status=PositionStatus.OPEN,
            opened_at=datetime.now() - timedelta(hours=4),  # Exactly 4 hours ago
            signal_timestamp=datetime.now()
        )
        
        should_close = time_exit.should_close_time(position, datetime.now())
        assert should_close is True
    
    def test_position_open_more_than_max_closes(self):
        """Position open > max hours → Closed"""
        time_exit = IntraDayTimeExit(max_hours=4, enabled=True)
        
        position = Position(
            deal_id='DEAL_123',
            instrument='GOLD',
            direction='BUY',
            entry_price=2650.0,
            size=0.5,
            stop_loss=2630.0,
            take_profit=2690.0,
            status=PositionStatus.OPEN,
            opened_at=datetime.now() - timedelta(hours=5),  # 5 hours ago
            signal_timestamp=datetime.now()
        )
        
        should_close = time_exit.should_close_time(position, datetime.now())
        assert should_close is True
    
    def test_disabled_never_closes(self):
        """Disabled → Never closes positions"""
        time_exit = IntraDayTimeExit(max_hours=4, enabled=False)
        
        position = Position(
            deal_id='DEAL_123',
            instrument='GOLD',
            direction='BUY',
            entry_price=2650.0,
            size=0.5,
            stop_loss=2630.0,
            take_profit=2690.0,
            status=PositionStatus.OPEN,
            opened_at=datetime.now() - timedelta(hours=10),  # 10 hours ago!
            signal_timestamp=datetime.now()
        )
        
        should_close = time_exit.should_close_time(position, datetime.now())
        assert should_close is False


# ========== EndOfDayClose Tests ==========

class TestEndOfDayClose:
    """Test end-of-day position closure"""
    
    def test_before_eod_hour_no_close(self):
        """Current time < EOD hour → Not closed"""
        eod_close = EndOfDayClose(close_hour=16, enabled=True)
        
        # Mock time: 10:00 AM (hour = 10)
        test_time = datetime.now().replace(hour=10, minute=0)
        
        should_close = eod_close.should_close_eod(test_time)
        assert should_close is False
    
    def test_exactly_eod_hour_closes(self):
        """Current time = EOD hour → Closed"""
        eod_close = EndOfDayClose(close_hour=16, enabled=True)
        
        # Mock time: 4:00 PM (hour = 16)
        test_time = datetime.now().replace(hour=16, minute=0)
        
        should_close = eod_close.should_close_eod(test_time)
        assert should_close is True
    
    def test_after_eod_hour_closes(self):
        """Current time > EOD hour → Closed"""
        eod_close = EndOfDayClose(close_hour=16, enabled=True)
        
        # Mock time: 6:00 PM (hour = 18)
        test_time = datetime.now().replace(hour=18, minute=0)
        
        should_close = eod_close.should_close_eod(test_time)
        assert should_close is True
    
    def test_disabled_never_closes(self):
        """Disabled → Never closes"""
        eod_close = EndOfDayClose(close_hour=16, enabled=False)
        
        # Mock time: 11:00 PM (hour = 23)
        test_time = datetime.now().replace(hour=23, minute=0)
        
        should_close = eod_close.should_close_eod(test_time)
        assert should_close is False


# ========== Integration Tests ==========

class TestTimeBasedExitsIntegration:
    """Integration tests for time-based exits in orchestrator"""
    
    @pytest.mark.asyncio
    async def test_intraday_time_exit_closes_old_position(self, config, mock_execution_skill, mock_event_bus):
        """Position open > 4 hours → Automatically closed"""
        # Create orchestrator with time exits enabled
        orch = ProductionOrchestrator(config)
        orch.event_bus = mock_event_bus
        orch.register_skill('execution', mock_execution_skill)
        
        # Use a fixed mock time so opened_at is consistent
        mock_current_time = datetime.now().replace(hour=10, minute=0, second=0, microsecond=0)
        
        # Add position opened 5 hours ago (relative to mock time)
        position = Position(
            deal_id='DEAL_OLD_123',
            instrument='GOLD',
            direction='BUY',
            entry_price=2650.0,
            size=0.5,
            stop_loss=2630.0,
            take_profit=2690.0,
            status=PositionStatus.OPEN,
            opened_at=mock_current_time - timedelta(hours=5),  # 5 hours before mock time
            signal_timestamp=mock_current_time
        )
        orch.position_manager.add_position(position)
        
        # Mock current time to be BEFORE EOD hour (e.g., 10 AM)
        with patch('orchestrator.production_orchestrator.datetime') as mock_datetime:
            mock_datetime.now.return_value = mock_current_time
            
            # Trigger time-based exit check
            await orch._check_time_based_exits()
        
        # Verify position was closed
        mock_execution_skill.close_position.assert_called_once_with('DEAL_OLD_123')
        
        # Verify POSITION_CLOSED event published
        assert mock_event_bus.publish.called
        close_event = mock_event_bus.publish.call_args[0][0]
        assert close_event.event_type == EventType.POSITION_CLOSED
        assert close_event.payload['close_reason'] == 'TIME_EXIT'
    
    @pytest.mark.asyncio
    async def test_intraday_time_exit_ignores_fresh_position(self, config, mock_execution_skill, mock_event_bus):
        """Position open < 4 hours → Not closed"""
        orch = ProductionOrchestrator(config)
        orch.event_bus = mock_event_bus
        orch.register_skill('execution', mock_execution_skill)

        # Use a fixed mock time so opened_at is consistent
        mock_current_time = datetime.now().replace(hour=10, minute=0, second=0, microsecond=0)

        # Add position opened 2 hours ago (relative to mock time)
        position = Position(
            deal_id='DEAL_FRESH_123',
            instrument='GOLD',
            direction='BUY',
            entry_price=2650.0,
            size=0.5,
            stop_loss=2630.0,
            take_profit=2690.0,
            status=PositionStatus.OPEN,
            opened_at=mock_current_time - timedelta(hours=2),  # 2 hours before mock time
            signal_timestamp=mock_current_time
        )
        orch.position_manager.add_position(position)

        # Mock current time to be BEFORE EOD hour (e.g., 10 AM)
        with patch('orchestrator.production_orchestrator.datetime') as mock_datetime:
            mock_datetime.now.return_value = mock_current_time

            # Trigger time-based exit check
            await orch._check_time_based_exits()
        
        # Verify position was NOT closed
        mock_execution_skill.close_position.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_eod_close_closes_all_positions(self, config, mock_execution_skill, mock_event_bus):
        """At EOD hour → All positions closed"""
        orch = ProductionOrchestrator(config)
        orch.event_bus = mock_event_bus
        orch.register_skill('execution', mock_execution_skill)
        
        # Add multiple positions
        for i in range(3):
            position = Position(
                deal_id=f'DEAL_{i}',
                instrument='GOLD',
                direction='BUY' if i % 2 == 0 else 'SELL',
                entry_price=2650.0,
                size=0.5,
                stop_loss=2630.0,
                take_profit=2690.0,
                status=PositionStatus.OPEN,
                opened_at=datetime.now() - timedelta(hours=i+1),
                signal_timestamp=datetime.now()
            )
            orch.position_manager.add_position(position)
        
        # Mock current time to be at/after EOD hour (4 PM = 16:00)
        with patch('orchestrator.production_orchestrator.datetime') as mock_datetime:
            mock_datetime.now.return_value = datetime.now().replace(hour=16, minute=0)
            
            # Trigger time-based exit check
            await orch._check_time_based_exits()
        
        # Verify ALL 3 positions were closed
        assert mock_execution_skill.close_position.call_count == 3
    
    @pytest.mark.asyncio
    async def test_disabled_time_exits_no_closes(self, config, mock_execution_skill, mock_event_bus):
        """Disabled time exits → No automatic closes"""
        # Disable time exits
        config['time_based_exits']['intraday_enabled'] = False
        config['time_based_exits']['eod_enabled'] = False
        
        orch = ProductionOrchestrator(config)
        orch.event_bus = mock_event_bus
        orch.register_skill('execution', mock_execution_skill)
        
        # Add old position
        position = Position(
            deal_id='DEAL_OLD',
            instrument='GOLD',
            direction='BUY',
            entry_price=2650.0,
            size=0.5,
            stop_loss=2630.0,
            take_profit=2690.0,
            status=PositionStatus.OPEN,
            opened_at=datetime.now() - timedelta(hours=10),  # 10 hours ago!
            signal_timestamp=datetime.now()
        )
        orch.position_manager.add_position(position)
        
        # Trigger check
        await orch._check_time_based_exits()
        
        # Verify NO closes (disabled)
        mock_execution_skill.close_position.assert_not_called()


# ========== Error Handling Tests ==========

class TestTimeExitErrorHandling:
    """Test error handling in time-based exits"""
    
    @pytest.mark.asyncio
    async def test_close_failure_does_not_crash(self, config, mock_execution_skill, mock_event_bus):
        """If close fails, log error but don't crash"""
        orch = ProductionOrchestrator(config)
        orch.event_bus = mock_event_bus
        orch.register_skill('execution', mock_execution_skill)
        
        # Make close fail
        mock_execution_skill.close_position = AsyncMock(return_value=False)
        
        # Add old position
        position = Position(
            deal_id='DEAL_123',
            instrument='GOLD',
            direction='BUY',
            entry_price=2650.0,
            size=0.5,
            stop_loss=2630.0,
            take_profit=2690.0,
            status=PositionStatus.OPEN,
            opened_at=datetime.now() - timedelta(hours=5),
            signal_timestamp=datetime.now()
        )
        orch.position_manager.add_position(position)
        
        # Should not raise exception
        try:
            await orch._check_time_based_exits()
            success = True
        except Exception:
            success = False
        
        assert success is True
    
    @pytest.mark.asyncio
    async def test_missing_execution_skill_graceful(self, config, mock_event_bus):
        """Missing execution skill → Log warning, don't crash"""
        orch = ProductionOrchestrator(config)
        orch.event_bus = mock_event_bus
        # Don't register execution skill
        
        # Add old position
        position = Position(
            deal_id='DEAL_123',
            instrument='GOLD',
            direction='BUY',
            entry_price=2650.0,
            size=0.5,
            stop_loss=2630.0,
            take_profit=2690.0,
            status=PositionStatus.OPEN,
            opened_at=datetime.now() - timedelta(hours=5),
            signal_timestamp=datetime.now()
        )
        orch.position_manager.add_position(position)
        
        # Should not crash
        try:
            await orch._check_time_based_exits()
            success = True
        except Exception:
            success = False
        
        assert success is True


if __name__ == '__main__':
    # Run tests with: pytest tests/unit/test_time_based_exits.py -v
    pytest.main([__file__, '-v', '-s'])

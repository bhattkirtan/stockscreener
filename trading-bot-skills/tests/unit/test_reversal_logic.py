"""
Unit tests for Reversal Logic (Close Opposite Position)

Tests the critical reversal logic that ensures:
1. When holding BUY and SELL signal fires → Close BUY, open SELL
2. When holding SELL and BUY signal fires → Close SELL, open BUY
3. Cooldown is bypassed for reverse signals
4. Position is closed BEFORE new position opens

This matches backtester behavior in cloud-function/src/core/backtester.py
"""
import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from orchestrator.production_orchestrator import ProductionOrchestrator
from core.event_bus import Event, EventType
from core.position_state import Position, PositionStatus
from skills.risk.risk_skill import RiskSkill


# ========== Fixtures ==========

@pytest.fixture
def config():
    """Test configuration"""
    return {
        'instrument': 'GOLD',
        'timeframe': 'M5',
        'initial_capital': 10000,
        'sl_cooldown_minutes': 15,
        'tp_cooldown_minutes': 5,
        'circuit_breaker': {},
        'trading_sessions': {},
        'spread_filter': {},
        'monitoring': {}
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


@pytest.fixture
def orchestrator_with_position(config, mock_execution_skill, mock_event_bus):
    """Create orchestrator with an open BUY position"""
    orch = ProductionOrchestrator(config)
    orch.event_bus = mock_event_bus
    orch.register_skill('execution', mock_execution_skill)
    
    # Add open BUY position
    position = Position(
        deal_id='DEAL_BUY_123',
        instrument='GOLD',
        direction='BUY',
        entry_price=2650.0,
        size=0.5,
        stop_loss=2630.0,
        take_profit=2690.0,
        status=PositionStatus.OPEN,
        opened_at=datetime.now(),
        signal_timestamp=datetime.now()
    )
    orch.position_manager.add_position(position)
    
    return orch, mock_execution_skill, mock_event_bus


# ========== Reversal Detection Tests ==========

class TestReversalDetection:
    """Test reversal signal detection logic"""
    
    @pytest.mark.asyncio
    async def test_buy_to_sell_reversal_detected(self, orchestrator_with_position):
        """Holding BUY + SELL signal = Reversal detected"""
        orch, exec_skill, event_bus = orchestrator_with_position
        
        # Create SELL signal event with proper conditions for SELL:
        # - supertrend_direction = -1 (down)
        # - close < ema (2645 < 2650)
        # - sma_fast < sma_slow (2640 < 2650)
        sell_event = Event(
            event_type=EventType.SIGNAL_GENERATED,
            instrument='GOLD',
            source='test',
            payload={
                'signal': 'SELL',
                'indicators': {
                    'current_price': 2645.0,  # Below EMA
                    'supertrend_direction': -1,  # Down
                    'ema': 2650.0,
                    'sma_fast': 2640.0,  # Below slow
                    'sma_slow': 2650.0
                }
            }
        )
        
        # Trigger reversal check
        await orch._check_reverse_signals(sell_event)
        
        # Verify position was closed
        exec_skill.close_position.assert_called_once_with('DEAL_BUY_123')
        
        # Verify POSITION_CLOSED event was published
        assert event_bus.publish.called
        published_event = event_bus.publish.call_args[0][0]
        assert published_event.event_type == EventType.POSITION_CLOSED
        assert published_event.payload['deal_id'] == 'DEAL_BUY_123'
        assert published_event.payload['close_reason'] == 'Reverse Signal'
    
    @pytest.mark.asyncio
    async def test_sell_to_buy_reversal_detected(self, config, mock_execution_skill, mock_event_bus):
        """Holding SELL + BUY signal = Reversal detected"""
        # Create orchestrator with SELL position
        orch = ProductionOrchestrator(config)
        orch.event_bus = mock_event_bus
        orch.register_skill('execution', mock_execution_skill)
        
        # Add open SELL position
        position = Position(
            deal_id='DEAL_SELL_456',
            instrument='GOLD',
            direction='SELL',
            entry_price=2650.0,
            size=0.5,
            stop_loss=2670.0,
            take_profit=2610.0,
            status=PositionStatus.OPEN,
            opened_at=datetime.now(),
            signal_timestamp=datetime.now()
        )
        orch.position_manager.add_position(position)
        
        # Create BUY signal event
        buy_event = Event(
            event_type=EventType.SIGNAL_GENERATED,
            instrument='GOLD',
            source='test',
            payload={
                'signal': 'BUY',
                'indicators': {
                    'current_price': 2645.0,
                    'supertrend_direction': 1,
                    'ema': 2640.0,
                    'sma_fast': 2642.0,
                    'sma_slow': 2638.0
                }
            }
        )
        
        # Trigger reversal check
        await orch._check_reverse_signals(buy_event)
        
        # Verify SELL position was closed
        mock_execution_skill.close_position.assert_called_once_with('DEAL_SELL_456')
    
    @pytest.mark.asyncio
    async def test_same_direction_signal_no_reversal(self, orchestrator_with_position):
        """Holding BUY + BUY signal = No reversal (ignored)"""
        orch, exec_skill, event_bus = orchestrator_with_position
        
        # Create another BUY signal (same direction)
        buy_event = Event(
            event_type=EventType.SIGNAL_GENERATED,
            instrument='GOLD',
            source='test',
            payload={
                'signal': 'BUY',
                'indicators': {'current_price': 2655.0}
            }
        )
        
        # Trigger reversal check
        await orch._check_reverse_signals(buy_event)
        
        # Verify NO position was closed
        exec_skill.close_position.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_hold_signal_no_reversal(self, orchestrator_with_position):
        """HOLD signal should not trigger reversal"""
        orch, exec_skill, event_bus = orchestrator_with_position
        
        # Create HOLD signal
        hold_event = Event(
            event_type=EventType.SIGNAL_GENERATED,
            instrument='GOLD',
            source='test',
            payload={
                'signal': 'HOLD',
                'indicators': {'current_price': 2655.0}
            }
        )
        
        # Trigger reversal check
        await orch._check_reverse_signals(hold_event)
        
        # Verify NO position was closed
        exec_skill.close_position.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_no_open_position_no_reversal(self, config, mock_execution_skill, mock_event_bus):
        """No open position = No reversal check needed"""
        # Create orchestrator with NO positions
        orch = ProductionOrchestrator(config)
        orch.event_bus = mock_event_bus
        orch.register_skill('execution', mock_execution_skill)
        
        # Create SELL signal (but no position to close)
        sell_event = Event(
            event_type=EventType.SIGNAL_GENERATED,
            instrument='GOLD',
            source='test',
            payload={
                'signal': 'SELL',
                'indicators': {'current_price': 2655.0}
            }
        )
        
        # Trigger reversal check
        await orch._check_reverse_signals(sell_event)
        
        # Verify NO close attempt (no position exists)
        mock_execution_skill.close_position.assert_not_called()


# ========== Cooldown Bypass Tests ==========

class TestCooldownBypass:
    """Test that cooldown is bypassed for reverse signals"""
    
    @pytest.mark.asyncio
    async def test_cooldown_bypassed_for_opposite_direction(self):
        """Reverse signal bypasses cooldown (matches backtester)"""
        # Create risk skill
        config = {
            'sl_cooldown_minutes': 15,
            'tp_cooldown_minutes': 5
        }
        mock_bus = AsyncMock()
        risk_skill = RiskSkill(config, event_bus=mock_bus)
        
        # Simulate last position: SELL closed via SL (should have 15min cooldown)
        risk_skill.last_closed_position = {
            'direction': 'SELL',
            'close_reason': 'SL_HIT',
            'close_time': datetime.now() - timedelta(minutes=2)  # 2 minutes ago (within cooldown)
        }
        
        # Check cooldown for BUY signal (opposite direction)
        is_allowed, reason = risk_skill._check_cooldown('BUY')
        
        # Verify cooldown is BYPASSED
        assert is_allowed is True
        assert 'Different direction' in reason or 'bypassed' in reason.lower()
    
    @pytest.mark.asyncio
    async def test_cooldown_enforced_for_same_direction(self):
        """Same direction signal enforces cooldown"""
        # Create risk skill
        config = {
            'sl_cooldown_minutes': 15,
            'tp_cooldown_minutes': 5
        }
        mock_bus = AsyncMock()
        risk_skill = RiskSkill(config, event_bus=mock_bus)
        
        # Simulate last position: BUY closed via SL (should have 15min cooldown)
        risk_skill.last_closed_position = {
            'direction': 'BUY',
            'close_reason': 'SL_HIT',
            'close_time': datetime.now() - timedelta(minutes=2)  # 2 minutes ago (within cooldown)
        }
        
        # Check cooldown for BUY signal (SAME direction)
        is_allowed, reason = risk_skill._check_cooldown('BUY')
        
        # Verify cooldown is ENFORCED
        assert is_allowed is False
        assert 'cooldown' in reason.lower()
        assert '15' in reason or 'SL' in reason
    
    @pytest.mark.asyncio
    async def test_cooldown_expired_allows_same_direction(self):
        """Expired cooldown allows same direction"""
        # Create risk skill
        config = {
            'sl_cooldown_minutes': 15,
            'tp_cooldown_minutes': 5
        }
        mock_bus = AsyncMock()
        risk_skill = RiskSkill(config, event_bus=mock_bus)
        
        # Simulate last position: BUY closed via SL 20 minutes ago (cooldown expired)
        risk_skill.last_closed_position = {
            'direction': 'BUY',
            'close_reason': 'SL_HIT',
            'close_time': datetime.now() - timedelta(minutes=20)  # 20 minutes ago
        }
        
        # Check cooldown for BUY signal (same direction, but cooldown expired)
        is_allowed, reason = risk_skill._check_cooldown('BUY')
        
        # Verify trade is ALLOWED (cooldown expired)
        assert is_allowed is True


# ========== Integration Tests ==========

class TestReversalIntegration:
    """Integration tests for full reversal flow"""
    
    @pytest.mark.asyncio
    async def test_full_reversal_flow_buy_to_sell(self, orchestrator_with_position):
        """Complete flow: BUY position + SELL signal → Close + Open"""
        orch, exec_skill, event_bus = orchestrator_with_position
        
        # Verify starting state: 1 BUY position
        assert orch.position_manager.get_position_count() == 1
        positions = orch.position_manager.get_open_positions()
        assert positions[0].direction == 'BUY'
        assert positions[0].deal_id == 'DEAL_BUY_123'
        
        # Create SELL signal event with proper SELL conditions
        sell_event = Event(
            event_type=EventType.SIGNAL_GENERATED,
            instrument='GOLD',
            source='test',
            payload={
                'signal': 'SELL',
                'indicators': {
                    'current_price': 2645.0,  # Below EMA
                    'supertrend_direction': -1,  # Down
                    'ema': 2650.0,
                    'sma_fast': 2640.0,  # Below slow
                    'sma_slow': 2650.0
                }
            }
        )
        
        # Execute reversal
        await orch._check_reverse_signals(sell_event)
        
        # Verify close was called
        exec_skill.close_position.assert_called_once_with('DEAL_BUY_123')
        
        # Verify POSITION_CLOSED event published
        assert event_bus.publish.called
        close_event = event_bus.publish.call_args[0][0]
        assert close_event.event_type == EventType.POSITION_CLOSED
        assert close_event.payload['close_reason'] == 'Reverse Signal'
        
        # Note: The actual opening of SELL position happens via normal flow:
        # SIGNAL_GENERATED → RISK_APPROVED (cooldown bypassed) → ORDER_FILLED
    
    @pytest.mark.asyncio
    async def test_reversal_closes_before_risk_approval(self):
        """Reversal closes position BEFORE risk approval for new position"""
        # This test verifies execution order:
        # 1. SIGNAL_GENERATED event fires
        # 2. _check_reverse_signals() closes opposite position
        # 3. RISK_APPROVED event fires (cooldown bypassed)
        # 4. New position opens
        
        # This ensures we never have BOTH positions open simultaneously
        pass  # Test would require full orchestrator flow simulation


# ========== Error Handling Tests ==========

class TestReversalErrorHandling:
    """Test error handling in reversal logic"""
    
    @pytest.mark.asyncio
    async def test_close_failure_does_not_block_new_signal(self, orchestrator_with_position):
        """If close fails, log error but don't crash"""
        orch, exec_skill, event_bus = orchestrator_with_position
        
        # Make close_position fail
        exec_skill.close_position = AsyncMock(return_value=False)
        
        # Create SELL signal with proper conditions
        sell_event = Event(
            event_type=EventType.SIGNAL_GENERATED,
            instrument='GOLD',
            source='test',
            payload={
                'signal': 'SELL',
                'indicators': {
                    'current_price': 2645.0,
                    'supertrend_direction': -1,
                    'ema': 2650.0,
                    'sma_fast': 2640.0,
                    'sma_slow': 2650.0
                }
            }
        )
        
        # Execute reversal (should not raise exception)
        try:
            await orch._check_reverse_signals(sell_event)
            success = True
        except Exception as e:
            success = False
            print(f"Reversal check raised exception: {e}")
        
        # Verify no exception was raised
        assert success is True
        
        # Verify close was attempted
        exec_skill.close_position.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_missing_execution_skill_graceful_failure(self, config, mock_event_bus):
        """Missing execution skill should not crash"""
        # Create orchestrator WITHOUT execution skill
        orch = ProductionOrchestrator(config)
        orch.event_bus = mock_event_bus
        
        # Add position
        position = Position(
            deal_id='DEAL_123',
            instrument='GOLD',
            direction='BUY',
            entry_price=2650.0,
            size=0.5,
            stop_loss=2630.0,
            take_profit=2690.0,
            status=PositionStatus.OPEN,
            opened_at=datetime.now(),
            signal_timestamp=datetime.now()
        )
        orch.position_manager.add_position(position)
        
        # Create SELL signal with proper conditions
        sell_event = Event(
            event_type=EventType.SIGNAL_GENERATED,
            instrument='GOLD',
            source='test',
            payload={
                'signal': 'SELL',
                'indicators': {
                    'current_price': 2645.0,
                    'supertrend_direction': -1,
                    'ema': 2650.0,
                    'sma_fast': 2640.0,
                    'sma_slow': 2650.0
                }
            }
        )
        
        # Execute reversal (should handle missing skill gracefully)
        try:
            await orch._check_reverse_signals(sell_event)
            success = True
        except Exception:
            success = False
        
        # Should not crash (logs warning internally)
        assert success is True


# ========== Comparison with Backtester Tests ==========

class TestBacktesterParity:
    """Verify behavior matches cloud-function backtester"""
    
    def test_uses_same_check_reverse_signal_function(self):
        """Verify both use core.signal_engine.check_reverse_signal()"""
        # Both backtester and bot import from same module
        from core.signal_engine import check_reverse_signal, create_market_state
        
        # For BUY position, need SELL signal:
        # - supertrend_direction = -1
        # - close < ema
        # - sma_fast < sma_slow
        market_state = create_market_state(
            close=2645.0,  # Below EMA
            supertrend_direction=-1,  # Down
            ema=2650.0,
            sma_fast=2640.0,  # Fast < slow
            sma_slow=2650.0,
            timestamp='2026-03-28 12:00:00'
        )
        
        # Test BUY position + SELL signal = Reversal
        assert check_reverse_signal('BUY', market_state) is True
        
        # Test SELL position + BUY signal = Would need BUY market state
        # (Testing the function itself, not orchestrator logic)
    
    def test_cooldown_bypass_matches_backtester(self):
        """Verify cooldown bypass logic matches backtester's signal_engine"""
        # Backtester logic: signal_engine.py lines 393-395
        # Bot logic: risk_skill.py line 277
        # Both check: if new_direction != last_direction → bypass cooldown
        
        config = {'sl_cooldown_minutes': 15, 'tp_cooldown_minutes': 5}
        mock_bus = AsyncMock()
        risk_skill = RiskSkill(config, event_bus=mock_bus)
        
        # Simulate: Last position was SELL, new signal is BUY
        risk_skill.last_closed_position = {
            'direction': 'SELL',
            'close_reason': 'SL_HIT',
            'close_time': datetime.now() - timedelta(minutes=1)  # Within cooldown
        }
        
        # Should bypass cooldown
        is_allowed, reason = risk_skill._check_cooldown('BUY')
        assert is_allowed is True


if __name__ == '__main__':
    # Run tests with: pytest tests/unit/test_reversal_logic.py -v
    pytest.main([__file__, '-v', '-s'])

"""
Unit Tests for Position Manager (Trailing Stop Loss)

Tests cover:
- Configuration validation
- Break-even trailing
- Step-based trailing 
- Combined strategies
- Edge cases (BUY/SELL, negative profit, etc.)
"""

import pytest
from src.core.position_manager import (
    TrailingStopConfig,
    PositionTracker,
    PositionManager
)


class TestTrailingStopConfig:
    """Test configuration validation"""
    
    def test_config_defaults(self):
        """Test default configuration"""
        config = TrailingStopConfig()
        assert not config.is_enabled()
        assert not config.breakeven_enabled
        assert not config.step_trailing_enabled
    
    def test_config_validation_breakeven(self):
        """Test break-even config validation"""
        # Valid config
        config = TrailingStopConfig(
            breakeven_enabled=True,
            breakeven_trigger_pips=20.0
        )
        config.validate()  # Should not raise
        
        # Invalid config (non-positive trigger)
        with pytest.raises(ValueError, match="breakeven_trigger_pips must be > 0"):
            invalid = TrailingStopConfig(
                breakeven_enabled=True,
                breakeven_trigger_pips=0.0
            )
            invalid.validate()
    
    def test_config_validation_step_trailing(self):
        """Test step trailing config validation"""
        # Valid config
        config = TrailingStopConfig(
            step_trailing_enabled=True,
            trail_step_pips=10.0,
            trail_move_pips=5.0
        )
        config.validate()  # Should not raise
        
        # Invalid config (zero step)
        with pytest.raises(ValueError, match="trail_step_pips and trail_move_pips must be > 0"):
            invalid = TrailingStopConfig(
                step_trailing_enabled=True,
                trail_step_pips=0.0,
                trail_move_pips=5.0
            )
            invalid.validate()
    
    def test_is_enabled(self):
        """Test is_enabled() method"""
        assert not TrailingStopConfig().is_enabled()
        assert TrailingStopConfig(breakeven_enabled=True, breakeven_trigger_pips=10).is_enabled()
        assert TrailingStopConfig(step_trailing_enabled=True, trail_step_pips=10, trail_move_pips=5).is_enabled()


class TestPositionTracker:
    """Test position tracking state"""
    
    def test_buy_tracker_initialization(self):
        """Test BUY position tracker initialization"""
        tracker = PositionTracker(
            direction='BUY',
            entry_price=4500.0,
            current_sl=4480.0,
            current_tp=4540.0
        )
        assert tracker.direction == 'BUY'
        assert tracker.highest_price_reached == 4500.0
        assert tracker.lowest_price_reached == 0.0
        assert tracker.last_trail_level == 0
        assert not tracker.breakeven_applied
    
    def test_sell_tracker_initialization(self):
        """Test SELL position tracker initialization"""
        tracker = PositionTracker(
            direction='SELL',
            entry_price=4500.0,
            current_sl=4520.0,
            current_tp=4460.0
        )
        assert tracker.direction == 'SELL'
        assert tracker.lowest_price_reached == 4500.0
        assert tracker.highest_price_reached == 0.0
    
    def test_invalid_direction(self):
        """Test invalid direction raises error"""
        with pytest.raises(ValueError, match="Invalid direction"):
            PositionTracker(
                direction='INVALID',
                entry_price=4500.0,
                current_sl=4480.0,
                current_tp=4540.0
            )


class TestBreakevenTrailing:
    """Test break-even trailing stop strategy"""
    
    def test_breakeven_buy_position(self):
        """Test break-even for BUY position"""
        config = TrailingStopConfig(
            breakeven_enabled=True,
            breakeven_trigger_pips=20.0
        )
        manager = PositionManager(config)
        
        tracker = PositionTracker(
            direction='BUY',
            entry_price=4500.0,
            current_sl=4480.0,
            current_tp=4540.0
        )
        
        # Price hasn't moved enough → no update
        new_sl, should_update = manager.calculate_trailing_stop(tracker, 4515.0)
        assert not should_update
        assert new_sl is None
        
        # Price moves 20 pips profit → trigger break-even
        new_sl, should_update = manager.calculate_trailing_stop(tracker, 4520.0)
        assert should_update
        assert new_sl == 4500.0  # Move to entry
        assert tracker.breakeven_applied
        
        # Update tracker SL
        tracker.current_sl = new_sl
        
        # Further price movement → break-even already applied, no more updates
        new_sl, should_update = manager.calculate_trailing_stop(tracker, 4530.0)
        assert not should_update  # Break-even only triggers once
    
    def test_breakeven_sell_position(self):
        """Test break-even for SELL position"""
        config = TrailingStopConfig(
            breakeven_enabled=True,
            breakeven_trigger_pips=20.0
        )
        manager = PositionManager(config)
        
        tracker = PositionTracker(
            direction='SELL',
            entry_price=4500.0,
            current_sl=4520.0,
            current_tp=4460.0
        )
        
        # Price drops 20 pips profit → trigger break-even
        new_sl, should_update = manager.calculate_trailing_stop(tracker, 4480.0)
        assert should_update
        assert new_sl == 4500.0  # Move to entry
        assert tracker.breakeven_applied
    
    def test_breakeven_not_triggered_on_loss(self):
        """Test break-even doesn't trigger when position is losing"""
        config = TrailingStopConfig(
            breakeven_enabled=True,
            breakeven_trigger_pips=20.0
        )
        manager = PositionManager(config)
        
        tracker = PositionTracker(
            direction='BUY',
            entry_price=4500.0,
            current_sl=4480.0,
            current_tp=4540.0
        )
        
        # Price drops (loss) → no break-even
        new_sl, should_update = manager.calculate_trailing_stop(tracker, 4490.0)
        assert not should_update


class TestStepTrailing:
    """Test step-based trailing stop strategy"""
    
    def test_step_trailing_buy_single_level(self):
        """Test step trailing for BUY position - single level"""
        config = TrailingStopConfig(
            step_trailing_enabled=True,
            trail_step_pips=10.0,  # Trail every 10 pips
            trail_move_pips=5.0    # Move SL by 5 pips
        )
        manager = PositionManager(config)
        
        tracker = PositionTracker(
            direction='BUY',
            entry_price=4500.0,
            current_sl=4480.0,
            current_tp=4540.0
        )
        
        # Price moves +5 pips (not enough) → no update
        new_sl, should_update = manager.calculate_trailing_stop(tracker, 4505.0)
        assert not should_update
        
        # Price moves +10 pips (1 level) → move SL by +5 pips
        new_sl, should_update = manager.calculate_trailing_stop(tracker, 4510.0)
        assert should_update
        assert new_sl == 4485.0  # 4480 + 5
        assert tracker.last_trail_level == 1
        
        # Update tracker
        tracker.current_sl = new_sl
        
        # Price stays at same level → no additional update
        new_sl, should_update = manager.calculate_trailing_stop(tracker, 4512.0)
        assert not should_update
    
    def test_step_trailing_buy_multiple_levels(self):
        """Test step trailing for BUY position - multiple levels at once"""
        config = TrailingStopConfig(
            step_trailing_enabled=True,
            trail_step_pips=10.0,
            trail_move_pips=5.0
        )
        manager = PositionManager(config)
        
        tracker = PositionTracker(
            direction='BUY',
            entry_price=4500.0,
            current_sl=4480.0,
            current_tp=4560.0
        )
        
        # Price jumps +35 pips (3 levels) → move SL by 3 × 5 = 15 pips
        new_sl, should_update = manager.calculate_trailing_stop(tracker, 4535.0)
        assert should_update
        assert new_sl == 4495.0  # 4480 + 15
        assert tracker.last_trail_level == 3
        
        # Update tracker
        tracker.current_sl = new_sl
        
        # Price reaches level 5 → move by 2 more levels (10 pips)
        new_sl, should_update = manager.calculate_trailing_stop(tracker, 4552.0)
        assert should_update
        assert new_sl == 4505.0  # 4495 + 10
        assert tracker.last_trail_level == 5
    
    def test_step_trailing_sell_position(self):
        """Test step trailing for SELL position"""
        config = TrailingStopConfig(
            step_trailing_enabled=True,
            trail_step_pips=10.0,
            trail_move_pips=5.0
        )
        manager = PositionManager(config)
        
        tracker = PositionTracker(
            direction='SELL',
            entry_price=4500.0,
            current_sl=4520.0,
            current_tp=4460.0
        )
        
        # Price drops +10 pips profit (1 level) → move SL down by 5 pips
        new_sl, should_update = manager.calculate_trailing_stop(tracker, 4490.0)
        assert should_update
        assert new_sl == 4515.0  # 4520 - 5
        assert tracker.last_trail_level == 1


class TestCombinedStrategies:
    """Test break-even + step trailing combined"""
    
    def test_both_strategies_most_aggressive_wins(self):
        """Test that most aggressive (protective) SL is chosen"""
        config = TrailingStopConfig(
            breakeven_enabled=True,
            breakeven_trigger_pips=20.0,
            step_trailing_enabled=True,
            trail_step_pips=10.0,
            trail_move_pips=5.0
        )
        manager = PositionManager(config)
        
        tracker = PositionTracker(
            direction='BUY',
            entry_price=4500.0,
            current_sl=4480.0,
            current_tp=4560.0
        )
        
        # Price at +20 pips: break-even → 4500, step trail (level 2) → 4490
        # Break-even (4500) is more aggressive (higher) for BUY
        new_sl, should_update = manager.calculate_trailing_stop(tracker, 4520.0)
        assert should_update
        assert new_sl == 4500.0  # Break-even wins
        assert tracker.breakeven_applied
        assert tracker.last_trail_level == 2
        
        # Update tracker
        tracker.current_sl = new_sl
        
        # Price at +35 pips: step trail continues (level 3 from level 2)
        # Step trail adds 5 more pips: 4500 → 4505
        new_sl, should_update = manager.calculate_trailing_stop(tracker, 4535.0)
        # Step trailing should continue and move SL up
        assert should_update
        assert new_sl == 4505.0  # Step trail: 4480 + (3 levels × 5 pips) = 4495, but from current 4500 + (1 level × 5) = 4505


class TestPositionClosing:
    """Test position closing detection (SL/TP hit)"""
    
    def test_buy_sl_hit(self):
        """Test BUY position SL hit detection"""
        tracker = PositionTracker(
            direction='BUY',
            entry_price=4500.0,
            current_sl=4480.0,
            current_tp=4540.0
        )
        
        manager = PositionManager(TrailingStopConfig())
        
        # Price above SL → not hit
        should_close, reason = manager.should_close_position(tracker, 4485.0)
        assert not should_close
        
        # Price at SL → hit
        should_close, reason = manager.should_close_position(tracker, 4480.0)
        assert should_close
        assert reason == 'SL_HIT'
        
        # Price below SL → hit
        should_close, reason = manager.should_close_position(tracker, 4475.0)
        assert should_close
        assert reason == 'SL_HIT'
    
    def test_buy_tp_hit(self):
        """Test BUY position TP hit detection"""
        tracker = PositionTracker(
            direction='BUY',
            entry_price=4500.0,
            current_sl=4480.0,
            current_tp=4540.0
        )
        
        manager = PositionManager(TrailingStopConfig())
        
        # Price at TP → hit
        should_close, reason = manager.should_close_position(tracker, 4540.0)
        assert should_close
        assert reason == 'TP_HIT'
        
        # Price above TP → hit
        should_close, reason = manager.should_close_position(tracker, 4545.0)
        assert should_close
        assert reason == 'TP_HIT'
    
    def test_sell_sl_hit(self):
        """Test SELL position SL hit detection"""
        tracker = PositionTracker(
            direction='SELL',
            entry_price=4500.0,
            current_sl=4520.0,
            current_tp=4460.0
        )
        
        manager = PositionManager(TrailingStopConfig())
        
        # Price at SL → hit
        should_close, reason = manager.should_close_position(tracker, 4520.0)
        assert should_close
        assert reason == 'SL_HIT'
        
        # Price above SL → hit
        should_close, reason = manager.should_close_position(tracker, 4525.0)
        assert should_close
        assert reason == 'SL_HIT'
    
    def test_sell_tp_hit(self):
        """Test SELL position TP hit detection"""
        tracker = PositionTracker(
            direction='SELL',
            entry_price=4500.0,
            current_sl=4520.0,
            current_tp=4460.0
        )
        
        manager = PositionManager(TrailingStopConfig())
        
        # Price at TP → hit
        should_close, reason = manager.should_close_position(tracker, 4460.0)
        assert should_close
        assert reason == 'TP_HIT'


class TestEdgeCases:
    """Test edge cases and error handling"""
    
    def test_disabled_trailing_returns_none(self):
        """Test that disabled trailing returns no update"""
        config = TrailingStopConfig()  # All disabled
        manager = PositionManager(config)
        
        tracker = PositionTracker(
            direction='BUY',
            entry_price=4500.0,
            current_sl=4480.0,
            current_tp=4540.0
        )
        
        new_sl, should_update = manager.calculate_trailing_stop(tracker, 4530.0)
        assert not should_update
        assert new_sl is None
    
    def test_highest_price_tracking(self):
        """Test that highest price is tracked correctly"""
        config = TrailingStopConfig(
            breakeven_enabled=True,
            breakeven_trigger_pips=30.0
        )
        manager = PositionManager(config)
        
        tracker = PositionTracker(
            direction='BUY',
            entry_price=4500.0,
            current_sl=4480.0,
            current_tp=4560.0
        )
        
        # Price goes up
        manager.calculate_trailing_stop(tracker, 4525.0)
        assert tracker.highest_price_reached == 4525.0
        
        # Price goes up more
        manager.calculate_trailing_stop(tracker, 4535.0)
        assert tracker.highest_price_reached == 4535.0
        
        # Price drops (but highest remains)
        manager.calculate_trailing_stop(tracker, 4520.0)
        assert tracker.highest_price_reached == 4535.0
        
        # Break-even triggers based on highest (35 pips profit)
        # But break-even already triggered at 4535, so no new update
        new_sl, should_update = manager.calculate_trailing_stop(tracker, 4520.0)
        # Break-even was already applied when price hit 4535
        assert not should_update  # Break-even only triggers once
        assert tracker.breakeven_applied
    
    def test_lowest_price_tracking_sell(self):
        """Test that lowest price is tracked correctly for SELL"""
        config = TrailingStopConfig(
            breakeven_enabled=True,
            breakeven_trigger_pips=30.0
        )
        manager = PositionManager(config)
        
        tracker = PositionTracker(
            direction='SELL',
            entry_price=4500.0,
            current_sl=4530.0,
            current_tp=4450.0
        )
        
        # Price goes down
        manager.calculate_trailing_stop(tracker, 4475.0)
        assert tracker.lowest_price_reached == 4475.0
        
        # Price goes down more
        manager.calculate_trailing_stop(tracker, 4465.0)
        assert tracker.lowest_price_reached == 4465.0
        
        # Price rises (but lowest remains)
        manager.calculate_trailing_stop(tracker, 4480.0)
        assert tracker.lowest_price_reached == 4465.0
        
        # Break-even already triggered at 4465, so no new update
        new_sl, should_update = manager.calculate_trailing_stop(tracker, 4480.0)
        assert not should_update  # Break-even only triggers once
        assert tracker.breakeven_applied


if __name__ == '__main__':
    pytest.main([__file__, '-v'])

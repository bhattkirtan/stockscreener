#!/usr/bin/env python3
"""
Test the functional signal engine to ensure identical behavior
between backtester and live trading bot.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.signal_engine import (
    MarketState,
    SignalType,
    PositionState,
    ExitReason,
    create_market_state,
    evaluate_signal,
    check_buy_conditions,
    check_sell_conditions,
    check_reverse_signal,
    check_stop_loss,
    check_take_profit,
    check_exit,
    calculate_stop_loss,
    calculate_take_profit,
    check_cooldown,
    get_signal_conditions
)


def test_buy_signal():
    """Test BUY signal generation"""
    print("="*60)
    print("TEST 1: BUY Signal")
    print("="*60)
    
    # Create market state with BUY conditions
    market = create_market_state(
        close=2650.50,
        supertrend_direction=1,  # UP
        ema=2640.00,  # Price > EMA ✓
        sma_fast=2635.00,
        sma_slow=2630.00,  # Fast > Slow ✓
        timestamp="2026-03-26 10:00:00"
    )
    
    signal = evaluate_signal(market)
    conditions = get_signal_conditions(market)
    
    print(f"Market State: {market}")
    print(f"Signal: {signal}")
    print(f"Conditions: {conditions}")
    print(f"✅ BUY signal expected: {signal == SignalType.BUY}")
    assert signal == SignalType.BUY, "BUY signal should be generated"
    print()


def test_sell_signal():
    """Test SELL signal generation"""
    print("="*60)
    print("TEST 2: SELL Signal")
    print("="*60)
    
    # Create market state with SELL conditions
    market = create_market_state(
        close=2640.00,
        supertrend_direction=-1,  # DOWN
        ema=2650.00,  # Price < EMA ✓
        sma_fast=2645.00,
        sma_slow=2650.00,  # Fast < Slow ✓
        timestamp="2026-03-26 11:00:00"
    )
    
    signal = evaluate_signal(market)
    conditions = get_signal_conditions(market)
    
    print(f"Market State: {market}")
    print(f"Signal: {signal}")
    print(f"Conditions: {conditions}")
    print(f"✅ SELL signal expected: {signal == SignalType.SELL}")
    assert signal == SignalType.SELL, "SELL signal should be generated"
    print()


def test_no_signal_st_up_but_price_below_ema():
    """Test NO signal when Supertrend UP but price below EMA"""
    print("="*60)
    print("TEST 3: NO Signal - ST UP but Price < EMA")
    print("="*60)
    
    market = create_market_state(
        close=2630.00,
        supertrend_direction=1,  # UP
        ema=2640.00,  # Price < EMA ❌
        sma_fast=2635.00,
        sma_slow=2630.00,  # Fast > Slow ✓
        timestamp="2026-03-26 12:00:00"
    )
    
    signal = evaluate_signal(market)
    conditions = get_signal_conditions(market)
    
    print(f"Market State: {market}")
    print(f"Signal: {signal}")
    print(f"Conditions: {conditions}")
    print(f"✅ NO signal expected: {signal == SignalType.NONE}")
    assert signal == SignalType.NONE, "No signal should be generated"
    print()


def test_no_signal_st_up_but_sma_bearish():
    """Test NO signal when Supertrend UP but SMAs bearish"""
    print("="*60)
    print("TEST 4: NO Signal - ST UP but Fast SMA < Slow SMA")
    print("="*60)
    
    market = create_market_state(
        close=2650.00,
        supertrend_direction=1,  # UP
        ema=2640.00,  # Price > EMA ✓
        sma_fast=2630.00,
        sma_slow=2635.00,  # Fast < Slow ❌
        timestamp="2026-03-26 13:00:00"
    )
    
    signal = evaluate_signal(market)
    conditions = get_signal_conditions(market)
    
    print(f"Market State: {market}")
    print(f"Signal: {signal}")
    print(f"Conditions: {conditions}")
    print(f"✅ NO signal expected: {signal == SignalType.NONE}")
    assert signal == SignalType.NONE, "No signal should be generated"
    print()


def test_reverse_signal_buy_to_sell():
    """Test reverse signal detection: BUY position should close on SELL signal"""
    print("="*60)
    print("TEST 5: Reverse Signal - BUY to SELL")
    print("="*60)
    
    # Currently holding BUY position
    current_position = 'BUY'
    
    # Market shows SELL signal
    market = create_market_state(
        close=2640.00,
        supertrend_direction=-1,  # DOWN
        ema=2650.00,  # Price < EMA ✓
        sma_fast=2645.00,
        sma_slow=2650.00,  # Fast < Slow ✓
        timestamp="2026-03-26 14:00:00"
    )
    
    should_close = check_reverse_signal(current_position, market)
    signal = evaluate_signal(market)
    
    print(f"Current Position: {current_position}")
    print(f"Market State: {market}")
    print(f"Current Signal: {signal}")
    print(f"Should Close: {should_close}")
    print(f"✅ Reverse signal expected: {should_close}")
    assert should_close == True, "BUY position should close on SELL signal"
    print()


def test_no_reverse_signal_buy_stays_buy():
    """Test NO reverse signal: BUY position stays when BUY conditions persist"""
    print("="*60)
    print("TEST 6: NO Reverse Signal - BUY stays BUY")
    print("="*60)
    
    current_position = 'BUY'
    
    # Market still shows BUY conditions
    market = create_market_state(
        close=2650.00,
        supertrend_direction=1,  # UP
        ema=2640.00,  # Price > EMA ✓
        sma_fast=2645.00,
        sma_slow=2640.00,  # Fast > Slow ✓
        timestamp="2026-03-26 15:00:00"
    )
    
    should_close = check_reverse_signal(current_position, market)
    signal = evaluate_signal(market)
    
    print(f"Current Position: {current_position}")
    print(f"Market State: {market}")
    print(f"Current Signal: {signal}")
    print(f"Should Close: {should_close}")
    print(f"✅ NO reverse signal expected: {not should_close}")
    assert should_close == False, "BUY position should NOT close on BUY signal"
    print()


def test_immutability():
    """Test that MarketState is truly immutable"""
    print("="*60)
    print("TEST 7: Immutability Check")
    print("="*60)
    
    market = create_market_state(
        close=2650.00,
        supertrend_direction=1,
        ema=2640.00,
        sma_fast=2645.00,
        sma_slow=2640.00
    )
    
    print(f"Original Market State: {market}")
    
    # Try to modify (should raise error)
    try:
        market.close = 2700.00
        print("❌ ERROR: MarketState is mutable!")
        assert False, "MarketState should be immutable"
    except AttributeError as e:
        print(f"✅ Immutability enforced: {e}")
    print()


def test_stop_loss_long():
    """Test stop loss for LONG position"""
    print("="*60)
    print("TEST 8: Stop Loss - LONG Position")
    print("="*60)
    
    # Create LONG position with SL at 2640
    position = PositionState(
        side='BUY',
        entry_price=2650.00,
        stop_loss=2640.00,
        take_profit=2665.00,
        entry_time="2026-03-26 10:00:00"
    )
    
    # Price drops to SL level
    current_price = 2639.50
    
    sl_hit = check_stop_loss(position, current_price)
    print(f"Position: {position.side} @ {position.entry_price}")
    print(f"Stop Loss: {position.stop_loss}")
    print(f"Current Price: {current_price}")
    print(f"SL Hit: {sl_hit}")
    print(f"✅ Stop loss triggered: {sl_hit}")
    
    assert sl_hit == True, "LONG stop loss should trigger when price <= SL"
    print()


def test_take_profit_long():
    """Test take profit for LONG position"""
    print("="*60)
    print("TEST 9: Take Profit - LONG Position")
    print("="*60)
    
    # Create LONG position with TP at 2665
    position = PositionState(
        side='BUY',
        entry_price=2650.00,
        stop_loss=2640.00,
        take_profit=2665.00,
        entry_time="2026-03-26 10:00:00"
    )
    
    # Price rises to TP level
    current_price = 2665.50
    
    tp_hit = check_take_profit(position, current_price)
    print(f"Position: {position.side} @ {position.entry_price}")
    print(f"Take Profit: {position.take_profit}")
    print(f"Current Price: {current_price}")
    print(f"TP Hit: {tp_hit}")
    print(f"✅ Take profit triggered: {tp_hit}")
    
    assert tp_hit == True, "LONG take profit should trigger when price >= TP"
    print()


def test_stop_loss_short():
    """Test stop loss for SHORT position"""
    print("="*60)
    print("TEST 10: Stop Loss - SHORT Position")
    print("="*60)
    
    # Create SHORT position with SL at 2660
    position = PositionState(
        side='SELL',
        entry_price=2650.00,
        stop_loss=2660.00,  # SL above entry for SHORT
        take_profit=2635.00,  # TP below entry for SHORT
        entry_time="2026-03-26 10:00:00"
    )
    
    # Price rises to SL level
    current_price = 2660.50
    
    sl_hit = check_stop_loss(position, current_price)
    print(f"Position: {position.side} @ {position.entry_price}")
    print(f"Stop Loss: {position.stop_loss}")
    print(f"Current Price: {current_price}")
    print(f"SL Hit: {sl_hit}")
    print(f"✅ Stop loss triggered: {sl_hit}")
    
    assert sl_hit == True, "SHORT stop loss should trigger when price >= SL"
    print()


def test_take_profit_short():
    """Test take profit for SHORT position"""
    print("="*60)
    print("TEST 11: Take Profit - SHORT Position")
    print("="*60)
    
    # Create SHORT position with TP at 2635
    position = PositionState(
        side='SELL',
        entry_price=2650.00,
        stop_loss=2660.00,
        take_profit=2635.00,
        entry_time="2026-03-26 10:00:00"
    )
    
    # Price drops to TP level
    current_price = 2634.50
    
    tp_hit = check_take_profit(position, current_price)
    print(f"Position: {position.side} @ {position.entry_price}")
    print(f"Take Profit: {position.take_profit}")
    print(f"Current Price: {current_price}")
    print(f"TP Hit: {tp_hit}")
    print(f"✅ Take profit triggered: {tp_hit}")
    
    assert tp_hit == True, "SHORT take profit should trigger when price <= TP"
    print()


def test_exit_priority():
    """Test exit priority: SL > TP > Reverse Signal"""
    print("="*60)
    print("TEST 12: Exit Priority Order")
    print("="*60)
    
    # Create LONG position
    position = PositionState(
        side='BUY',
        entry_price=2650.00,
        stop_loss=2640.00,
        take_profit=2665.00,
        entry_time="2026-03-26 10:00:00"
    )
    
    # Case 1: SL hit (highest priority)
    print("\nCase 1: SL Hit (highest priority)")
    current_price = 2639.00
    market = create_market_state(
        close=current_price,
        supertrend_direction=-1,  # Reverse signal present
        ema=2640.00,
        sma_fast=2630.00,
        sma_slow=2635.00,
        timestamp="2026-03-26 10:05:00"
    )
    
    should_exit, reason = check_exit(position, current_price, market)
    print(f"Price: {current_price} (SL={position.stop_loss}, TP={position.take_profit})")
    print(f"Exit: {should_exit}, Reason: {reason}")
    assert should_exit == True and reason == ExitReason.STOP_LOSS, "SL should have highest priority"
    print("✅ Stop Loss priority correct")
    
    # Case 2: TP hit (second priority)
    print("\nCase 2: TP Hit (second priority)")
    current_price = 2666.00
    market = create_market_state(
        close=current_price,
        supertrend_direction=-1,  # Reverse signal present
        ema=2640.00,
        sma_fast=2630.00,
        sma_slow=2635.00,
        timestamp="2026-03-26 10:10:00"
    )
    
    should_exit, reason = check_exit(position, current_price, market)
    print(f"Price: {current_price} (SL={position.stop_loss}, TP={position.take_profit})")
    print(f"Exit: {should_exit}, Reason: {reason}")
    assert should_exit == True and reason == ExitReason.TAKE_PROFIT, "TP should have second priority"
    print("✅ Take Profit priority correct")
    
    # Case 3: Reverse signal only (third priority)
    print("\nCase 3: Reverse Signal (third priority)")
    current_price = 2655.00  # Normal price, no SL/TP
    market = create_market_state(
        close=current_price,
        supertrend_direction=-1,  # DOWN
        ema=2658.00,  # Price < EMA
        sma_fast=2630.00,
        sma_slow=2635.00,  # Fast < Slow (bearish)
        timestamp="2026-03-26 10:15:00"
    )
    
    should_exit, reason = check_exit(position, current_price, market)
    print(f"Price: {current_price} (no SL/TP hit)")
    print(f"Exit: {should_exit}, Reason: {reason}")
    assert should_exit == True and reason == ExitReason.REVERSE_SIGNAL, "Reverse signal should be third priority"
    print("✅ Reverse Signal priority correct")
    
    # Case 4: No exit
    print("\nCase 4: No Exit Condition")
    current_price = 2655.00
    market = create_market_state(
        close=current_price,
        supertrend_direction=1,  # UP (same as position)
        ema=2640.00,  # Price > EMA
        sma_fast=2635.00,
        sma_slow=2630.00,  # Fast > Slow (bullish)
        timestamp="2026-03-26 10:20:00"
    )
    
    should_exit, reason = check_exit(position, current_price, market)
    print(f"Price: {current_price} (position in profit, no exit signal)")
    print(f"Exit: {should_exit}, Reason: {reason}")
    assert should_exit == False and reason == ExitReason.NONE, "Should not exit"
    print("✅ No exit when conditions not met")
    print()


def test_calculate_sl_tp():
    """Test TP/SL calculation logic"""
    print("="*60)
    print("TEST 13: Calculate Stop Loss & Take Profit")
    print("="*60)
    
    entry_price = 2650.00
    sl_pips = 20
    tp_pips = 40
    
    # BUY position
    print("\nBUY Position:")
    buy_sl = calculate_stop_loss(entry_price, 'BUY', sl_pips, pip_value=1.0)
    buy_tp = calculate_take_profit(entry_price, 'BUY', tp_pips, pip_value=1.0)
    print(f"  Entry: {entry_price}")
    print(f"  SL: {buy_sl} (should be {entry_price - 20})")
    print(f"  TP: {buy_tp} (should be {entry_price + 40})")
    assert buy_sl == 2630.00, "BUY SL should be entry - 20"
    assert buy_tp == 2690.00, "BUY TP should be entry + 40"
    print("  ✅ BUY SL/TP correct")
    
    # SELL position
    print("\nSELL Position:")
    sell_sl = calculate_stop_loss(entry_price, 'SELL', sl_pips, pip_value=1.0)
    sell_tp = calculate_take_profit(entry_price, 'SELL', tp_pips, pip_value=1.0)
    print(f"  Entry: {entry_price}")
    print(f"  SL: {sell_sl} (should be {entry_price + 20})")
    print(f"  TP: {sell_tp} (should be {entry_price - 40})")
    assert sell_sl == 2670.00, "SELL SL should be entry + 20"
    assert sell_tp == 2610.00, "SELL TP should be entry - 40"
    print("  ✅ SELL SL/TP correct")
    print()


def test_cooldown_same_direction():
    """Test cooldown prevents same direction re-entry"""
    print("="*60)
    print("TEST 14: Cooldown - Same Direction Block")
    print("="*60)
    
    # SL hit 10 minutes ago, trying to re-enter BUY
    print("\nCase 1: SL hit 10min ago, re-entering same direction (BUY)")
    is_blocked, msg = check_cooldown(
        last_exit_time="2026-03-26 10:00:00",
        last_exit_reason="SL_HIT",
        current_signal=SignalType.BUY,
        last_position_side='BUY',
        minutes_since_exit=10.0,
        sl_cooldown_minutes=15,
        tp_cooldown_minutes=5
    )
    print(f"  Blocked: {is_blocked}")
    print(f"  Message: {msg}")
    assert is_blocked == True, "Should block same direction after SL"
    assert "15m" in msg, "Should mention 15m cooldown"
    print("  ✅ SL cooldown blocks re-entry")
    
    # TP hit 3 minutes ago, trying to re-enter SELL
    print("\nCase 2: TP hit 3min ago, re-entering same direction (SELL)")
    is_blocked, msg = check_cooldown(
        last_exit_time="2026-03-26 10:00:00",
        last_exit_reason="TP_HIT",
        current_signal=SignalType.SELL,
        last_position_side='SELL',
        minutes_since_exit=3.0,
        sl_cooldown_minutes=15,
        tp_cooldown_minutes=5
    )
    print(f"  Blocked: {is_blocked}")
    print(f"  Message: {msg}")
    assert is_blocked == True, "Should block same direction after TP"
    assert "5m" in msg, "Should mention 5m cooldown"
    print("  ✅ TP cooldown blocks re-entry")
    print()


def test_cooldown_reverse_signal():
    """Test cooldown allows reverse signals immediately"""
    print("="*60)
    print("TEST 15: Cooldown - Reverse Signal Allowed")
    print("="*60)
    
    # SL hit 5 minutes ago, but reverse signal (BUY → SELL)
    print("\nCase: SL hit 5min ago, but entering opposite direction (BUY→SELL)")
    is_blocked, msg = check_cooldown(
        last_exit_time="2026-03-26 10:00:00",
        last_exit_reason="SL_HIT",
        current_signal=SignalType.SELL,  # Opposite to last position
        last_position_side='BUY',  # Last was BUY
        minutes_since_exit=5.0,
        sl_cooldown_minutes=15,
        tp_cooldown_minutes=5
    )
    print(f"  Blocked: {is_blocked}")
    print(f"  Message: {msg}")
    assert is_blocked == False, "Reverse signals should bypass cooldown"
    assert "Reverse" in msg or msg == "", "Should indicate reverse signal"
    print("  ✅ Reverse signal bypasses cooldown")
    print()


def test_cooldown_expired():
    """Test cooldown allows re-entry after time passes"""
    print("="*60)
    print("TEST 16: Cooldown - Expired Period")
    print("="*60)
    
    # SL hit 20 minutes ago (> 15m cooldown)
    print("\nCase: SL hit 20min ago (cooldown expired)")
    is_blocked, msg = check_cooldown(
        last_exit_time="2026-03-26 10:00:00",
        last_exit_reason="SL_HIT",
        current_signal=SignalType.BUY,
        last_position_side='BUY',
        minutes_since_exit=20.0,
        sl_cooldown_minutes=15,
        tp_cooldown_minutes=5
    )
    print(f"  Blocked: {is_blocked}")
    print(f"  Message: {msg}")
    assert is_blocked == False, "Should allow re-entry after cooldown expires"
    print("  ✅ Cooldown expired, re-entry allowed")
    print()


if __name__ == "__main__":
    print("\n" + "="*60)
    print("FUNCTIONAL SIGNAL ENGINE TESTS")
    print("="*60 + "\n")
    
    # Entry signal tests
    test_buy_signal()
    test_sell_signal()
    test_no_signal_st_up_but_price_below_ema()
    test_no_signal_st_up_but_sma_bearish()
    
    # Reverse signal tests
    test_reverse_signal_buy_to_sell()
    test_no_reverse_signal_buy_stays_buy()
    
    # Data structure tests
    test_immutability()
    
    # Exit logic tests
    test_stop_loss_long()
    test_take_profit_long()
    test_stop_loss_short()
    test_take_profit_short()
    test_exit_priority()
    
    # Position management tests
    test_calculate_sl_tp()
    test_cooldown_same_direction()
    test_cooldown_reverse_signal()
    test_cooldown_expired()
    
    print("="*60)
    print("✅ ALL 16 TESTS PASSED!")
    print("="*60)
    print("\nThe functional signal engine ensures:")
    print("  1. Pure functions with no side effects")
    print("  2. Immutable data structures")
    print("  3. Identical logic between backtester and live bot")
    print("  4. Complete exit logic: SL > TP > Reverse Signal")
    print("  5. Position management: SL/TP calculation + cooldown")
    print("  6. Golden/Death cross support for enhanced entry signals")
    print("  7. Testable and composable functions")


def test_golden_cross_signal():
    """Test BUY signal with golden cross (fast SMA crosses above slow)"""
    print("\n" + "="*60)
    print("TEST 17: Golden Cross - Signal with Cross")
    print("="*60)
    
    # ST UP, price > EMA, fast just crossed above slow
    market = create_market_state(
        close=2650.0,
        supertrend_direction=1,
        ema=2640.0,
        sma_fast=2642.0,  # Just crossed above slow
        sma_slow=2641.0,
        timestamp="2026-03-26 10:00:00"
    )
    
    # Without golden_cross: still signals (fast > slow)
    signal_without = evaluate_signal(market, golden_cross=False)
    # With golden_cross: should also signal
    signal_with = evaluate_signal(market, golden_cross=True)
    
    print(f"Market: ST={market.supertrend_direction}, Price={market.close}, EMA={market.ema}")
    print(f"        Fast SMA={market.sma_fast}, Slow SMA={market.sma_slow}")
    print(f"Signal without golden_cross: {signal_without}")
    print(f"Signal with golden_cross: {signal_with}")
    assert signal_with == SignalType.BUY, "Golden cross should trigger BUY"
    print("✅ Golden cross triggers BUY signal\n")


def test_death_cross_signal():
    """Test SELL signal with death cross (fast SMA crosses below slow)"""
    print("="*60)
    print("TEST 18: Death Cross - Signal with Cross")
    print("="*60)
    
    # ST DOWN, price < EMA, fast just crossed below slow
    market = create_market_state(
        close=2640.0,
        supertrend_direction=-1,
        ema=2650.0,
        sma_fast=2648.0,  # Just crossed below slow
        sma_slow=2649.0,
        timestamp="2026-03-26 11:00:00"
    )
    
    # Without death_cross: still signals (fast < slow)
    signal_without = evaluate_signal(market, death_cross=False)
    # With death_cross: should also signal
    signal_with = evaluate_signal(market, death_cross=True)
    
    print(f"Market: ST={market.supertrend_direction}, Price={market.close}, EMA={market.ema}")
    print(f"        Fast SMA={market.sma_fast}, Slow SMA={market.sma_slow}")
    print(f"Signal without death_cross: {signal_without}")
    print(f"Signal with death_cross: {signal_with}")
    assert signal_with == SignalType.SELL, "Death cross should trigger SELL"
    print("✅ Death cross triggers SELL signal\n")


if __name__ == "__main__":
    print("\n" + "="*60)
    print("FUNCTIONAL SIGNAL ENGINE TESTS")
    print("="*60 + "\n")
    
    # Entry signal tests
    test_buy_signal()
    test_sell_signal()
    test_no_signal_st_up_but_price_below_ema()
    test_no_signal_st_up_but_sma_bearish()
    
    # Reverse signal tests
    test_reverse_signal_buy_to_sell()
    test_no_reverse_signal_buy_stays_buy()
    
    # Data structure tests
    test_immutability()
    
    # Exit logic tests
    test_stop_loss_long()
    test_take_profit_long()
    test_stop_loss_short()
    test_take_profit_short()
    test_exit_priority()
    
    # Position management tests
    test_calculate_sl_tp()
    test_cooldown_same_direction()
    test_cooldown_reverse_signal()
    test_cooldown_expired()
    
    # Crossover tests
    test_golden_cross_signal()
    test_death_cross_signal()
    
    print("="*60)
    print("✅ ALL 18 TESTS PASSED!")
    print("="*60)
    print("\nThe functional signal engine ensures:")
    print("  1. Pure functions with no side effects")
    print("  2. Immutable data structures")
    print("  3. Identical logic between backtester and live bot")
    print("  4. Complete exit logic: SL > TP > Reverse Signal")
    print("  5. Position management: SL/TP calculation + cooldown")
    print("  6. Golden/Death cross support for enhanced entry signals")
    print("  7. Testable and composable functions")

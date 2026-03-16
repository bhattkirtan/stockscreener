"""Demo script for zone-based strategy.

This script demonstrates how to use the zone-based strategy with sample data.
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import sys
sys.path.append('/Users/kirtanbhatt/code/stockScreener/cloud-function')

from src.strategies.zone_strategy import ZoneStrategy, TradeSetup


def generate_sample_ohlc(timeframe: str, bars: int = 200) -> pd.DataFrame:
    """Generate sample OHLC data for testing.
    
    Args:
        timeframe: Timeframe (H4, H1, M15, M5)
        bars: Number of bars to generate
        
    Returns:
        OHLC dataframe
    """
    # Gold price around 2650
    base_price = 2650.0
    
    # Different volatility for different timeframes
    volatility = {
        'H4': 15.0,
        'H1': 8.0,
        'M15': 3.0,
        'M5': 1.5
    }.get(timeframe, 5.0)
    
    # Generate timestamps
    minutes_map = {'H4': 240, 'H1': 60, 'M15': 15, 'M5': 5}
    minutes = minutes_map.get(timeframe, 60)
    
    start_time = datetime.now() - timedelta(minutes=minutes * bars)
    timestamps = [start_time + timedelta(minutes=minutes * i) for i in range(bars)]
    
    # Generate price data with trend
    np.random.seed(42)
    trend = np.linspace(0, 20, bars)  # Uptrend
    
    closes = []
    opens = []
    highs = []
    lows = []
    
    current_price = base_price
    
    for i in range(bars):
        # Random walk with trend
        change = np.random.randn() * volatility + trend[i] / bars * volatility
        current_price += change
        
        open_price = current_price
        close_price = current_price + np.random.randn() * volatility * 0.5
        
        high_price = max(open_price, close_price) + abs(np.random.randn()) * volatility * 0.3
        low_price = min(open_price, close_price) - abs(np.random.randn()) * volatility * 0.3
        
        opens.append(open_price)
        closes.append(close_price)
        highs.append(high_price)
        lows.append(low_price)
        
        current_price = close_price
    
    return pd.DataFrame({
        'timestamp': timestamps,
        'open': opens,
        'high': highs,
        'low': lows,
        'close': closes
    })


def demo_zone_strategy():
    """Demonstrate zone strategy usage."""
    
    print("=" * 70)
    print("ZONE-BASED STRATEGY DEMO")
    print("=" * 70)
    print()
    
    # Initialize strategy
    print("1. Initializing strategy for GOLD...")
    strategy = ZoneStrategy(symbol="GOLD")
    print(f"   ✓ Strategy initialized")
    print(f"   ✓ Risk per trade: {strategy.config['risk_per_idea_pct'] * 100:.2f}%")
    print(f"   ✓ Min R:R ratio: {strategy.config['min_rr_for_trade']:.1f}")
    print(f"   ✓ Min trade score: {strategy.config['min_trade_score']}")
    print()
    
    # Generate sample data
    print("2. Generating sample multi-timeframe data...")
    df_dict = {
        'H4': generate_sample_ohlc('H4', 200),
        'H1': generate_sample_ohlc('H1', 400),
        'M15': generate_sample_ohlc('M15', 800),
        'M5': generate_sample_ohlc('M5', 2000)
    }
    
    for tf, df in df_dict.items():
        print(f"   ✓ {tf}: {len(df)} bars ({df.iloc[0]['timestamp']} to {df.iloc[-1]['timestamp']})")
    print()
    
    # Update zones
    print("3. Detecting zones on multiple timeframes...")
    strategy.update_zones(df_dict)
    
    for tf in ['H4', 'H1', 'M15']:
        zones = strategy.current_zones.get(tf, [])
        print(f"   ✓ {tf}: {len(zones)} zones detected")
        
        # Show top 3 zones
        if zones:
            scored_zones = strategy.zone_scorer.rank_zones(zones, df_dict)
            for i, (zone, score) in enumerate(scored_zones[:3], 1):
                print(f"      {i}. {zone.type.value.upper():10} @ {zone.midpoint:.2f} "
                      f"(score: {score:.1f}, state: {zone.state.value})")
    print()
    
    # Calculate bias
    print("4. Calculating directional bias...")
    h4_ema = strategy.bias_model.get_ema_values(df_dict['H4'], 'H4')
    h1_ema = strategy.bias_model.get_ema_values(df_dict['H1'], 'H1')
    
    print(f"   H4: Fast EMA = {h4_ema['fast']:.2f}, Slow EMA = {h4_ema['slow']:.2f}")
    print(f"   H1: Fast EMA = {h1_ema['fast']:.2f}, Slow EMA = {h1_ema['slow']:.2f}")
    print(f"   ✓ Bias: {strategy.current_bias.value.upper()}")
    
    bias_strength = strategy.bias_model.calculate_bias_strength(df_dict['H4'], df_dict['H1'])
    print(f"   ✓ Bias strength: {bias_strength:.2%}")
    print()
    
    # Evaluate setup
    print("5. Evaluating current trade setup...")
    current_price = df_dict['M5'].iloc[-1]['close']
    spread = 0.3  # 0.3 pips for gold
    equity = 10000.0  # $10,000 account
    
    print(f"   Current price: ${current_price:.2f}")
    print(f"   Spread: {spread} pips")
    print(f"   Account equity: ${equity:,.2f}")
    print()
    
    setup = strategy.evaluate_setup(
        df_dict=df_dict,
        current_price=current_price,
        spread=spread,
        equity=equity,
        is_news_blocked=False
    )
    
    if setup:
        print("   ✅ VALID SETUP FOUND!")
        print(f"   Direction: {setup.direction.upper()}")
        print(f"   Entry: ${setup.entry_price:.2f}")
        print(f"   Stop Loss: ${setup.stop_loss:.2f}")
        print(f"   Take Profit 1: ${setup.take_profit_1:.2f}")
        if setup.take_profit_2:
            print(f"   Take Profit 2: ${setup.take_profit_2:.2f}")
        print(f"   Risk: ${setup.risk_amount:.2f}")
        print(f"   Position Size: {setup.position_size:.2f} lots")
        print(f"   Setup Score: {setup.score:.1f}/100")
        print(f"   R:R Ratio: {setup.room_to_target:.2f}")
        print(f"   Zone: {setup.zone.type.value} @ ${setup.zone.midpoint:.2f} ({setup.zone.timeframe})")
        print(f"   Trigger: {setup.trigger.value}")
        print(f"   Bias: {setup.bias.value}")
        
        # Calculate potential profit/loss
        stop_distance = abs(setup.entry_price - setup.stop_loss)
        tp1_distance = abs(setup.take_profit_1 - setup.entry_price)
        
        potential_loss = stop_distance * setup.position_size
        potential_profit = tp1_distance * setup.position_size
        
        print()
        print(f"   Potential Loss: ${potential_loss:.2f} ({potential_loss / equity * 100:.2f}%)")
        print(f"   Potential Profit (TP1): ${potential_profit:.2f} ({potential_profit / equity * 100:.2f}%)")
    else:
        print("   ❌ No valid setup found")
        print("   Possible reasons:")
        print("   - No clear trigger on M5")
        print("   - Insufficient room to target")
        print("   - Setup score below threshold")
        print("   - Strong opposing zone blocking entry")
    
    print()
    print("=" * 70)
    print("DEMO COMPLETE")
    print("=" * 70)
    print()
    print("Next steps:")
    print("1. Integrate with your data provider for real market data")
    print("2. Add economic calendar for news blocking")
    print("3. Implement session detection for session quality filtering")
    print("4. Run backtests using the backtester framework")
    print("5. Optimize parameters using walk-forward analysis")
    print()


def demo_zone_cluster_detection():
    """Demonstrate zone cluster detection."""
    
    print("\n" + "=" * 70)
    print("ZONE CLUSTER DETECTION DEMO")
    print("=" * 70)
    print()
    
    strategy = ZoneStrategy(symbol="GOLD")
    
    # Generate data
    df_dict = {
        'H4': generate_sample_ohlc('H4', 200),
        'H1': generate_sample_ohlc('H1', 400),
        'M15': generate_sample_ohlc('M15', 800),
        'M5': generate_sample_ohlc('M5', 2000)
    }
    
    strategy.update_zones(df_dict)
    
    current_price = df_dict['M5'].iloc[-1]['close']
    
    print(f"Current price: ${current_price:.2f}")
    print()
    
    # Find zone clusters
    clusters = strategy.zone_engine.get_zone_clusters(current_price, max_distance=50.0)
    
    print(f"Found {len(clusters)} zone clusters within 50 points")
    print()
    
    for i, cluster in enumerate(clusters, 1):
        print(f"Cluster {i}: {len(cluster)} zones")
        
        # Calculate cluster score
        cluster_score = strategy.zone_scorer.score_cluster(cluster, df_dict)
        print(f"  Cluster score: {cluster_score:.1f}")
        
        for zone in cluster:
            print(f"  - {zone.timeframe} {zone.type.value:10} @ {zone.midpoint:.2f} "
                  f"(strength: {zone.strength_score:.1f})")
        print()


if __name__ == "__main__":
    # Run demos
    demo_zone_strategy()
    demo_zone_cluster_detection()
    
    print("\n✅ All demos complete!")
    print()
    print("To use this strategy in production:")
    print("1. Review zone_strategy_config.yaml for configuration options")
    print("2. Integrate with your broker's data feed")
    print("3. Implement position management and order execution")
    print("4. Add comprehensive logging and monitoring")
    print("5. Start with paper trading before going live")
    print()

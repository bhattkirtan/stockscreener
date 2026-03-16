"""
Example: Zone-Based Strategy with External Data Feeds

Demonstrates complete integration of:
- Zone engine (H4/H1/M15 zones)
- Bias engine (EMA crossovers)
- Trigger engine (M5 patterns)
- Trade scorer (0-100 scoring)
- External data manager (calendar + macro + news)
- Event blocker (scheduled + unscheduled blocking)

Reference: strategy.md Sections 6-17
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import logging

# Core strategy components
from src.core.zone_based_strategy import ZoneBasedIntradayStrategy
from src.data.external_data_manager import ExternalDataManager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def load_sample_data():
    """
    Load sample OHLC data for multiple timeframes
    
    In production, this would fetch from Capital.com API
    """
    # Generate sample data (replace with real data in production)
    end_date = datetime.utcnow()
    
    # H4: 500 bars = ~83 days
    dates_h4 = pd.date_range(end=end_date, periods=500, freq='4H')
    df_h4 = pd.DataFrame({
        'open': 2000 + np.random.randn(500).cumsum(),
        'high': 2002 + np.random.randn(500).cumsum(),
        'low': 1998 + np.random.randn(500).cumsum(),
        'close': 2000 + np.random.randn(500).cumsum(),
        'volume': np.random.randint(1000, 5000, 500)
    }, index=dates_h4)
    
    # Ensure high/low are correct
    df_h4['high'] = df_h4[['open', 'close']].max(axis=1) + abs(np.random.randn(500))
    df_h4['low'] = df_h4[['open', 'close']].min(axis=1) - abs(np.random.randn(500))
    
    # H1: 2000 bars = ~83 days
    dates_h1 = pd.date_range(end=end_date, periods=2000, freq='1H')
    df_h1 = pd.DataFrame({
        'open': 2000 + np.random.randn(2000).cumsum() * 0.5,
        'high': 2002 + np.random.randn(2000).cumsum() * 0.5,
        'low': 1998 + np.random.randn(2000).cumsum() * 0.5,
        'close': 2000 + np.random.randn(2000).cumsum() * 0.5,
        'volume': np.random.randint(500, 2000, 2000)
    }, index=dates_h1)
    
    df_h1['high'] = df_h1[['open', 'close']].max(axis=1) + abs(np.random.randn(2000) * 0.5)
    df_h1['low'] = df_h1[['open', 'close']].min(axis=1) - abs(np.random.randn(2000) * 0.5)
    
    # M15: 8000 bars = ~83 days
    dates_m15 = pd.date_range(end=end_date, periods=8000, freq='15T')
    df_m15 = pd.DataFrame({
        'open': 2000 + np.random.randn(8000).cumsum() * 0.25,
        'high': 2002 + np.random.randn(8000).cumsum() * 0.25,
        'low': 1998 + np.random.randn(8000).cumsum() * 0.25,
        'close': 2000 + np.random.randn(8000).cumsum() * 0.25,
        'volume': np.random.randint(100, 500, 8000)
    }, index=dates_m15)
    
    df_m15['high'] = df_m15[['open', 'close']].max(axis=1) + abs(np.random.randn(8000) * 0.25)
    df_m15['low'] = df_m15[['open', 'close']].min(axis=1) - abs(np.random.randn(8000) * 0.25)
    
    # M5: 24000 bars = ~83 days
    dates_m5 = pd.date_range(end=end_date, periods=24000, freq='5T')
    df_m5 = pd.DataFrame({
        'open': 2000 + np.random.randn(24000).cumsum() * 0.1,
        'high': 2002 + np.random.randn(24000).cumsum() * 0.1,
        'low': 1998 + np.random.randn(24000).cumsum() * 0.1,
        'close': 2000 + np.random.randn(24000).cumsum() * 0.1,
        'volume': np.random.randint(50, 200, 24000)
    }, index=dates_m5)
    
    df_m5['high'] = df_m5[['open', 'close']].max(axis=1) + abs(np.random.randn(24000) * 0.1)
    df_m5['low'] = df_m5[['open', 'close']].min(axis=1) - abs(np.random.randn(24000) * 0.1)
    
    return df_h4, df_h1, df_m15, df_m5


def example_with_external_data():
    """
    Example: Complete strategy with external data feeds
    """
    logger.info("="*70)
    logger.info("Zone-Based Strategy with External Data Feeds - Example")
    logger.info("="*70)
    
    # 1. Initialize external data manager
    logger.info("\n1. Initializing External Data Manager...")
    
    # Note: In production, provide real API keys
    external_data = ExternalDataManager(
        trading_econ_api_key=None,  # Your Trading Economics key
        fred_api_key=None,           # Your FRED key
        news_api_key=None,           # Your NewsAPI key
        enable_calendar=False,       # Enable with real key
        enable_macro=False,          # Enable with real key
        enable_news=False            # Enable with real key
    )
    
    logger.info("✓ External data manager initialized")
    
    # 2. Initialize zone-based strategy
    logger.info("\n2. Initializing Zone-Based Strategy...")
    
    strategy = ZoneBasedIntradayStrategy(
        zone_width_multipliers={'H4': 0.35, 'H1': 0.25, 'M15': 0.18},
        strong_zone_threshold=4.0,
        min_passing_score=70,
        min_risk_reward=2.0,
        risk_per_trade_pct=0.01
    )
    
    logger.info("✓ Strategy initialized")
    
    # 3. Load sample data
    logger.info("\n3. Loading sample data...")
    df_h4, df_h1, df_m15, df_m5 = load_sample_data()
    
    logger.info(f"✓ Data loaded:")
    logger.info(f"   H4:  {len(df_h4)} bars")
    logger.info(f"   H1:  {len(df_h1)} bars")
    logger.info(f"   M15: {len(df_m15)} bars")
    logger.info(f"   M5:  {len(df_m5)} bars")
    
    # 4. Get external data context
    logger.info("\n4. Fetching external data context...")
    
    current_time = df_m5.index[-1]
    current_atr = 1.5  # Sample ATR
    avg_atr = 1.2      # Sample average ATR
    
    ext_context = external_data.get_external_data_context(
        current_time=current_time,
        current_atr=current_atr,
        normal_atr=avg_atr
    )
    
    logger.info(f"✓ External data context:")
    logger.info(f"   Macro regime: {ext_context.macro_regime.value}")
    logger.info(f"   Position multiplier: {ext_context.position_size_multiplier:.2f}x")
    logger.info(f"   Trading blocked: {ext_context.is_blocked}")
    if ext_context.is_blocked:
        logger.info(f"   Block reason: {ext_context.block_reason}")
    
    # 5. Generate trading signal
    logger.info("\n5. Generating trading signal...")
    
    if ext_context.is_blocked:
        logger.warning("⚠️  Trading blocked by external data - skipping signal")
        return
    
    signal = strategy.generate_signal(
        df_h4=df_h4,
        df_h1=df_h1,
        df_m15=df_m15,
        df_m5=df_m5,
        current_atr=current_atr,
        avg_atr=avg_atr,
        spread=0.50,  # $0.50 spread for Gold
        account_balance=10000.0,
        minutes_to_event=ext_context.minutes_to_next_event
    )
    
    if signal is None:
        logger.info("✗ No valid signal generated")
        return
    
    # 6. Display signal details
    logger.info(f"\n6. Signal Generated:")
    logger.info(f"   Direction: {signal.direction.upper()}")
    logger.info(f"   Entry: ${signal.entry_price:.2f}")
    logger.info(f"   Stop: ${signal.stop_price:.2f}")
    logger.info(f"   Target: ${signal.target_price:.2f}")
    logger.info(f"   Score: {signal.trade_score.total_score}/100")
    logger.info(f"   ")
    logger.info(f"   Score Breakdown:")
    logger.info(f"     - Bias alignment:  {signal.trade_score.bias_score}/20")
    logger.info(f"     - Zone quality:    {signal.trade_score.zone_score}/20")
    logger.info(f"     - Trigger quality: {signal.trade_score.trigger_score}/15")
    logger.info(f"     - Room to target:  {signal.trade_score.room_score}/15")
    logger.info(f"     - Volatility:      {signal.trade_score.volatility_score}/10")
    logger.info(f"     - Session timing:  {signal.trade_score.session_score}/10")
    logger.info(f"     - Spread:          {signal.trade_score.spread_score}/5")
    logger.info(f"     - News safety:     {signal.trade_score.news_safety_score}/5")
    
    # 7. Calculate position size
    base_position_size = strategy.calculate_position_size(
        signal=signal,
        account_balance=10000.0
    )
    
    # Apply macro regime multiplier
    adjusted_position_size = base_position_size * ext_context.position_size_multiplier
    
    logger.info(f"\n7. Position Sizing:")
    logger.info(f"   Base size:     {base_position_size:.2f} contracts")
    logger.info(f"   Regime adjust: {ext_context.position_size_multiplier:.2f}x")
    logger.info(f"   Final size:    {adjusted_position_size:.2f} contracts")
    
    logger.info("\n" + "="*70)
    logger.info("✓ Example completed successfully!")
    logger.info("="*70)


def example_status_summary():
    """
    Example: Get external data status summary
    """
    logger.info("\n" + "="*70)
    logger.info("External Data Status Summary - Example")
    logger.info("="*70)
    
    # Initialize with no API keys (for demo)
    external_data = ExternalDataManager(
        enable_calendar=False,
        enable_macro=False,
        enable_news=False
    )
    
    # Get status summary
    summary = external_data.get_status_summary()
    
    logger.info(f"\nStatus as of: {summary['timestamp']}")
    logger.info(f"\nFeeds Enabled:")
    logger.info(f"  Calendar: {summary['feeds_enabled']['calendar']}")
    logger.info(f"  Macro:    {summary['feeds_enabled']['macro']}")
    logger.info(f"  News:     {summary['feeds_enabled']['news']}")
    
    logger.info(f"\nTrading Status:")
    logger.info(f"  Allowed: {summary['trading_allowed']}")
    if not summary['trading_allowed']:
        logger.info(f"  Reason:  {summary['block_reason']}")
    
    logger.info(f"\nMacro Regime:")
    logger.info(f"  Regime:              {summary['macro_regime']}")
    logger.info(f"  Position multiplier: {summary['position_size_multiplier']:.2f}x")
    
    logger.info("\n" + "="*70)


if __name__ == "__main__":
    # Run examples
    
    # Example 1: Complete strategy flow
    example_with_external_data()
    
    # Example 2: Status summary
    example_status_summary()

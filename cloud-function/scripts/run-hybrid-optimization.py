#!/usr/bin/env python3
"""
Run hybrid strategy optimization with zone detection and event blocking.

This script optimizes:
1. SuperTrend parameters (proven baseline)
2. Zone detection and filtering
3. Economic event blocking
"""
import sys
import os
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime
import logging

# Setup logging
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

# Add cloud-function to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.strategy import SupertrendVWAPStrategy
from src.zones.zone_engine import ZoneEngine, ZoneType
from src.zones.zone_scoring import ZoneScorer


class HybridStrategyOptimizer:
    """Optimizer for hybrid zone-supertrend strategy."""
    
    def __init__(self, df: pd.DataFrame, initial_capital: float = 10000.0,
                 instrument: str = 'GOLD', calendar_path: str = None):
        """Initialize optimizer.
        
        Args:
            df: OHLC dataframe with timestamp index
            initial_capital: Starting capital
            instrument: Instrument name (GOLD, US100, etc.)
            calendar_path: Path to economic calendar JSON
        """
        self.df = df
        self.initial_capital = initial_capital
        self.instrument = instrument
        self.calendar_path = calendar_path
        self.results = []
    
    def define_hybrid_grid(self, mode: str = 'quick') -> dict:
        """Define parameter grid for hybrid strategy optimization.
        
        Args:
            mode: 'quick', 'optimize', 'medium', 'full', or 'comparison'
            
        Returns:
            Parameter grid dictionary
        """
        if mode == 'comparison':
            # Compare all TP/SL strategies with/without zones (clean comparison)
            return {
                # Fixed SuperTrend params (use proven winner from March 14)
                'supertrend_period': [10],
                'supertrend_multiplier': [1.5],
                'sma_fast': [20],
                'sma_slow': [50],
                
                # Test all TP/SL strategies
                'tp_sl_strategy': ['fixed', 'atr', 'fibonacci'],
                
                # Fixed TP/SL values (5:30 pips - proven winner)
                'sl_pips': [5.0],
                'tp_pips': [30.0],
                
                # ATR-based multipliers (test conservative to aggressive)
                'atr_sl_multiplier': [0.5, 0.7, 1.0],
                'atr_tp_multiplier': [2.0, 2.5, 3.0],
                
                # Zone filtering (ON vs OFF comparison)
                'enable_zone_filter': [True, False],
                'zone_block_distance': [1.5],  # Use proven best
                'zone_min_strength': [3.5],    # Use proven best
                
                # Zone stops (test if beneficial)
                'enable_zone_stops': [True, False],
                
                # Event blocking (proven beneficial)
                'enable_event_blocking': [False],  # Test without first
                'event_block_before_min': [15],
                'event_block_after_min': [30],
            }
        
        elif mode == 'quick':
            # Test proven baseline + zone filter variations
            return {
                # SuperTrend (proven winners)
                'supertrend_period': [10],
                'supertrend_multiplier': [3.0],
                'sma_fast': [20],
                'sma_slow': [50],
                
                # ATR-based TP/SL (proven: 0.7x2.5)
                'atr_sl_multiplier': [0.7],
                'atr_tp_multiplier': [2.5],
                
                # Zone detection
                'enable_zone_filter': [True, False],  # Compare with/without
                'zone_block_distance': [0.8, 1.0, 1.5],  # Zone widths
                'zone_min_strength': [3.5, 4.0, 4.5],  # Strength threshold
                
                # Zone stop adjustment
                'enable_zone_stops': [False],  # Keep ATR stops for now
                
                # Event blocking
                'enable_event_blocking': [True],
                'event_block_before_min': [15],
                'event_block_after_min': [30],
            }
        
        elif mode == 'optimize':
            # Optimize SuperTrend + TP/SL with proven zone config (81 combinations)
            return {
                # SuperTrend variations to test
                'supertrend_period': [8, 10, 12],
                'supertrend_multiplier': [2.5, 3.0, 3.5],
                'sma_fast': [20],
                'sma_slow': [50],
                
                # Test ATR-based TP/SL variations
                'atr_sl_multiplier': [0.5, 0.7, 0.9],
                'atr_tp_multiplier': [2.0, 2.5, 3.0],
                
                # Use proven best zone config
                'enable_zone_filter': [True],
                'zone_block_distance': [1.5],  # Proven best
                'zone_min_strength': [3.5],     # Sufficient
                
                # Keep ATR stops
                'enable_zone_stops': [False],
                
                # Event blocking enabled
                'enable_event_blocking': [True],
                'event_block_before_min': [15],
                'event_block_after_min': [30],
            }
        
        elif mode == 'medium':
            # More SuperTrend variations + zone parameters
            return {
                # SuperTrend variations
                'supertrend_period': [8, 10, 12],
                'supertrend_multiplier': [2.5, 3.0, 3.5],
                'sma_fast': [15, 20, 25],
                'sma_slow': [40, 50, 60],
                
                # ATR-based TP/SL
                'atr_sl_multiplier': [0.5, 0.7, 1.0],
                'atr_tp_multiplier': [2.0, 2.5, 3.0],
                
                # Zone detection
                'enable_zone_filter': [True, False],
                'zone_block_distance': [0.5, 0.8, 1.0, 1.5, 2.0],
                'zone_min_strength': [3.0, 3.5, 4.0, 4.5, 5.0],
                
                # Zone stops
                'enable_zone_stops': [True, False],
                
                # Event blocking
                'enable_event_blocking': [True, False],
                'event_block_before_min': [10, 15, 20],
                'event_block_after_min': [20, 30, 45],
            }
        
        else:  # full
            # Comprehensive grid
            return {
                'supertrend_period': [7, 8, 9, 10, 11, 12],
                'supertrend_multiplier': [2.0, 2.5, 3.0, 3.5, 4.0],
                'sma_fast': [10, 15, 20, 25, 30],
                'sma_slow': [35, 40, 50, 60, 70],
                'atr_sl_multiplier': [0.5, 0.6, 0.7, 0.8, 1.0],
                'atr_tp_multiplier': [1.5, 2.0, 2.5, 3.0, 3.5],
                'enable_zone_filter': [True, False],
                'zone_block_distance': [0.5, 0.8, 1.0, 1.2, 1.5, 2.0],
                'zone_min_strength': [2.5, 3.0, 3.5, 4.0, 4.5, 5.0],
                'enable_zone_stops': [True, False],
                'enable_event_blocking': [True, False],
                'event_block_before_min': [10, 15, 20, 30],
                'event_block_after_min': [20, 30, 45, 60],
            }
    
    def _load_calendar_events(self, calendar_path: str) -> list:
        """Load economic calendar events.
        
        Args:
            calendar_path: Path to calendar JSON
            
        Returns:
            List of event dictionaries with datetime objects
        """
        import json
        
        try:
            with open(calendar_path, 'r') as f:
                events = json.load(f)
            
            # Convert string dates to datetime
            for event in events:
                event['datetime'] = pd.to_datetime(event['datetime'])
            
            return events
        except Exception as e:
            print(f"⚠️  Warning: Failed to load calendar: {e}")
            return []
    
    def _is_blocked_by_event(self, timestamp: pd.Timestamp, events: list,
                            before_min: int, after_min: int) -> bool:
        """Check if timestamp is within event blocking window.
        
        Args:
            timestamp: Current timestamp
            events: List of events
            before_min: Minutes before event to block
            after_min: Minutes after event to block
            
        Returns:
            True if blocked by event
        """
        for event in events:
            event_time = event['datetime']
            
            # Check if within blocking window
            time_diff = (timestamp - event_time).total_seconds() / 60
            
            if -before_min <= time_diff <= after_min:
                return True
        
        return False
    
    def _resample_timeframe(self, df: pd.DataFrame, freq: str) -> pd.DataFrame:
        """Resample M5 data to higher timeframe.
        
        Args:
            df: M5 dataframe
            freq: '4h', '1h', or '15min'
            
        Returns:
            Resampled dataframe
        """
        df_copy = df.copy()
        df_copy.set_index('timestamp', inplace=True)
        
        resampled = df_copy.resample(freq).agg({
            'open': 'first',
            'high': 'max',
            'low': 'min',
            'close': 'last'
        }).dropna()
        
        resampled.reset_index(inplace=True)
        return resampled
    
    def _detect_simple_zones(self, df: pd.DataFrame, atr: float,
                            width_fraction: float) -> list:
        """Simple zone detection using swing highs/lows.
        
        Args:
            df: OHLC dataframe
            atr: ATR value
            width_fraction: Zone width as fraction of ATR
            
        Returns:
            List of zones [{'type': 'support'/'resistance', 'low': x, 'high': y, 'strength': s}]
        """
        zones = []
        lookback = min(50, len(df) - 10)
        
        if lookback < 10:
            return zones
        
        recent = df.iloc[-lookback:]
        zone_width = atr * width_fraction
        
        # Find swing highs (resistance)
        for i in range(2, len(recent) - 2):
            high = recent.iloc[i]['high']
            
            if (high > recent.iloc[i-1]['high'] and
                high > recent.iloc[i-2]['high'] and
                high > recent.iloc[i+1]['high'] and
                high > recent.iloc[i+2]['high']):
                
                zones.append({
                    'type': 'resistance',
                    'low': high - zone_width / 2,
                    'high': high + zone_width / 2,
                    'midpoint': high,
                    'strength': 1.0
                })
        
        # Find swing lows (support)
        for i in range(2, len(recent) - 2):
            low = recent.iloc[i]['low']
            
            if (low < recent.iloc[i-1]['low'] and
                low < recent.iloc[i-2]['low'] and
                low < recent.iloc[i+1]['low'] and
                low < recent.iloc[i+2]['low']):
                
                zones.append({
                    'type': 'support',
                    'low': low - zone_width / 2,
                    'high': low + zone_width / 2,
                    'midpoint': low,
                    'strength': 1.0
                })
        
        return zones
    
    def _calculate_atr(self, df: pd.DataFrame, period: int = 14) -> float:
        """Calculate ATR."""
        if len(df) < period + 1:
            return 0.0
        
        high = df['high'].values
        low = df['low'].values
        close = df['close'].values
        
        tr = np.maximum(high[1:] - low[1:],
                       np.maximum(abs(high[1:] - close[:-1]),
                                 abs(low[1:] - close[:-1])))
        
        atr = np.mean(tr[-period:])
        return atr
    
    def backtest_config(self, params: dict) -> dict:
        """Run backtest with given parameters.
        
        Args:
            params: Strategy parameters
            
        Returns:
            Results dictionary with metrics
        """
        # Extract parameters
        enable_zone_filter = params.get('enable_zone_filter', False)
        zone_block_dist = params.get('zone_block_distance', 1.0)
        zone_min_strength = params.get('zone_min_strength', 4.0)
        enable_event_block = params.get('enable_event_blocking', False)
        event_before = params.get('event_block_before_min', 15)
        event_after = params.get('event_block_after_min', 30)
        
        # TP/SL Strategy parameters
        tp_sl_strategy = params.get('tp_sl_strategy', 'fixed')
        sl_pips = params.get('sl_pips', 20.0)
        tp_pips = params.get('tp_pips', 40.0)
        atr_sl_mult = params.get('atr_sl_multiplier', 0.7)
        atr_tp_mult = params.get('atr_tp_multiplier', 2.5)
        
        # Prepare data with timestamp as index
        df = self.df.copy()
        if 'timestamp' not in df.columns:
            raise ValueError("DataFrame must have 'timestamp' column")
        
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df_indexed = df.set_index('timestamp')
        
        # Initialize strategy
        strategy = SupertrendVWAPStrategy(
            supertrend_period=params.get('supertrend_period', 10),
            supertrend_multiplier=params.get('supertrend_multiplier', 3.0),
            sma_fast=params.get('sma_fast', 20),
            sma_slow=params.get('sma_slow', 50),
            sl_pips=sl_pips,
            tp_pips=tp_pips,
        )
        
        # Calculate indicators first
        df_with_indicators = strategy.calculate_indicators(df_indexed)
        
        # Generate base signals
        signals_df = strategy.generate_signals(df_with_indicators)
        
        # Calculate ATR for dynamic strategies
        atr = self._calculate_atr(df, period=14)
        
        # Apply TP/SL based on strategy type
        if tp_sl_strategy == 'fixed':
            # Fixed TP/SL already set in strategy initialization
            pass
        
        elif tp_sl_strategy == 'atr':
            # Apply ATR-based TP/SL to signals
            for idx in signals_df.index:
                if signals_df.loc[idx, 'signal'] != 0:
                    price = df_indexed.loc[idx, 'close']
                    
                    # Calculate ATR-based stops
                    sl_distance = atr * atr_sl_mult
                    tp_distance = atr * atr_tp_mult
                    
                    if signals_df.loc[idx, 'signal'] == 1:  # BUY
                        signals_df.loc[idx, 'stop_loss'] = price - sl_distance
                        signals_df.loc[idx, 'take_profit'] = price + tp_distance
                    elif signals_df.loc[idx, 'signal'] == -1:  # SELL
                        signals_df.loc[idx, 'stop_loss'] = price + sl_distance
                        signals_df.loc[idx, 'take_profit'] = price - tp_distance
        
        elif tp_sl_strategy == 'fibonacci':
            # Apply Fibonacci-based TP/SL to signals
            for idx in signals_df.index:
                if signals_df.loc[idx, 'signal'] != 0:
                    signal_type = int(signals_df.loc[idx, 'signal'])
                    
                    # Get historical data up to signal point
                    signal_position = df_indexed.index.get_loc(idx)
                    hist_df = df_indexed.iloc[:signal_position+1]
                    entry_price = float(hist_df.iloc[-1]['close'])
                    
                    # Calculate Fibonacci TP/SL
                    tp_pips_calc, sl_pips_calc = strategy.calculate_fibonacci_tp_sl(
                        hist_df, signal_type, entry_price
                    )
                    
                    if tp_pips_calc and sl_pips_calc:
                        pip_value = params.get('pip_value', 1.0)
                        sl_distance = sl_pips_calc * pip_value
                        tp_distance = tp_pips_calc * pip_value
                        
                        if signal_type == 1:  # BUY
                            signals_df.loc[idx, 'stop_loss'] = entry_price - sl_distance
                            signals_df.loc[idx, 'take_profit'] = entry_price + tp_distance
                        elif signal_type == -1:  # SELL
                            signals_df.loc[idx, 'stop_loss'] = entry_price + sl_distance
                            signals_df.loc[idx, 'take_profit'] = entry_price - tp_distance
        
        # Apply zone filtering if enabled
        if enable_zone_filter:
            try:
                # Initialize zone engine and scorer
                zone_engine = ZoneEngine(symbol=self.instrument)
                zone_scorer = ZoneScorer(symbol=self.instrument)
                
                # Detect zones on multiple timeframes
                h4_df = self._resample_timeframe(df, '4h')
                h1_df = self._resample_timeframe(df, '1h')
                m15_df = self._resample_timeframe(df, '15min')
                
                # Detect zones on each timeframe
                h4_zones = zone_engine.detect_zones(h4_df, 'H4')
                h1_zones = zone_engine.detect_zones(h1_df, 'H1')
                m15_zones = zone_engine.detect_zones(m15_df, 'M15')
                
                # SCORE ZONES - Calculate actual strength scores
                for zone in h4_zones:
                    zone.strength_score = zone_scorer.score_zone(zone, h4_df)
                for zone in h1_zones:
                    zone.strength_score = zone_scorer.score_zone(zone, h1_df)
                for zone in m15_zones:
                    zone.strength_score = zone_scorer.score_zone(zone, m15_df)
                
                # LOG ZONES ONCE (only for first backtest run)
                if not hasattr(self, '_zones_logged'):
                    self._zones_logged = True
                    logger.warning(f"\n{'='*80}")
                    logger.warning(f"ZONE DETECTION ANALYSIS")
                    logger.warning(f"{'='*80}")
                    logger.warning(f"H4 Zones: {len(h4_zones)}, H1 Zones: {len(h1_zones)}, M15 Zones: {len(m15_zones)}")
                    
                    # Count strong zones
                    strong_h4 = sum(1 for z in h4_zones if z.strength_score >= zone_min_strength)
                    strong_h1 = sum(1 for z in h1_zones if z.strength_score >= zone_min_strength)
                    strong_m15 = sum(1 for z in m15_zones if z.strength_score >= zone_min_strength)
                    logger.warning(f"Strong Zones (>={zone_min_strength}): H4={strong_h4}, H1={strong_h1}, M15={strong_m15}")
                    
                    if h4_zones:
                        z = h4_zones[0]
                        logger.warning(f"\nSample H4 Zone:")
                        logger.warning(f"  Type: {z.type if hasattr(z, 'type') else 'N/A'}")
                        logger.warning(f"  Midpoint: {z.midpoint if hasattr(z, 'midpoint') else 'N/A'}")
                        logger.warning(f"  Lower: {z.lower_bound if hasattr(z, 'lower_bound') else 'N/A'}")
                        logger.warning(f"  Upper: {z.upper_bound if hasattr(z, 'upper_bound') else 'N/A'}")
                        logger.warning(f"  Strength: {z.strength_score if hasattr(z, 'strength_score') else 'N/A'}")
                        logger.warning(f"  State: {z.state if hasattr(z, 'state') else 'N/A'}")
                    
                    # Show strength distribution
                    all_strengths = [z.strength_score for z in h4_zones + h1_zones + m15_zones]
                    if all_strengths:
                        logger.warning(f"\nZone Strength Distribution:")
                        logger.warning(f"  Min: {min(all_strengths):.2f}")
                        logger.warning(f"  Max: {max(all_strengths):.2f}")
                        logger.warning(f"  Avg: {sum(all_strengths)/len(all_strengths):.2f}")
                    
                    logger.warning(f"{'='*80}\n")
                
                # Combine all zones
                all_zones = h4_zones + h1_zones + m15_zones
                
                # Filter signals based on zones
                signals_before_zone_filter = (signals_df['signal'] != 0).sum()
                zones_blocked_count = 0
                
                for idx in signals_df.index:
                    if signals_df.loc[idx, 'signal'] == 0:
                        continue
                    
                    price = df_indexed.loc[idx, 'close']
                    signal_type = signals_df.loc[idx, 'signal']
                    
                    # Check if signal conflicts with nearby zones
                    for zone in all_zones:
                        # Check zone strength using correct attribute
                        if zone.strength_score < zone_min_strength:
                            continue
                        
                        # Calculate distance to zone using correct attribute
                        zone_distance = abs(price - zone.midpoint) / atr
                        
                        # Block BUY signals near resistance (using ZoneType enum)
                        if signal_type == 1 and zone.type == ZoneType.RESISTANCE:
                            if zone_distance < zone_block_dist:
                                signals_df.loc[idx, 'signal'] = 0  # Block signal
                                zones_blocked_count += 1
                                break
                        
                        # Block SELL signals near support (using ZoneType enum)
                        elif signal_type == -1 and zone.type == ZoneType.SUPPORT:
                            if zone_distance < zone_block_dist:
                                signals_df.loc[idx, 'signal'] = 0  # Block signal
                                zones_blocked_count += 1
                                break
                
                signals_after_zone_filter = (signals_df['signal'] != 0).sum()
                
                # Log zone filtering results once
                if not hasattr(self, '_zone_filter_logged'):
                    self._zone_filter_logged = True
                    logger.warning(f"Zone Filter: {signals_before_zone_filter} signals -> {signals_after_zone_filter} signals ({zones_blocked_count} blocked)")
            except Exception as e:
                # If zone filtering fails, continue without it
                logger.warning(f"Zone filtering failed: {e}")
        
        # Apply event blocking filter to signals if enabled
        if enable_event_block and self.calendar_path:
            try:
                from src.data.manual_calendar_adapter import ManualCalendarAdapter
                calendar = ManualCalendarAdapter(self.calendar_path)
                
                # Count signals before event blocking
                signals_before_event_filter = (signals_df['signal'] != 0).sum()
                events_blocked_count = 0
                
                # Filter out signals during blocked periods
                for idx in signals_df.index:
                    if signals_df.loc[idx, 'signal'] == 0:
                        continue
                    
                    timestamp = idx
                    is_blocked, event = calendar.is_blocked(
                        timestamp,
                        custom_block_before=event_before,
                        custom_block_after=event_after
                    )
                    
                    if is_blocked:
                        signals_df.loc[idx, 'signal'] = 0  # Block signal
                        events_blocked_count += 1
                
                signals_after_event_filter = (signals_df['signal'] != 0).sum()
                
                # Log event filtering results once
                if not hasattr(self, '_event_filter_logged'):
                    self._event_filter_logged = True
                    logger.warning(f"Event Filter: {signals_before_event_filter} signals -> {signals_after_event_filter} signals ({events_blocked_count} blocked)")
                    
            except Exception as e:
                logger.warning(f"Event blocking failed: {e}")
        
        # Configure backtester WITHOUT event blocking (already filtered signals above)
        from src.core.backtester import BacktestConfig, IntraCandleBacktester
        
        config = BacktestConfig(
            initial_capital=self.initial_capital,
            spread_cost_usd=0.50,
            slippage_cost_usd=0.05,
            pip_value=1.0,
            max_positions=1,
            enable_event_blocking=False,  # Already filtered in signals
            verbose=False  # Disable logging for optimization speed
        )
        
        backtester = IntraCandleBacktester(config=config)
        
        # Run backtest
        try:
            results = backtester.run(
                df=df_with_indicators,
                signals=signals_df,
                tick_data=None,  # Use OHLC simulation
                timeframe_minutes=5
            )
            
            # Extract metrics (use correct keys from backtester)
            return {
                'params': params,
                'total_return': results.get('return_pct', 0.0),
                'win_rate': results.get('win_rate', 0.0),
                'trades': results.get('total_trades', 0),
                'sharpe': results.get('sharpe_ratio', 0.0),
                'max_dd': results.get('max_drawdown_pct', 0.0),
                'profit_factor': results.get('profit_factor', 0.0)
            }
        
        except Exception as e:
            logger.error(f"Backtest failed: {e}")
            return {
                'params': params,
                'total_return': 0.0,
                'win_rate': 0.0,
                'trades': 0,
                'sharpe': 0.0,
                'max_dd': 0.0,
                'profit_factor': 0.0
            }
    
    def run_optimization(self, mode: str = 'quick', parallel: bool = True,
                        n_jobs: int = -1) -> pd.DataFrame:
        """Run optimization across parameter grid.
        
        Args:
            mode: Optimization mode (quick, medium, full)
            parallel: Whether to use parallel processing
            n_jobs: Number of parallel workers (-1 for all cores)
            
        Returns:
            Results dataframe sorted by total return
        """
        from itertools import product
        
        grid = self.define_hybrid_grid(mode)
        
        # Generate all combinations
        keys = list(grid.keys())
        values = list(grid.values())
        combinations = list(product(*values))
        
        total = len(combinations)
        print(f"\n🔬 Testing {total} parameter combinations...")
        print(f"   Mode: {mode}")
        print(f"   Parallel: {'Yes' if parallel else 'No'}")
        if parallel:
            n_workers = n_jobs if n_jobs > 0 else os.cpu_count()
            print(f"   Workers: {n_workers}")
        print()
        
        if parallel:
            from concurrent.futures import ProcessPoolExecutor, as_completed
            
            # Prepare parameter dicts
            param_dicts = [dict(zip(keys, combo)) for combo in combinations]
            
            results = []
            with ProcessPoolExecutor(max_workers=n_workers) as executor:
                futures = {executor.submit(self.backtest_config, p): p for p in param_dicts}
                
                completed = 0
                for future in as_completed(futures):
                    completed += 1
                    try:
                        result = future.result()
                        results.append(result)
                        if completed % 10 == 0 or completed == total:
                            print(f"   [{completed}/{total}] Completed...")
                    except Exception as e:
                        print(f"   ❌ Error: {e}")
        else:
            # Sequential
            results = []
            for i, combo in enumerate(combinations, 1):
                params = dict(zip(keys, combo))
                result = self.backtest_config(params)
                results.append(result)
                
                if i % 10 == 0 or i == total:
                    print(f"   [{i}/{total}] Completed...")
        
        # Convert to DataFrame
        df = pd.DataFrame(results)
        
        # Sort by total return
        df = df.sort_values('total_return', ascending=False)
        
        return df
    
    def print_summary(self, results_df: pd.DataFrame, top_n: int = 10):
        """Print optimization summary.
        
        Args:
            results_df: Results dataframe
            top_n: Number of top results to show
        """
        print("\n" + "="*80)
        print(f"📊 TOP {top_n} CONFIGURATIONS")
        print("="*80)
        
        # Print header
        print(f"\n{'Rank':<6}{'Return':<10}{'WinRate':<10}{'Trades':<8}{'Sharpe':<8}{'MaxDD':<8}{'TP/SL':<10}{'Zones':<8}{'Events':<8}")
        print("-"*80)
        
        for idx, (_, row) in enumerate(results_df.head(top_n).iterrows(), 1):
            zone_status = "ON" if row['params'].get('enable_zone_filter', False) else "OFF"
            event_status = "ON" if row['params'].get('enable_event_blocking', False) else "OFF"
            tp_sl = row['params'].get('tp_sl_strategy', 'fixed')[:6]  # Truncate to fit
            
            print(f"{idx:<6}"
                  f"{row['total_return']:>8.2f}% "
                  f"{row['win_rate']:>8.1f}% "
                  f"{int(row['trades']):<8}"
                  f"{row['sharpe']:>7.2f} "
                  f"{row['max_dd']:>7.2f}% "
                  f"{tp_sl:<10}"
                  f"{zone_status:<8}"
                  f"{event_status:<8}")
        
        print()


def main():
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Hybrid Strategy Optimization: SuperTrend + Zones + Event Blocking'
    )
    parser.add_argument('--data-file', required=True, help='Path to M5 CSV data file')
    parser.add_argument('--instrument', default='GOLD', help='Instrument name')
    parser.add_argument('--capital', type=float, default=10000.0, help='Initial capital')
    parser.add_argument('--mode', default='quick', 
                       choices=['quick', 'optimize', 'medium', 'full', 'comparison'],
                       help='Optimization mode: comparison (72 combos - test all TP/SL strategies), '
                            'quick (18), optimize (81), medium (~1M), full (~10M)')
    
    # Default calendar path relative to cloud-function directory
    default_calendar = os.path.join(
        os.path.dirname(os.path.dirname(__file__)), 
        'data', 
        'economic_calendar.json'
    )
    parser.add_argument('--calendar-path', 
                       default=default_calendar,
                       help='Path to economic calendar JSON')
    parser.add_argument('--n-jobs', type=int, default=-1,
                       help='Number of parallel workers (-1 for all cores)')
    parser.add_argument('--no-parallel', action='store_true',
                       help='Disable parallel processing')
    parser.add_argument('--output', default='hybrid_optimization_results.csv',
                       help='Output CSV file (default: current directory)')
    
    args = parser.parse_args()
    
    print("\n" + "="*80)
    print("🎯 HYBRID STRATEGY OPTIMIZATION")
    print("   SuperTrend + Multi-Timeframe Zones + Event Blocking")
    print("="*80 + "\n")
    
    # Load data
    print(f"📊 Loading data from {args.data_file}...")
    try:
        df = pd.read_csv(args.data_file)
        
        # Ensure timestamp column
        if 'time' in df.columns:
            df['timestamp'] = pd.to_datetime(df['time'])
        elif 'timestamp' not in df.columns:
            print("❌ Error: No 'timestamp' or 'time' column found")
            sys.exit(1)
        else:
            df['timestamp'] = pd.to_datetime(df['timestamp'])
        
        df = df.sort_values('timestamp').reset_index(drop=True)
        
        print(f"✅ Loaded {len(df)} M5 bars")
        print(f"   Range: {df['timestamp'].iloc[0]} to {df['timestamp'].iloc[-1]}")
        print(f"   Columns: {list(df.columns)}\n")
        
    except Exception as e:
        print(f"❌ Failed to load data: {e}")
        sys.exit(1)
    
    # Check calendar file
    if os.path.exists(args.calendar_path):
        print(f"✅ Economic calendar found: {args.calendar_path}\n")
    else:
        print(f"⚠️  Warning: Calendar file not found: {args.calendar_path}")
        print(f"   Event blocking will be disabled\n")
    
    # Initialize optimizer
    optimizer = HybridStrategyOptimizer(
        df=df,
        initial_capital=args.capital,
        instrument=args.instrument,
        calendar_path=args.calendar_path if os.path.exists(args.calendar_path) else None
    )
    
    # Run optimization
    print(f"🚀 Starting optimization...")
    print(f"   Capital: ${args.capital:,.2f}")
    print(f"   Mode: {args.mode}")
    
    start_time = datetime.now()
    
    results_df = optimizer.run_optimization(
        mode=args.mode,
        parallel=not args.no_parallel,
        n_jobs=args.n_jobs
    )
    
    elapsed = (datetime.now() - start_time).total_seconds()
    
    # Show summary
    optimizer.print_summary(results_df, top_n=20)
    
    # Ensure output directory exists
    output_dir = os.path.dirname(args.output)
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir, exist_ok=True)
    
    # Save results
    results_df.to_csv(args.output, index=False)
    print(f"✅ Results saved to: {args.output}")
    
    # Save top 50
    top_50_file = args.output.replace('.csv', '_top50.csv')
    results_df.head(50).to_csv(top_50_file, index=False)
    print(f"✅ Top 50 saved to: {top_50_file}")
    
    print(f"\n⏱️  Total time: {elapsed/60:.1f} minutes")
    print(f"⚡ Speed: {len(results_df)/elapsed:.1f} configs/second\n")
    print("✅ Optimization complete!\n")


if __name__ == '__main__':
    main()

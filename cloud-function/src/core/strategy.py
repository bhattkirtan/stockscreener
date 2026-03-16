"""
Strategy implementation: Supertrend + SMA/EMA
Simplified approach focusing on trend-following with moving averages
"""

import pandas as pd
import numpy as np
from typing import Dict, Tuple, Optional
import logging

from src.core import indicators as _ind
from src.core import fibonacci as _fib

logger = logging.getLogger(__name__)


class SupertrendVWAPStrategy:
    """
    Supertrend + SMA/EMA trend-following strategy:
    - Supertrend for primary trend direction
    - SMA Fast/Slow for crossover signals and trend confirmation
    - EMA for dynamic support/resistance
    - Heikin Ashi candles for cleaner signals (calculated but not used in logic)
    """
    
    def __init__(self, 
                 supertrend_period: int = 10,
                 supertrend_multiplier: float = 2.5,
                 sma_fast: int = 20,  # Fast SMA for crossovers
                 sma_slow: int = 50,  # Slow SMA for trend
                 ema_period: int = 21,  # EMA for dynamic support/resistance
                 bb_period: int = 20,  # Bollinger Bands period
                 bb_std: float = 2.0,  # Bollinger Bands standard deviation
                 sl_pips: float = 20.0,
                 tp_pips: float = 40.0,
                 pip_value: float = 0.01,
                 # PHASE 1: Gold-specific filters
                 use_rsi_filter: bool = False,
                 rsi_period: int = 14,
                 rsi_overbought: float = 70,
                 rsi_oversold: float = 30,
                 use_atr_volatility_filter: bool = False,
                 atr_volatility_period: int = 14,
                 atr_sma_period: int = 20,
                 atr_min_ratio: float = 0.7,
                 atr_max_ratio: float = 1.5,
                 use_session_filter: bool = False,
                 trading_sessions: str = 'london_ny',
                 # PHASE 4: Heiken Ashi for trend smoothing
                 use_heikin_ashi: bool = False):  # Disabled: No improvement over baseline
        # PHASE 2 REMOVED: ADX (no improvement), BB sizing (-25.85% test), Dynamic TP/SL (-55% test) all failed
        # PHASE 3 REMOVED: MTF confirmation (+0.82% test) and S/R filter (-25.90% test) hurt performance
        # FINAL: Phase 1 baseline + RSI filter (+30.09% test improvement) = 150.77% test performance
        """
        Args:
            supertrend_period: ATR period for Supertrend
            supertrend_multiplier: ATR multiplier for Supertrend
            sma_fast: Fast SMA period for crossovers
            sma_slow: Slow SMA period for trend direction
            ema_period: EMA period for dynamic support/resistance
            bb_period: Bollinger Bands period
            bb_std: Bollinger Bands standard deviation
            sl_pips: Stop loss in pips
            tp_pips: Take profit in pips
            pip_value: Value of 1 pip (0.01 for gold, 0.0001 for forex)
            use_rsi_filter: Enable RSI overbought/oversold filter
            rsi_period: RSI calculation period
            rsi_overbought: RSI level considered overbought
            rsi_oversold: RSI level considered oversold
            use_atr_volatility_filter: Enable ATR volatility filter
            atr_volatility_period: ATR period for volatility calculation
            atr_sma_period: SMA period for ATR average
            atr_min_ratio: Minimum ATR ratio (avoid low volatility)
            atr_max_ratio: Maximum ATR ratio (avoid extreme volatility)
            use_session_filter: Enable trading session filter
            trading_sessions: 'london_ny', 'london_only', or 'all'
            use_heikin_ashi: Use HA candles for trend detection (prices still from OHLC)
            
            Phase 2/3 parameters REMOVED - all failed testing except RSI filter
        """
        self.supertrend_period = supertrend_period
        self.supertrend_multiplier = supertrend_multiplier
        self.sma_fast = sma_fast
        self.sma_slow = sma_slow
        self.ema_period = ema_period
        self.bb_period = bb_period
        self.bb_std = bb_std
        self.sl_pips = sl_pips
        self.tp_pips = tp_pips
        self.pip_value = pip_value
        
        # PHASE 1: Gold-specific filters
        self.use_rsi_filter = use_rsi_filter
        self.rsi_period = rsi_period
        self.rsi_overbought = rsi_overbought
        self.rsi_oversold = rsi_oversold
        self.use_atr_volatility_filter = use_atr_volatility_filter
        self.atr_volatility_period = atr_volatility_period
        self.atr_sma_period = atr_sma_period
        self.atr_min_ratio = atr_min_ratio
        self.atr_max_ratio = atr_max_ratio
        self.use_session_filter = use_session_filter
        self.trading_sessions = trading_sessions
        
        # PHASE 4: Heiken Ashi
        self.use_heikin_ashi = use_heikin_ashi
        
        # Memory system for delayed SMA alignment
        self.pending_flip = {
            'direction': None,      # 1=BUY, -1=SELL
            'candle_idx': None,     # When flip occurred
            'price': None,          # Price at flip
            'ema': None,            # EMA at flip
            'price_ema_aligned': False,  # Did Price/EMA align at flip?
            'max_wait': 10          # Max candles to wait (50 min on M5)
        }
        
        # Track last processed bar to avoid reprocessing history
        self.last_processed_index = 0
    
    def calculate_heikin_ashi(self, df: pd.DataFrame) -> pd.DataFrame:
        """Calculate Heikin-Ashi candles. Delegates to indicators.calculate_heikin_ashi."""
        ha_cols = _ind.calculate_heikin_ashi(df)
        result = df.copy()
        for col in ha_cols.columns:
            result[col] = ha_cols[col]
        return result
    
    def calculate_atr(self, df: pd.DataFrame, period: int) -> pd.Series:
        """Average True Range. Delegates to indicators.calculate_atr."""
        return _ind.calculate_atr(df, period)
    
    def calculate_supertrend(
        self,
        df: pd.DataFrame,
        period: Optional[int] = None,
        multiplier: Optional[float] = None,
    ) -> Tuple[pd.Series, pd.Series]:
        """Supertrend indicator. Delegates to indicators.calculate_supertrend."""
        return _ind.calculate_supertrend(
            df,
            period if period is not None else self.supertrend_period,
            multiplier if multiplier is not None else self.supertrend_multiplier,
        )
    
    def calculate_vwap(self, df: pd.DataFrame) -> pd.Series:
        """Volume Weighted Average Price. Delegates to indicators.calculate_vwap."""
        return _ind.calculate_vwap(df)

    def calculate_bollinger_bands(self, df: pd.DataFrame) -> Tuple[pd.Series, pd.Series, pd.Series]:
        """Bollinger Bands. Delegates to indicators.calculate_bollinger_bands."""
        return _ind.calculate_bollinger_bands(df, self.bb_period, self.bb_std)

    def calculate_rsi(self, df: pd.DataFrame) -> pd.Series:
        """RSI. Delegates to indicators.calculate_rsi."""
        return _ind.calculate_rsi(df, self.rsi_period)
    
    def find_swing_points(self, df: pd.DataFrame, lookback: int = 5) -> Tuple[pd.Series, pd.Series]:
        """Swing highs/lows. Delegates to fibonacci.find_swing_points."""
        return _fib.find_swing_points(df, lookback)

    def get_recent_swing_points(
        self, df: pd.DataFrame, lookback_bars: int = 50
    ) -> Tuple[Optional[float], Optional[float]]:
        """Most recent swing high/low. Delegates to fibonacci.get_recent_swing_points."""
        return _fib.get_recent_swing_points(df, lookback_bars)

    def calculate_fibonacci_levels(
        self, swing_high: float, swing_low: float, direction: int
    ) -> Dict[str, float]:
        """Fibonacci levels. Delegates to fibonacci.calculate_fibonacci_levels."""
        return _fib.calculate_fibonacci_levels(swing_high, swing_low, direction)

    def calculate_fibonacci_tp_sl(
        self, df: pd.DataFrame, direction: int, entry_price: float
    ) -> Tuple[Optional[float], Optional[float]]:
        """Fibonacci TP/SL in pips. Delegates to fibonacci.calculate_fibonacci_tp_sl."""
        return _fib.calculate_fibonacci_tp_sl(df, direction, entry_price, self.pip_value)
    
    # PHASE 2 METHODS REMOVED (ADX, BB sizing, Dynamic TP/SL):
    # - calculate_adx(): ADX filter doesn't improve top 10 strategies
    # - get_bb_position_multiplier(): BB position sizing failed (-25.85% test)
    # - calculate_dynamic_tp_sl(): Dynamic TP/SL catastrophically failed (-55% test)
    # Fixed TP/SL works best
    
    # PHASE 3 METHODS REMOVED (MTF and S/R):
    # - calculate_mtf_trend(): MTF confirmation had negligible impact (+0.82% test)
    # - find_support_resistance(): S/R filter was catastrophically bad (-25.90% test)
    # Only RSI filter provides real value (+30.09% test improvement)
    
    def is_trading_session(self, hour: int) -> bool:
        """
        Check if current hour (UTC) is within allowed trading sessions
        
        London session: 7:00-16:00 UTC
        NY session: 12:00-21:00 UTC
        London/NY overlap: 12:00-16:00 UTC (most liquid)
        
        Args:
            hour: Hour in UTC (0-23)
            
        Returns:
            True if in allowed trading session
        """
        if self.trading_sessions == 'all':
            return True
        elif self.trading_sessions == 'london_only':
            return 7 <= hour < 16
        elif self.trading_sessions == 'london_ny':
            # London 7-16, NY 12-21 (combined 7-21)
            return 7 <= hour < 21
        else:
            return True  # Default to allowing all sessions
    
    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Calculate all indicators
        
        Args:
            df: DataFrame with OHLCV columns
            
        Returns:
            DataFrame with all indicators added
        """
        result = df.copy()
        
        # Heikin Ashi (always calculate for analysis, but only use if enabled)
        ha_df = self.calculate_heikin_ashi(df)
        result['ha_open'] = ha_df['ha_open']
        result['ha_high'] = ha_df['ha_high']
        result['ha_low'] = ha_df['ha_low']
        result['ha_close'] = ha_df['ha_close']
        
        # Supertrend: Use HA candles if enabled, otherwise regular OHLC
        if self.use_heikin_ashi:
            # Calculate Supertrend on Heiken Ashi for smoother trend detection
            result['supertrend'], result['direction'] = self.calculate_supertrend(ha_df)
        else:
            # Standard: Calculate Supertrend on regular OHLC
            result['supertrend'], result['direction'] = self.calculate_supertrend(df)
        
        # SMA Fast and Slow
        result['sma_fast'] = df['close'].rolling(window=self.sma_fast).mean()
        result['sma_slow'] = df['close'].rolling(window=self.sma_slow).mean()
        
        # EMA
        result['ema'] = df['close'].ewm(span=self.ema_period, adjust=False).mean()
        
        # Bollinger Bands
        result['bb_middle'] = df['close'].rolling(window=self.bb_period).mean()
        bb_std = df['close'].rolling(window=self.bb_period).std()
        result['bb_upper'] = result['bb_middle'] + (self.bb_std * bb_std)
        result['bb_lower'] = result['bb_middle'] - (self.bb_std * bb_std)
        result['bb_width'] = result['bb_upper'] - result['bb_lower']
        
        # PHASE 1: Gold-specific filters
        
        # ATR: Always calculate for TP/SL (uses supertrend period for consistency)
        result['atr'] = self.calculate_atr(df, self.supertrend_period)
        
        # RSI filter
        if self.use_rsi_filter:
            result['rsi'] = self.calculate_rsi(df)
        
        # ATR Volatility filter (uses different period for filtering)
        if self.use_atr_volatility_filter:
            result['atr_filter'] = self.calculate_atr(df, self.atr_volatility_period)
            result['atr_sma'] = result['atr_filter'].rolling(window=self.atr_sma_period).mean()
            result['atr_ratio'] = result['atr_filter'] / result['atr_sma']
        
        # Session filter (add hour column for filtering)
        if self.use_session_filter:
            result['hour'] = df.index.hour
        
        # PHASE 2 REMOVED: ADX (no improvement), BB sizing (-25.85%), Dynamic TP/SL (-55%) all failed
        # PHASE 3 REMOVED: MTF confirmation (+0.82% test, negligible) and S/R filter (-25.90% test, catastrophic)
        # FINAL: Phase 1 baseline + RSI filter (+30.09% test improvement) = 150.77% test performance
        
        return result
    
    def generate_signals(self, df: pd.DataFrame, live_mode: bool = False) -> pd.DataFrame:
        """
        Generate trading signals based on Supertrend + SMA/EMA
        
        Signal logic:
        - BUY: Supertrend uptrend + price > SMA_fast > SMA_slow (strong uptrend)
        - SELL: Supertrend downtrend + price < SMA_fast < SMA_slow (strong downtrend)
        - Alternative: SMA crossovers confirmed by Supertrend direction
        
        Args:
            df: DataFrame with indicators calculated
            live_mode: If True, only process new bars (for live trading). If False, process all bars (for backtesting)
            
        Returns:
            DataFrame with signal (1=buy, -1=sell, 0=hold), stop_loss, take_profit columns
        """
        signals = df.copy()
        signals['signal'] = 0
        signals['stop_loss'] = np.nan
        signals['take_profit'] = np.nan
        signals['entry_price'] = np.nan
        
        # Track if we're in a position to avoid multiple entries
        in_position = False
        position_type = 0  # 1 for long, -1 for short
        
        # In live mode: only process NEW bars (incremental)
        # In backtest mode: process ALL bars (full simulation)
        if live_mode:
            start_idx = max(1, self.last_processed_index)
        else:
            start_idx = 1  # Process all bars for backtesting
        
        for i in range(start_idx, len(signals)):
            # Skip if insufficient data
            if (pd.isna(signals['supertrend'].iloc[i]) or 
                pd.isna(signals['sma_fast'].iloc[i]) or
                pd.isna(signals['sma_slow'].iloc[i]) or
                pd.isna(signals['ema'].iloc[i]) or
                pd.isna(signals['bb_middle'].iloc[i])):
                continue
            
            # ALWAYS use real OHLC close for price checks (not HA close)
            close = signals['close'].iloc[i]
            supertrend_dir = signals['direction'].iloc[i]
            sma_fast = signals['sma_fast'].iloc[i]
            sma_slow = signals['sma_slow'].iloc[i]
            ema = signals['ema'].iloc[i]
            bb_middle = signals['bb_middle'].iloc[i]
            bb_upper = signals['bb_upper'].iloc[i]
            bb_lower = signals['bb_lower'].iloc[i]
            bb_width = signals['bb_width'].iloc[i]
            
            # Check for Supertrend direction changes (CRITICAL: only enter on trend flip)
            prev_supertrend_dir = signals['direction'].iloc[i-1]
            trend_changed_to_up = (supertrend_dir == 1 and prev_supertrend_dir == -1)
            trend_changed_to_down = (supertrend_dir == -1 and prev_supertrend_dir == 1)
            
            # Check for SMA crossovers
            sma_fast_prev = signals['sma_fast'].iloc[i-1]
            sma_slow_prev = signals['sma_slow'].iloc[i-1]
            golden_cross = (sma_fast > sma_slow) and (sma_fast_prev <= sma_slow_prev)
            death_cross = (sma_fast < sma_slow) and (sma_fast_prev >= sma_slow_prev)
            
            # Log Supertrend flips
            if trend_changed_to_up or trend_changed_to_down:
                flip_dir = "UP" if trend_changed_to_up else "DOWN"
                logger.info(f"🔄 [Strategy] Supertrend flip {flip_dir} at i={i}: "
                           f"Price={close:.2f}, EMA={ema:.2f}, "
                           f"SMA_fast={sma_fast:.2f}, SMA_slow={sma_slow:.2f}, "
                           f"GoldenCross={golden_cross}, DeathCross={death_cross}")
            
            # Exit logic: Check if we should exit current position
            if in_position:
                if position_type == 1 and (supertrend_dir == -1 or death_cross):
                    # Exit long on downtrend or death cross
                    in_position = False
                    position_type = 0
                elif position_type == -1 and (supertrend_dir == 1 or golden_cross):
                    # Exit short on uptrend or golden cross
                    in_position = False
                    position_type = 0
            
            # Entry logic: Only enter if not in position
            if not in_position:
                # MEMORY SYSTEM: Check for pending flip waiting for SMA alignment
                # In live mode: only check on latest bar to avoid reprocessing
                # In backtest mode: check every bar to simulate full strategy
                signal_from_memory = 0
                if live_mode:
                    if i == len(signals) - 1:  # Only on latest bar in live mode
                        signal_from_memory = self._check_pending_flip(i, signals)
                else:
                    signal_from_memory = self._check_pending_flip(i, signals)  # Check all bars in backtest
                if signal_from_memory != 0:
                    # Fire signal from memory (SMA finally aligned)
                    logger.info(f"🧠 [Strategy] Memory signal fired at i={i}: Pending flip from candle {self.pending_flip['candle_idx']} now has SMA aligned")
                    signals.iloc[i, signals.columns.get_loc('signal')] = signal_from_memory
                    signals.iloc[i, signals.columns.get_loc('entry_price')] = close
                    
                    atr = signals['atr'].iloc[i]
                    if signal_from_memory == 1:  # BUY
                        signals.iloc[i, signals.columns.get_loc('stop_loss')] = close - (self.sl_pips * atr)
                        signals.iloc[i, signals.columns.get_loc('take_profit')] = close + (self.tp_pips * atr)
                        position_type = 1
                    else:  # SELL
                        signals.iloc[i, signals.columns.get_loc('stop_loss')] = close + (self.sl_pips * atr)
                        signals.iloc[i, signals.columns.get_loc('take_profit')] = close - (self.tp_pips * atr)
                        position_type = -1
                    
                    in_position = True
                    self.pending_flip['direction'] = None  # Clear memory
                    continue  # Skip to next candle
                
                # PHASE 1: Apply gold-specific filters before entry
                
                # RSI Filter: Skip if overbought/oversold
                if self.use_rsi_filter:
                    rsi = signals['rsi'].iloc[i]
                    if pd.isna(rsi):
                        continue  # Skip if RSI not calculated yet
                    # Don't buy if overbought, don't sell if oversold
                    if (supertrend_dir == 1 and rsi > self.rsi_overbought) or \
                       (supertrend_dir == -1 and rsi < self.rsi_oversold):
                        continue
                
                # ATR Volatility Filter: Skip if extreme volatility
                if self.use_atr_volatility_filter:
                    atr_ratio = signals['atr_ratio'].iloc[i]
                    if pd.isna(atr_ratio):
                        continue  # Skip if ATR ratio not calculated yet
                    # Skip if too low volatility (< min) or too high (> max)
                    if atr_ratio < self.atr_min_ratio or atr_ratio > self.atr_max_ratio:
                        continue
                
                # Session Filter: Only trade during specified sessions
                if self.use_session_filter:
                    hour = signals['hour'].iloc[i]
                    if not self.is_trading_session(hour):
                        continue
                
                # PHASE 2/3 REMOVED: All failed in testing
                # - ADX Filter: No improvement on top 10 strategies
                # - BB Position Sizing: -25.85% test (bad)
                # - Dynamic TP/SL: -55% test (catastrophic)
                # - MTF Confirmation: +0.82% test (negligible, not worth complexity)
                # - S/R Filter: -25.90% test (catastrophic)
                # Only RSI filter survived with +30.09% test improvement
                
                # Check if new flip invalidates pending memory (whipsaw protection)
                if trend_changed_to_up or trend_changed_to_down:
                    flip_dir = 1 if trend_changed_to_up else -1
                    if self.pending_flip['direction'] is not None and self.pending_flip['direction'] != flip_dir:
                        logger.info(f"⚠️ [Strategy] Opposite flip at i={i} - INVALIDATING pending {self._flip_name(self.pending_flip['direction'])} from candle {self.pending_flip['candle_idx']} (whipsaw protection)")
                        self.pending_flip['direction'] = None  # Clear memory
                
                # BUY Signal: Multiple conditions
                # 1. Supertrend CHANGED to uptrend (prevents multiple signals in same trend)
                # 2. Price above EMA (short-term momentum)
                # 3. Either golden cross OR fast SMA > slow SMA (trend strength)
                if (trend_changed_to_up and 
                    close > ema and 
                    (golden_cross or sma_fast > sma_slow)):
                    
                    logger.info(f"✅ [Strategy] BUY signal at i={i}: "
                               f"Price {close:.2f} > EMA {ema:.2f}, "
                               f"SMA trend {'golden_cross' if golden_cross else 'bullish'}")
                    
                    signals.iloc[i, signals.columns.get_loc('signal')] = 1
                    signals.iloc[i, signals.columns.get_loc('entry_price')] = close
                    
                    # ATR-based TP/SL: sl_pips and tp_pips are ATR multipliers
                    atr = signals['atr'].iloc[i]
                    signals.iloc[i, signals.columns.get_loc('stop_loss')] = close - (self.sl_pips * atr)
                    signals.iloc[i, signals.columns.get_loc('take_profit')] = close + (self.tp_pips * atr)
                    
                    in_position = True
                    position_type = 1
                
                # SELL Signal: Multiple conditions
                # 1. Supertrend CHANGED to downtrend (prevents multiple signals in same trend)
                # 2. Price below EMA (short-term momentum)
                # 3. Either death cross OR fast SMA < slow SMA (trend strength)
                elif (trend_changed_to_down and 
                      close < ema and 
                      (death_cross or sma_fast < sma_slow)):
                    
                    logger.info(f"✅ [Strategy] SELL signal at i={i}: "
                               f"Price {close:.2f} < EMA {ema:.2f}, "
                               f"SMA trend {'death_cross' if death_cross else 'bearish'}")
                    
                    signals.iloc[i, signals.columns.get_loc('signal')] = -1
                    signals.iloc[i, signals.columns.get_loc('entry_price')] = close
                    
                    # ATR-based TP/SL: sl_pips and tp_pips are ATR multipliers
                    atr = signals['atr'].iloc[i]
                    signals.iloc[i, signals.columns.get_loc('stop_loss')] = close + (self.sl_pips * atr)
                    signals.iloc[i, signals.columns.get_loc('take_profit')] = close - (self.tp_pips * atr)
                    
                    in_position = True
                    position_type = -1
                elif trend_changed_to_up or trend_changed_to_down:
                    # Trend flipped but conditions not met - check if we should store in memory
                    flip_dir_str = "UP" if trend_changed_to_up else "DOWN"
                    flip_dir_num = 1 if trend_changed_to_up else -1
                    reasons = []
                    price_ema_ok = False
                    sma_ok = False
                    
                    if trend_changed_to_up:
                        price_ema_ok = close > ema
                        sma_ok = golden_cross or sma_fast > sma_slow
                        if not price_ema_ok:
                            reasons.append(f"Price {close:.2f} NOT > EMA {ema:.2f}")
                        if not sma_ok:
                            reasons.append(f"SMA not bullish (fast {sma_fast:.2f} NOT > slow {sma_slow:.2f})")
                    else:  # trend_changed_to_down
                        price_ema_ok = close < ema
                        sma_ok = death_cross or sma_fast < sma_slow
                        if not price_ema_ok:
                            reasons.append(f"Price {close:.2f} NOT < EMA {ema:.2f}")
                        if not sma_ok:
                            reasons.append(f"SMA not bearish (fast {sma_fast:.2f} NOT < slow {sma_slow:.2f})")
                    
                    # MEMORY SYSTEM: If flip + price/EMA aligned but SMA not ready, store in memory
                    if price_ema_ok and not sma_ok:
                        self.pending_flip = {
                            'direction': flip_dir_num,
                            'candle_idx': i,
                            'price': close,
                            'ema': ema,
                            'price_ema_aligned': True,
                            'max_wait': 10
                        }
                        logger.info(f"🧠 [Strategy] Supertrend flip {flip_dir_str} at i={i} - STORED IN MEMORY (Price/EMA aligned, waiting for SMA)")
                    else:
                        logger.info(f"⏭️ [Strategy] Supertrend flip {flip_dir_str} but NO SIGNAL at i={i}: {', '.join(reasons)}")
        
        # Update last processed index (only relevant in live mode)
        if live_mode:
            self.last_processed_index = len(signals)
        
        return signals
    
    def _flip_name(self, direction: int) -> str:
        """Helper to get flip direction name"""
        return "BUY" if direction == 1 else "SELL"
    
    def _check_pending_flip(self, i: int, signals: pd.DataFrame) -> int:
        """
        Check if pending flip should fire based on current SMA alignment
        
        Returns:
            1 for BUY signal, -1 for SELL signal, 0 for no signal
        """
        if self.pending_flip['direction'] is None:
            return 0  # No pending flip
        
        # Check timeout
        wait_time = i - self.pending_flip['candle_idx']
        if wait_time > self.pending_flip['max_wait']:
            logger.info(f"⏰ [Strategy] Pending {self._flip_name(self.pending_flip['direction'])} from candle {self.pending_flip['candle_idx']} TIMED OUT at i={i} (waited {wait_time} candles)")
            self.pending_flip['direction'] = None
            return 0
        
        # Get current values
        close = signals['close'].iloc[i]
        ema = signals['ema'].iloc[i]
        sma_fast = signals['sma_fast'].iloc[i]
        sma_slow = signals['sma_slow'].iloc[i]
        supertrend_dir = signals['direction'].iloc[i]
        
        # Check if Supertrend still in same direction
        if supertrend_dir != self.pending_flip['direction']:
            logger.info(f"⚠️ [Strategy] Pending {self._flip_name(self.pending_flip['direction'])} CANCELLED at i={i} - Supertrend reversed")
            self.pending_flip['direction'] = None
            return 0
        
        # Check if conditions now met
        if self.pending_flip['direction'] == 1:  # Pending BUY
            price_ema_ok = close > ema
            sma_ok = sma_fast > sma_slow
            
            if price_ema_ok and sma_ok:
                logger.info(f"✅ [Strategy] Pending BUY conditions met at i={i}: Price {close:.2f} > EMA {ema:.2f}, SMA bullish (fast {sma_fast:.2f} > slow {sma_slow:.2f})")
                return 1
            elif not price_ema_ok:
                # Price/EMA broke - invalidate
                logger.info(f"⚠️ [Strategy] Pending BUY INVALIDATED at i={i} - Price {close:.2f} fell below EMA {ema:.2f}")
                self.pending_flip['direction'] = None
                return 0
                
        else:  # Pending SELL (-1)
            price_ema_ok = close < ema
            sma_ok = sma_fast < sma_slow
            
            if price_ema_ok and sma_ok:
                logger.info(f"✅ [Strategy] Pending SELL conditions met at i={i}: Price {close:.2f} < EMA {ema:.2f}, SMA bearish (fast {sma_fast:.2f} < slow {sma_slow:.2f})")
                return -1
            elif not price_ema_ok:
                # Price/EMA broke - invalidate
                logger.info(f"⚠️ [Strategy] Pending SELL INVALIDATED at i={i} - Price {close:.2f} rose above EMA {ema:.2f}")
                self.pending_flip['direction'] = None
                return 0
        
        return 0  # Conditions not yet met, keep waiting
    
    def backtest(self, df: pd.DataFrame, initial_capital: float = 10000.0) -> Dict:
        """
        Run complete backtest with strategy
        
        Args:
            df: DataFrame with OHLCV data
            initial_capital: Starting capital in account currency
            
        Returns:
            Dict with backtest results
        """
        from backtester import IntraCandleBacktester, BacktestConfig
        
        # Calculate indicators
        logger.info("Calculating indicators...")
        df_with_indicators = self.calculate_indicators(df)
        
        # Generate signals
        logger.info("Generating signals...")
        signals = self.generate_signals(df_with_indicators)
        
        # Configure backtest
        config = BacktestConfig(
            initial_capital=initial_capital,
            spread_pips=2.0,  # Will be updated with real spread
            slippage_pips=0.5,
            pip_value=self.pip_value,
            position_size_pct=1.0,  # Use 100% of capital per trade
            max_positions=1  # One trade at a time
        )
        
        # Run backtest
        logger.info(f"Running backtest with initial capital: ${initial_capital:,.2f}")
        backtester = IntraCandleBacktester(config)
        results = backtester.run(signals)
        
        return results


class SentimentAwareStrategy(SupertrendVWAPStrategy):
    """
    Enhanced strategy with sentiment/news awareness
    Future integration for:
    - News events (economic calendar)
    - Twitter sentiment
    - Market regime detection
    """
    
    def __init__(self, *args, sentiment_weight: float = 0.2, **kwargs):
        """
        Args:
            sentiment_weight: How much to weight sentiment (0.0 to 1.0)
        """
        super().__init__(*args, **kwargs)
        self.sentiment_weight = sentiment_weight
    
    def get_news_sentiment(self, timestamp: pd.Timestamp, instrument: str) -> float:
        """
        Get news sentiment score for a given time/instrument
        
        TODO: Integrate with:
        - NewsAPI
        - Twitter API (X)
        - Economic calendar APIs
        - Fed speeches, central bank announcements
        
        Args:
            timestamp: Time to check sentiment
            instrument: Instrument to check (e.g., 'GOLD', 'EURUSD')
            
        Returns:
            Sentiment score: 1.0 (bullish) to -1.0 (bearish), 0.0 (neutral)
        """
        # Placeholder - implement real sentiment analysis
        return 0.0
    
    def get_market_regime(self, df: pd.DataFrame) -> str:
        """
        Detect current market regime
        
        Regimes:
        - trending_up: Strong uptrend
        - trending_down: Strong downtrend
        - ranging: Sideways/choppy
        - high_volatility: Volatile/unpredictable
        
        Args:
            df: DataFrame with price data
            
        Returns:
            Regime string
        """
        # Calculate recent volatility
        recent_close = df['close'].tail(20)
        volatility = recent_close.std() / recent_close.mean()
        
        # Calculate trend strength (ADX-like)
        recent_high = df['high'].tail(20).max()
        recent_low = df['low'].tail(20).min()
        current_close = df['close'].iloc[-1]
        
        range_pct = (recent_high - recent_low) / recent_low
        position_in_range = (current_close - recent_low) / (recent_high - recent_low) if recent_high != recent_low else 0.5
        
        if volatility > 0.02:  # 2% volatility threshold
            return 'high_volatility'
        elif position_in_range > 0.7 and range_pct > 0.01:
            return 'trending_up'
        elif position_in_range < 0.3 and range_pct > 0.01:
            return 'trending_down'
        else:
            return 'ranging'
    
    def adjust_signal_for_sentiment(self, signal: int, sentiment: float, regime: str) -> int:
        """
        Adjust trading signal based on sentiment and market regime
        
        Args:
            signal: Original signal (1, -1, or 0)
            sentiment: Sentiment score (-1.0 to 1.0)
            regime: Market regime string
            
        Returns:
            Adjusted signal
        """
        if signal == 0:
            return 0
        
        # Don't trade in high volatility
        if regime == 'high_volatility':
            logger.info("Skipping trade due to high volatility regime")
            return 0
        
        # Don't take buys in downtrend or sells in uptrend (unless sentiment very strong)
        if signal == 1 and regime == 'trending_down' and sentiment < 0.5:
            logger.info("Skipping buy signal - downtrend regime")
            return 0
        elif signal == -1 and regime == 'trending_up' and sentiment > -0.5:
            logger.info("Skipping sell signal - uptrend regime")
            return 0
        
        # Strong opposing sentiment cancels signal
        if signal == 1 and sentiment < -0.7:
            logger.info("Canceling buy signal - strong negative sentiment")
            return 0
        elif signal == -1 and sentiment > 0.7:
            logger.info("Canceling sell signal - strong positive sentiment")
            return 0
        
        return signal
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Generate signals with sentiment/regime awareness
        
        Args:
            df: DataFrame with indicators
            
        Returns:
            DataFrame with adjusted signals
        """
        # Get base signals from parent class
        signals = super().generate_signals(df)
        
        # Get market regime
        regime = self.get_market_regime(df)
        logger.info(f"Detected market regime: {regime}")
        
        # Adjust each signal based on sentiment/regime
        for i in range(len(signals)):
            if signals['signal'].iloc[i] != 0:
                timestamp = signals.index[i]
                sentiment = self.get_news_sentiment(timestamp, 'GOLD')  # TODO: pass instrument
                
                original_signal = signals['signal'].iloc[i]
                adjusted_signal = self.adjust_signal_for_sentiment(original_signal, sentiment, regime)
                
                if original_signal != adjusted_signal:
                    logger.info(f"Signal adjusted at {timestamp}: {original_signal} -> {adjusted_signal}")
                    signals.loc[i, 'signal'] = adjusted_signal
        
        return signals


if __name__ == '__main__':
    """Test strategy with real data"""
    import json
    import os
    from dotenv import load_dotenv
    from data_fetcher import CapitalComDataFetcher
    
    load_dotenv()
    secrets_str = os.getenv('apicredentials')
    
    if not secrets_str:
        print("\n❌ No credentials found in environment")
        print("\n💡 Create a .env file with your Capital.com credentials:")
        print("   cp .env.example .env")
        print("   Then edit .env and add: apicredentials='{\"apikey\":\"xxx\",...}'")
        exit(1)
    
    secrets = json.loads(secrets_str)
    
    # Initialize data fetcher
    fetcher = CapitalComDataFetcher(
        api_key=secrets.get('apikey', ''),
        username=secrets.get('username', ''),
        password=secrets.get('password', ''),
        capkey=secrets.get('capkey', '')
    )
    
    print("\n" + "="*70)
    print("Testing Strategy Implementation")
    print("="*70)
    
    # Fetch data
    print("\n📊 Fetching GOLD M15 data...")
    df = fetcher.fetch_and_cache('GOLD', 'M15', max_bars=1000)
    
    if df is None or len(df) == 0:
        print("❌ Failed to fetch data")
        exit(1)
    
    print(f"✅ Loaded {len(df)} bars")
    print(f"   Date range: {df.index[0]} to {df.index[-1]}")
    
    # Initialize strategy
    print("\n⚙️  Initializing strategy...")
    strategy = SupertrendVWAPStrategy(
        supertrend_period=10,
        supertrend_multiplier=3.0,
        sl_pips=20.0,
        tp_pips=40.0,
        pip_value=0.01  # Gold
    )
    
    # Calculate indicators
    print("\n📈 Calculating indicators...")
    df_with_indicators = strategy.calculate_indicators(df)
    print(f"✅ Calculated indicators:")
    print(f"   Supertrend: {df_with_indicators['supertrend'].iloc[-1]:.2f}")
    print(f"   VWAP: {df_with_indicators['vwap'].iloc[-1]:.2f}")
    print(f"   RSI: {df_with_indicators['rsi'].iloc[-1]:.1f}")
    
    # Generate signals
    print("\n🎯 Generating signals...")
    signals = strategy.generate_signals(df_with_indicators)
    
    buy_signals = (signals['signal'] == 1).sum()
    sell_signals = (signals['signal'] == -1).sum()
    
    print(f"✅ Generated signals:")
    print(f"   Buy signals: {buy_signals}")
    print(f"   Sell signals: {sell_signals}")
    print(f"   Total signals: {buy_signals + sell_signals}")
    
    if buy_signals + sell_signals > 0:
        print(f"\n📋 Last 3 signals:")
        signal_rows = signals[signals['signal'] != 0].tail(3)
        for idx, row in signal_rows.iterrows():
            signal_type = "BUY" if row['signal'] == 1 else "SELL"
            print(f"   {idx}: {signal_type} @ {row['entry_price']:.2f}, SL={row['stop_loss']:.2f}, TP={row['take_profit']:.2f}")
    
    print("\n" + "="*70)
    print("Strategy test completed!")
    print("="*70)
    print("\n💡 Next: Run full backtest with:")
    print("   python -c \"from strategy import SupertrendVWAPStrategy; strategy = SupertrendVWAPStrategy(); strategy.backtest(df, initial_capital=10000)\"")

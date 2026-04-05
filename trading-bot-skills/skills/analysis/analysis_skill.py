"""
Analysis Skill
Calculates technical indicators and generates trading signals.

EVENT-DRIVEN:
- Subscribes to: CANDLE_CLOSED
- Publishes: SIGNAL_GENERATED (when new signal detected)

ARCHITECTURE:
- All indicator math lives in core/indicators.py (pure functions, no state)
- All SL/TP math lives in core/sl_tp_engine.py (pure functions, dispatches by method)
- This skill owns: signal evaluation logic, edge detection, event publishing
- Signal rules are fully config-driven — no code change needed to tweak strategy
"""
from typing import Dict, List, Optional, Tuple, TYPE_CHECKING
import pandas as pd
import numpy as np
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from skills.base_skill import Skill, SkillExecutionError

if TYPE_CHECKING:
    from core.event_bus import EventBus, Event


def _normalize_ts(ts: pd.Timestamp, index: pd.Index) -> pd.Timestamp:
    """
    Align ts timezone to match the DataFrame index so .asof() doesn't raise.
    - If index is tz-aware and ts is tz-naive → localize ts to UTC.
    - If index is tz-naive and ts is tz-aware → strip ts timezone.
    """
    idx_tz = getattr(index, 'tz', None)
    if idx_tz is not None and ts.tz is None:
        return ts.tz_localize('UTC')
    if idx_tz is None and ts.tz is not None:
        return ts.tz_localize(None)
    return ts


class AnalysisSkill(Skill):
    """
    Analysis skill: computes indicators, evaluates signal, computes SL/TP, publishes event.

    Config keys (all under 'analysis' section or passed directly):
      indicators.supertrend.enabled / atr_period / multiplier
      indicators.ema.enabled / period
      indicators.sma.enabled / fast_period / slow_period
      indicators.vwap.enabled
      indicators.macd.enabled / fast / slow / signal_period
      indicators.rsi.enabled / period / overbought / oversold
      indicators.bollinger.enabled / period / std_dev
      indicators.stochastic.enabled / k_period / d_period / overbought / oversold
      indicators.volume.enabled / sma_period / min_ratio
      signal_rules.require_supertrend
      signal_rules.require_ema
      signal_rules.require_sma / strict_sma_cross
      signal_rules.require_vwap
      signal_rules.require_rsi
      signal_rules.require_macd
      signal_rules.require_bb
      signal_rules.require_stochastic
      signal_rules.require_volume
      signal_rules.edge_detection
      sl_tp.method  (fixed | atr | fibonacci | supertrend)
      sl_tp.*       (forwarded to sl_tp_engine.compute_sl_tp)
    """

    def __init__(self, config: Dict, event_bus: Optional['EventBus'] = None, market_data_skill=None):
        super().__init__(config, event_bus)
        self.market_data = market_data_skill

        ind = config.get('indicators', config)  # Fall back to top-level config if no 'indicators' key

        # -- Supertrend --------------------------------------------------------
        st = ind.get('supertrend', {})
        self.st_enabled    = st.get('enabled', True)
        self.st_period     = st.get('period', st.get('atr_period', 7))
        self.st_multiplier = st.get('multiplier', 2.0)

        # -- EMA ---------------------------------------------------------------
        ema = ind.get('ema', {})
        self.ema_enabled = ema.get('enabled', True)
        self.ema_period  = ema.get('period', 21)

        # -- SMA ---------------------------------------------------------------
        sma = ind.get('sma', {})
        self.sma_enabled     = sma.get('enabled', True)
        self.sma_fast_period = sma.get('fast_period', 25)
        self.sma_slow_period = sma.get('slow_period', 30)
        self.sma_fast        = self.sma_fast_period  # alias
        self.sma_slow        = self.sma_slow_period  # alias

        # -- VWAP --------------------------------------------------------------
        vwap = ind.get('vwap', {})
        self.vwap_enabled = vwap.get('enabled', False)

        # -- MACD --------------------------------------------------------------
        macd = ind.get('macd', {})
        self.macd_enabled       = macd.get('enabled', False)
        self.macd_fast          = macd.get('fast', 12)
        self.macd_slow          = macd.get('slow', 26)
        self.macd_signal_period = macd.get('signal_period', 9)

        # -- RSI ---------------------------------------------------------------
        rsi = ind.get('rsi', {})
        self.rsi_enabled    = rsi.get('enabled', False)
        self.rsi_period     = rsi.get('period', 14)
        self.rsi_overbought = rsi.get('overbought', 70)
        self.rsi_oversold   = rsi.get('oversold', 30)

        # -- Bollinger Bands ---------------------------------------------------
        bb = ind.get('bollinger', {})
        self.bb_enabled = bb.get('enabled', True)
        self.bb_period  = bb.get('period', 20)
        self.bb_std     = bb.get('std_dev', 2.0)

        # -- Stochastic --------------------------------------------------------
        stoch = ind.get('stochastic', {})
        self.stoch_enabled    = stoch.get('enabled', False)
        self.stoch_k_period   = stoch.get('k_period', 14)
        self.stoch_d_period   = stoch.get('d_period', 3)
        self.stoch_overbought = stoch.get('overbought', 80)
        self.stoch_oversold   = stoch.get('oversold', 20)

        # -- Volume ------------------------------------------------------------
        vol = ind.get('volume', {})
        self.vol_enabled    = vol.get('enabled', False)
        self.vol_sma_period = vol.get('sma_period', 20)
        self.vol_min_ratio  = vol.get('min_ratio', 1.2)

        # -- Signal rules (all AND) -------------------------------------------
        self.rules = config.get('signal_rules', {})

        # -- SL/TP config ------------------------------------------------------
        self.sl_tp_config = config.get('sl_tp', {
            'method': 'atr',
            'atr_sl_multiplier': 1.5,
            'atr_tp_multiplier': 3.0,
            'stop_loss_pips': 20,
            'take_profit_pips': 40,
            'risk_reward_ratio': 2.0,
            'swing_lookback': 20,
        })

        # -- Edge detection state ----------------------------------------------
        self.last_signal_state = None

        # Pre-computed indicators (set by backtest runner to avoid O(n²) per-candle recompute)
        self.precomputed_df: Optional[pd.DataFrame] = None

        # -- MTF Confluence (H1 + 4h + Daily BB) --------------------------------
        mtf = ind.get('mtf', {})
        self.mtf_h1_bb_period    = mtf.get('h1_bb_period', 20)
        self.mtf_h1_bb_std       = mtf.get('h1_bb_std', 2.0)
        self.mtf_h4_bb_period    = mtf.get('h4_bb_period', 20)
        self.mtf_h4_bb_std       = mtf.get('h4_bb_std', 2.0)
        self.mtf_daily_bb_period = mtf.get('daily_bb_period', 20)
        self.mtf_daily_bb_std    = mtf.get('daily_bb_std', 2.0)
        self.mtf_daily_sma       = mtf.get('daily_sma_period', 20)

        self.require_h1_bb      = self.rules.get('require_h1_bb', False)
        self.require_daily_bias = self.rules.get('require_daily_bias', False)
        self.block_ranging_days = self.rules.get('block_ranging_days', False)

        # H1 standalone BB band_pct thresholds:
        # Block BUY  when H1 band_pct > upper_block  → price near H1 upper band (resistance)
        # Block SELL when H1 band_pct < lower_block  → price near H1 lower band (support)
        self.h1_bb_upper_block = self.rules.get('h1_bb_upper_block', 0.75)
        self.h1_bb_lower_block = self.rules.get('h1_bb_lower_block', 0.25)

        # MTF confluence voting gate (H1 + 4h + Daily):
        # Each TF casts a vote if price is near a wall. Block if votes >= mtf_min_votes.
        self.require_mtf_bb      = self.rules.get('require_mtf_bb', False)
        self.mtf_min_votes       = self.rules.get('mtf_min_votes', 2)
        self.mtf_bb_upper_block  = self.rules.get('mtf_bb_upper_block', 0.75)
        self.mtf_bb_lower_block  = self.rules.get('mtf_bb_lower_block', 0.25)

        self.df_h1:    Optional[pd.DataFrame] = None  # set by backtest runner
        self.df_4h:    Optional[pd.DataFrame] = None  # set by backtest runner
        self.df_daily: Optional[pd.DataFrame] = None  # set by backtest runner
        self.mtf_rejections: Dict[str, int]   = {}   # reason → count

    async def execute(self, context) -> 'Context':
        """
        Context-pipeline path (sequential orchestrator).
        Computes indicators → evaluates signal → writes to context.
        """
        from skills.base_skill import Context
        if not self.market_data:
            return context

        candle_history = self.market_data.get_candle_history()
        min_bars = max(
            self.sma_slow_period, self.bb_period, self.st_period,
            self.macd_slow + self.macd_signal_period,
            self.rsi_period, self.stoch_k_period,
        ) + 5
        if not candle_history or len(candle_history) < min_bars:
            return context

        df = _to_dataframe(candle_history)
        df = self._compute_indicators(df)
        latest = df.iloc[-1]
        prev   = df.iloc[-2]

        ind = self._extract_indicators(df, latest, prev)
        if ind is None:
            return context

        signal = self._evaluate_signal(ind, latest, prev)
        if not signal:
            return context

        # Edge detection: only fire on state change
        if self.rules.get('edge_detection', True) and signal == self.last_signal_state:
            return context
        self.last_signal_state = signal

        entry_price = float(latest['close'])
        stop_loss, take_profit = self._compute_sl_tp(signal, entry_price, ind)

        context.signal       = signal
        context.entry_price  = entry_price
        context.stop_loss    = stop_loss
        context.take_profit  = take_profit
        return context

    async def on_candle_closed(self, event: 'Event') -> None:
        """Handle CANDLE_CLOSED: compute indicators → evaluate signal → publish."""
        if self.precomputed_df is not None:
            # Fast path: look up pre-computed row by candle timestamp
            candle_payload = event.payload.get('candle', {})
            ts = candle_payload.get('timestamp')
            try:
                ts_key = pd.Timestamp(ts)
                if ts_key in self.precomputed_df.index:
                    latest = self.precomputed_df.loc[ts_key]
                    iloc_pos = self.precomputed_df.index.get_loc(ts_key)
                    if iloc_pos < 1:
                        return
                    prev = self.precomputed_df.iloc[iloc_pos - 1]
                    df = self.precomputed_df.iloc[max(0, iloc_pos - 100): iloc_pos + 1]
                else:
                    return
            except Exception:
                return
        else:
            # Live path: recompute on rolling buffer
            if not self.market_data:
                return
            candle_history = self.market_data.get_candle_history()
            min_bars = max(self.sma_slow_period, self.bb_period, self.st_period,
                           self.macd_slow + self.macd_signal_period,
                           self.rsi_period, self.stoch_k_period) + 5
            if not candle_history or len(candle_history) < min_bars:
                return
            df = _to_dataframe(candle_history)
            df = self._compute_indicators(df)
            latest = df.iloc[-1]
            prev   = df.iloc[-2]

        ind = self._extract_indicators(df, latest, prev)
        if ind is None:
            return  # NaN in required indicators

        signal = self._evaluate_signal(ind, latest, prev)
        if not signal:
            return

        # Edge detection: only publish on signal state change
        if self.rules.get('edge_detection', True) and signal == self.last_signal_state:
            return
        self.last_signal_state = signal

        entry_price = float(latest['close'])
        stop_loss, take_profit = self._compute_sl_tp(signal, entry_price, ind)

        # Candle timestamp for RiskSkill trading-hours check
        candle_timestamp = latest.name if hasattr(latest, 'name') else None

        if self.event_bus:
            from core.event_bus import create_signal_generated_event
            await self.event_bus.publish(
                create_signal_generated_event(
                    signal=signal,
                    entry_price=entry_price,
                    sl=stop_loss,
                    tp=take_profit,
                    instrument=event.instrument,
                    timestamp=candle_timestamp,
                )
            )

    # ------------------------------------------------------------------
    # Indicator computation
    # ------------------------------------------------------------------

    def _compute_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Delegate all indicator math to core/indicators.py pure functions."""
        from core.indicators import (
            calculate_atr, calculate_supertrend,
            calculate_ema, calculate_sma,
            calculate_vwap_daily,
            calculate_macd,
            calculate_rsi,
            calculate_bollinger_bands,
            calculate_stochastic,
        )

        # ATR — always needed (SL/TP + Supertrend). Pass full df.
        df['atr'] = calculate_atr(df, self.st_period)

        if self.st_enabled:
            df['supertrend'], df['supertrend_direction'] = calculate_supertrend(
                df, self.st_period, self.st_multiplier)

        if self.ema_enabled:
            df['ema'] = calculate_ema(df['close'], self.ema_period)

        if self.sma_enabled:
            df['sma_fast'] = calculate_sma(df['close'], self.sma_fast_period)
            df['sma_slow'] = calculate_sma(df['close'], self.sma_slow_period)

        if self.vwap_enabled:
            df['vwap'] = calculate_vwap_daily(df)

        if self.macd_enabled:
            df['macd'], df['macd_signal'], df['macd_hist'] = calculate_macd(
                df['close'], self.macd_fast, self.macd_slow, self.macd_signal_period)

        if self.rsi_enabled:
            df['rsi'] = calculate_rsi(df['close'], self.rsi_period)

        if self.bb_enabled:
            df['bb_upper'], df['bb_middle'], df['bb_lower'] = calculate_bollinger_bands(
                df['close'], self.bb_period, self.bb_std)

        if self.stoch_enabled:
            df['stoch_k'], df['stoch_d'] = calculate_stochastic(
                df, self.stoch_k_period, self.stoch_d_period)

        if self.vol_enabled and 'volume' in df.columns:
            vol_sma = df['volume'].rolling(self.vol_sma_period, min_periods=self.vol_sma_period).mean()
            df['vol_sma']   = vol_sma
            df['vol_ratio'] = df['volume'] / vol_sma.replace(0, np.nan)

        return df

    def _extract_indicators(self, df: pd.DataFrame, latest, prev) -> Optional[Dict]:
        """
        Extract indicator values into a flat dict.  Returns None if any
        *required* (enabled) indicator is still NaN on the latest bar.
        """
        ind: Dict = {'current_price': float(latest['close'])}

        # ATR — always required
        if 'atr' not in df.columns or pd.isna(latest['atr']):
            return None
        ind['atr'] = float(latest['atr'])

        if self.st_enabled:
            if pd.isna(latest.get('supertrend')):
                return None
            ind['supertrend']           = float(latest['supertrend'])
            ind['supertrend_direction'] = int(latest['supertrend_direction'])

        if self.ema_enabled:
            if pd.isna(latest.get('ema')):
                return None
            ind['ema'] = float(latest['ema'])

        if self.sma_enabled:
            if pd.isna(latest.get('sma_fast')) or pd.isna(latest.get('sma_slow')):
                return None
            ind['sma_fast']      = float(latest['sma_fast'])
            ind['sma_slow']      = float(latest['sma_slow'])
            ind['sma_fast_prev'] = float(prev['sma_fast']) if not pd.isna(prev.get('sma_fast')) else ind['sma_fast']
            ind['sma_slow_prev'] = float(prev['sma_slow']) if not pd.isna(prev.get('sma_slow')) else ind['sma_slow']

        if self.vwap_enabled and 'vwap' in df.columns:
            ind['vwap'] = float(latest['vwap']) if not pd.isna(latest['vwap']) else None

        if self.macd_enabled and 'macd' in df.columns:
            if pd.isna(latest.get('macd')):
                return None
            ind['macd']        = float(latest['macd'])
            ind['macd_signal'] = float(latest['macd_signal'])
            ind['macd_hist']   = float(latest['macd_hist'])
            ind['macd_hist_prev'] = float(prev['macd_hist']) if not pd.isna(prev.get('macd_hist')) else 0.0

        if self.rsi_enabled and 'rsi' in df.columns:
            if pd.isna(latest.get('rsi')):
                return None
            ind['rsi'] = float(latest['rsi'])

        if self.bb_enabled and 'bb_upper' in df.columns:
            if pd.isna(latest.get('bb_upper')):
                return None
            ind['bb_upper']  = float(latest['bb_upper'])
            ind['bb_middle'] = float(latest['bb_middle'])
            ind['bb_lower']  = float(latest['bb_lower'])

        if self.stoch_enabled and 'stoch_k' in df.columns:
            if pd.isna(latest.get('stoch_k')):
                return None
            ind['stoch_k'] = float(latest['stoch_k'])
            ind['stoch_d'] = float(latest['stoch_d'])

        if self.vol_enabled and 'vol_ratio' in df.columns:
            ind['vol_ratio'] = float(latest['vol_ratio']) if not pd.isna(latest.get('vol_ratio')) else 0.0

        # Swing high/low for Fibonacci SL/TP (last N bars)
        lookback = self.sl_tp_config.get('swing_lookback', 20)
        swing_slice = df.iloc[-lookback:]
        ind['swing_high'] = float(swing_slice['high'].max())
        ind['swing_low']  = float(swing_slice['low'].min())

        return ind

    # ------------------------------------------------------------------
    # Signal evaluation  (AND logic — every enabled rule must pass)
    # ------------------------------------------------------------------

    def _evaluate_signal(self, ind: Dict, latest, prev) -> Optional[str]:
        """
        Evaluate all enabled indicator rules.  ALL must agree on direction.
        Returns 'BUY', 'SELL', or None.
        """
        close = ind['current_price']

        # Collect per-rule verdicts
        buy_votes  = []
        sell_votes = []

        # --- Supertrend ---
        if self.rules.get('require_supertrend', True) and self.st_enabled:
            d = ind.get('supertrend_direction', 0)
            buy_votes.append(d == 1)
            sell_votes.append(d == -1)

        # --- EMA ---
        if self.rules.get('require_ema', True) and self.ema_enabled:
            ema = ind.get('ema', close)
            buy_votes.append(close > ema)
            sell_votes.append(close < ema)

        # --- SMA crossover / trend ---
        if self.rules.get('require_sma', True) and self.sma_enabled:
            sf, ss = ind['sma_fast'], ind['sma_slow']
            sfp, ssp = ind['sma_fast_prev'], ind['sma_slow_prev']
            if self.rules.get('strict_sma_cross', False):
                # Only on the crossover candle
                golden = (sf > ss) and (sfp <= ssp)
                death  = (sf < ss) and (sfp >= ssp)
                buy_votes.append(golden)
                sell_votes.append(death)
            else:
                # Trend direction is enough
                buy_votes.append(sf > ss)
                sell_votes.append(sf < ss)

        # --- VWAP ---
        if self.rules.get('require_vwap', False) and self.vwap_enabled:
            vwap = ind.get('vwap')
            if vwap:
                buy_votes.append(close > vwap)
                sell_votes.append(close < vwap)

        # --- RSI ---
        if self.rules.get('require_rsi', False) and self.rsi_enabled:
            rsi = ind.get('rsi', 50)
            buy_votes.append(rsi < self.rsi_overbought)   # not overbought
            sell_votes.append(rsi > self.rsi_oversold)    # not oversold

        # --- MACD ---
        if self.rules.get('require_macd', False) and self.macd_enabled:
            hist      = ind.get('macd_hist', 0)
            hist_prev = ind.get('macd_hist_prev', 0)
            buy_votes.append(hist > 0 or (hist > hist_prev))   # positive or rising
            sell_votes.append(hist < 0 or (hist < hist_prev))  # negative or falling

        # --- Bollinger Bands ---
        if self.rules.get('require_bb', False) and self.bb_enabled:
            upper  = ind.get('bb_upper', close)
            lower  = ind.get('bb_lower', close)
            middle = ind.get('bb_middle', close)
            buy_votes.append(close > middle and close < upper)   # inside upper half
            sell_votes.append(close < middle and close > lower)  # inside lower half

        # --- Stochastic ---
        if self.rules.get('require_stochastic', False) and self.stoch_enabled:
            k = ind.get('stoch_k', 50)
            buy_votes.append(k < self.stoch_overbought)
            sell_votes.append(k > self.stoch_oversold)

        # --- Volume confirmation ---
        if self.rules.get('require_volume', False) and self.vol_enabled:
            ratio = ind.get('vol_ratio', 1.0)
            buy_votes.append(ratio >= self.vol_min_ratio)
            sell_votes.append(ratio >= self.vol_min_ratio)

        if not buy_votes:   # no rules configured at all
            return None

        if all(buy_votes):
            signal = 'BUY'
        elif all(sell_votes):
            signal = 'SELL'
        else:
            return None

        # -- MTF Confluence gate (H1 BB zone + MTF voting + Daily SMA bias) -----
        if self.require_h1_bb or self.require_mtf_bb or self.require_daily_bias:
            ts = latest.name if hasattr(latest, 'name') else None
            if ts is not None:
                ok, reason = self._check_mtf_confluence(pd.Timestamp(ts), signal)
                if not ok:
                    self.mtf_rejections[reason] = self.mtf_rejections.get(reason, 0) + 1
                    return None

        return signal

    # ------------------------------------------------------------------
    # MTF Confluence gate  (H1 BB zone + Daily SMA bias)
    # ------------------------------------------------------------------

    def _check_mtf_confluence(self, ts: pd.Timestamp, direction: str) -> Tuple[bool, str]:
        """
        Lookahead-safe multi-timeframe check using .asof() on pre-indexed frames.
        Returns (allowed, rejection_reason).
        """
        # -- H1 Bollinger Band location gate --
        # Concept: BB lines are price levels, not trend filters.
        # BUY  is blocked when H1 price is near the H1 upper band (resistance overhead).
        # SELL is blocked when H1 price is near the H1 lower band (support below).
        # band_pct = (close - lower) / (upper - lower)
        #   > h1_bb_upper_block (default 0.75) → price in upper zone → resistance nearby → block BUY
        #   < h1_bb_lower_block (default 0.25) → price in lower zone → support nearby  → block SELL
        if self.require_h1_bb and self.df_h1 is not None:
            try:
                # Subtract 1h to get the *previously completed* H1 bar (avoid look-ahead).
                ts_h1    = _normalize_ts(ts - pd.Timedelta(hours=1), self.df_h1.index)
                h1_row   = self.df_h1.asof(ts_h1)
                h1_upper = h1_row.get('h1_bb_upper', np.nan)
                h1_lower = h1_row.get('h1_bb_lower', np.nan)
                h1_close = h1_row.get('close',        np.nan)
                if not any(pd.isna(x) for x in [h1_upper, h1_lower, h1_close]):
                    band_width = h1_upper - h1_lower
                    if band_width > 0:
                        band_pct = (h1_close - h1_lower) / band_width
                        if direction == 'BUY'  and band_pct > self.h1_bb_upper_block:
                            return False, 'h1_near_upper_resistance'
                        if direction == 'SELL' and band_pct < self.h1_bb_lower_block:
                            return False, 'h1_near_lower_support'
            except Exception:
                pass  # Don't block if lookup fails

        # -- MTF BB confluence voting gate --
        # Each available TF (H1, 4h, Daily) votes whether price is near a wall.
        # Signal is blocked when votes >= mtf_min_votes.
        if self.require_mtf_bb:
            votes = 0
            available = 0

            def _band_pct_vote(df_tf, offset_hours, upper_col, lower_col):
                """Returns 1 if this TF votes to block, 0 otherwise. Returns None if data unavailable."""
                try:
                    ts_tf = _normalize_ts(ts - pd.Timedelta(hours=offset_hours), df_tf.index)
                    row   = df_tf.asof(ts_tf)
                    upper = row.get(upper_col, np.nan)
                    lower = row.get(lower_col, np.nan)
                    close = row.get('close', np.nan)
                    if any(pd.isna(x) for x in [upper, lower, close]):
                        return None
                    bw = upper - lower
                    if bw <= 0:
                        return None
                    bp = (close - lower) / bw
                    if direction == 'BUY'  and bp > self.mtf_bb_upper_block:
                        return 1
                    if direction == 'SELL' and bp < self.mtf_bb_lower_block:
                        return 1
                    return 0
                except Exception:
                    return None

            if self.df_h1 is not None:
                v = _band_pct_vote(self.df_h1, 1, 'h1_bb_upper', 'h1_bb_lower')
                if v is not None:
                    available += 1
                    votes += v

            if self.df_4h is not None:
                v = _band_pct_vote(self.df_4h, 4, 'h4_bb_upper', 'h4_bb_lower')
                if v is not None:
                    available += 1
                    votes += v

            if self.df_daily is not None and 'daily_bb_upper' in self.df_daily.columns:
                v = _band_pct_vote(self.df_daily, 24, 'daily_bb_upper', 'daily_bb_lower')
                if v is not None:
                    available += 1
                    votes += v

            if available > 0 and votes >= self.mtf_min_votes:
                return False, f'mtf_bb_blocked_{votes}of{available}'

        # -- Daily SMA bias --
        if self.require_daily_bias and self.df_daily is not None:
            try:
                ts_d = _normalize_ts(ts, self.df_daily.index)
                d_row       = self.df_daily.asof(ts_d, subset=['close', 'daily_sma'])
                daily_sma   = d_row.get('daily_sma', np.nan)
                daily_close = d_row.get('close',     np.nan)
                if not pd.isna(daily_sma) and not pd.isna(daily_close):
                    if direction == 'BUY'  and daily_close < daily_sma:
                        return False, 'daily_bias_bearish'
                    if direction == 'SELL' and daily_close > daily_sma:
                        return False, 'daily_bias_bullish'
            except Exception:
                pass

        return True, 'ok'

    # ------------------------------------------------------------------
    # MTF data loaders  (called from main.py during warm-up and live updates)
    # ------------------------------------------------------------------

    def load_h1_history(self, candles: list) -> None:
        """
        Build df_h1 from a list of H1 OHLC candle dicts.
        Called once at warm-up with ~60 historical H1 bars, then appended
        live via update_h1_candle() each time a new H1 bar closes.
        """
        if not candles:
            return
        df = pd.DataFrame(candles)
        df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True)
        df = df.set_index('timestamp').sort_index()
        df = df[~df.index.duplicated(keep='last')]

        from core.indicators import calculate_bollinger_bands
        df['h1_bb_middle'], df['h1_bb_upper'], df['h1_bb_lower'] = \
            calculate_bollinger_bands(df['close'], self.mtf_h1_bb_period, self.mtf_h1_bb_std)

        self.df_h1 = df
        import logging
        logging.getLogger(__name__).info(
            f"✅ H1 BB loaded: {len(df)} bars, "
            f"latest={df.index[-1].isoformat() if len(df) else 'n/a'}"
        )

    def update_h1_candle(self, candle: dict) -> None:
        """
        Append a single live H1 candle and recompute BB.
        Called from the WebSocket H1 candle callback.
        """
        if self.df_h1 is None:
            return
        ts = pd.to_datetime(candle['timestamp'], utc=True)
        row = pd.DataFrame([{
            'open':  candle.get('open',  0),
            'high':  candle.get('high',  0),
            'low':   candle.get('low',   0),
            'close': candle.get('close', 0),
        }], index=[ts])
        self.df_h1 = pd.concat([self.df_h1, row])
        self.df_h1 = self.df_h1[~self.df_h1.index.duplicated(keep='last')].sort_index()

        from core.indicators import calculate_bollinger_bands
        self.df_h1['h1_bb_middle'], self.df_h1['h1_bb_upper'], self.df_h1['h1_bb_lower'] = \
            calculate_bollinger_bands(self.df_h1['close'], self.mtf_h1_bb_period, self.mtf_h1_bb_std)

    def load_daily_history(self, candles: list) -> None:
        """
        Build df_daily from a list of Daily OHLC candle dicts.
        Called once at warm-up with ~30 daily bars.
        Daily data changes slowly — no live update needed (re-fetch each day).
        """
        if not candles:
            return
        df = pd.DataFrame(candles)
        df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True)
        df = df.set_index('timestamp').sort_index()
        df = df[~df.index.duplicated(keep='last')]

        from core.indicators import calculate_sma
        df['daily_sma'] = calculate_sma(df['close'], self.mtf_daily_sma)

        self.df_daily = df
        import logging
        logging.getLogger(__name__).info(
            f"✅ Daily SMA loaded: {len(df)} bars, "
            f"latest={df.index[-1].isoformat() if len(df) else 'n/a'}"
        )

    # ------------------------------------------------------------------
    # SL/TP  (delegates entirely to sl_tp_engine)
    # ------------------------------------------------------------------

    def _compute_sl_tp(self, signal: str, entry_price: float, ind: Dict) -> Tuple[float, float]:
        """Compute stop-loss and take-profit using sl_tp_engine dispatcher."""
        from core.sl_tp_engine import compute_sl_tp
        return compute_sl_tp(
            signal=signal,
            entry_price=entry_price,
            sl_tp_config=self.sl_tp_config,
            atr=ind.get('atr'),
            supertrend_value=ind.get('supertrend'),
            swing_high=ind.get('swing_high'),
            swing_low=ind.get('swing_low'),
        )

    def validate_config(self) -> bool:
        """Validate configuration."""
        if self.st_enabled and (self.st_period < 1 or self.st_multiplier <= 0):
            raise SkillExecutionError("Invalid Supertrend parameters")
        if self.sma_enabled and (self.sma_fast_period < 1 or self.sma_slow_period < 1):
            raise SkillExecutionError("Invalid SMA parameters")
        return True


# ---------------------------------------------------------------------------
# Module-level helper (shared with backtester)
# ---------------------------------------------------------------------------

def _to_dataframe(candle_history: List[Dict]) -> pd.DataFrame:
    """Convert a list of candle dicts to a DatetimeIndex DataFrame."""
    df = pd.DataFrame(candle_history)
    if 'timestamp' in df.columns:
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df.set_index('timestamp', inplace=True)
    for col in ('open', 'high', 'low', 'close'):
        df[col] = pd.to_numeric(df[col], errors='coerce')
    if 'volume' in df.columns:
        df['volume'] = pd.to_numeric(df['volume'], errors='coerce').fillna(0)
    return df

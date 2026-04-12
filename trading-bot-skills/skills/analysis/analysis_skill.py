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
        # Directional bias MA: close > bias_ma → BUY only; close < bias_ma → SELL only
        self.sma_bias_period  = sma.get('bias_period', 100)
        self.sma_bias_enabled = sma.get('bias_enabled', False)
        # Slope filter: MA must also be pointing in the signal direction
        # slope = MA[now] - MA[now - slope_lookback]; positive = rising, negative = falling
        self.sma_bias_slope_bars    = sma.get('bias_slope_bars', 0)   # 0 = disabled

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

        # -- ADX ---------------------------------------------------------------
        adx = ind.get('adx', {})
        self.adx_enabled   = adx.get('enabled', False)
        self.adx_period    = adx.get('period', 14)
        self.adx_threshold = adx.get('threshold', 25)   # <threshold = ranging, skip signal
        self.adx_di_filter = adx.get('di_filter', False) # also require DI+>DI- for BUY etc.

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

        # -- M1 exit -----------------------------------------------------------
        m1_cfg = ind.get('m1_exit', config.get('m1_exit', {}))
        self.m1_exit_enabled   = m1_cfg.get('enabled', False)
        self.m1_st_period      = m1_cfg.get('atr_period', 14)
        self.m1_st_multiplier  = m1_cfg.get('multiplier', 1.5)

        # -- Tick exit (profit-based interval) ---------------------------------
        # Levels sorted ascending by min_profit_pips.
        # Each level: {'min_profit_pips': N, 'check_interval_sec': S}
        # S=0 means check every tick.
        te_cfg = config.get('tick_exit', {})
        self.tick_exit_enabled = te_cfg.get('enabled', False)
        raw_levels = te_cfg.get('levels', [])
        self._tick_exit_levels = sorted(raw_levels, key=lambda x: x['min_profit_pips'])
        # pip_size: main.py propagates risk.pip_size → analysis.sl_tp.pip_size
        self._pip_size = config.get('sl_tp', {}).get('pip_size', config.get('pip_size', 1.0))
        # Reverse-on-loss: close + open opposite when in a loss and ST + MA100 both agree
        self.tick_reverse_on_loss    = te_cfg.get('reverse_on_loss', False)
        self.tick_loss_check_interval = float(te_cfg.get('loss_check_interval_sec', 180))

        # Position state — set by backtesting/orchestrator after a trade opens/closes.
        # Used by on_m1_candle_closed to know whether to look for an exit.
        self.current_position:    Optional[str]   = None   # 'BUY', 'SELL', or None
        self.current_entry_price: Optional[float] = None
        self.current_sl:          Optional[float] = None
        self.current_tp:          Optional[float] = None

        # Live tick exit: Supertrend trailing stop from last M5 candle close.
        # BUY → exit if tick price < st_lower; SELL → exit if tick price > st_upper.
        self.current_st_trail:    Optional[float] = None
        self._tick_exit_fired:    bool            = False  # prevent duplicate exits per bar
        self._last_tick_check_ts: Optional[float] = None  # epoch seconds of last check
        # Latest MA100 value — updated every M5 candle close, used for reverse-on-loss bias check.
        self.current_sma_bias:    Optional[float] = None

        # Rolling M1 candle buffer for ST computation
        self._m1_buffer:   list         = []
        self._m1_prev_dir: Optional[int] = None   # last confirmed M1 ST direction

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

        # Update Supertrend trailing stop and MA100 for live tick exit.
        # Reset tick-exit-fired flag so a new bar allows a fresh check.
        if self.current_position == 'BUY':
            self.current_st_trail = ind.get('st_lower')
        elif self.current_position == 'SELL':
            self.current_st_trail = ind.get('st_upper')
        self.current_sma_bias = ind.get('sma_bias')  # always update, used by reverse-on-loss
        self._tick_exit_fired = False

        # Check SL/TP on M5 bar for open position (fallback when M1 exit unavailable)
        if self.current_position and self.event_bus:
            candle_payload = event.payload.get('candle', {})
            high = float(candle_payload.get('high', 0))
            low  = float(candle_payload.get('low',  0))
            ts   = candle_payload.get('timestamp')
            exit_reason: Optional[str] = None
            exit_price_val: float = 0.0

            if self.current_sl is not None:
                if self.current_position == 'BUY'  and low  <= self.current_sl:
                    exit_reason, exit_price_val = 'SL_HIT', self.current_sl
                elif self.current_position == 'SELL' and high >= self.current_sl:
                    exit_reason, exit_price_val = 'SL_HIT', self.current_sl

            if exit_reason is None and self.current_tp is not None:
                if self.current_position == 'BUY'  and high >= self.current_tp:
                    exit_reason, exit_price_val = 'TP_HIT', self.current_tp
                elif self.current_position == 'SELL' and low  <= self.current_tp:
                    exit_reason, exit_price_val = 'TP_HIT', self.current_tp

            if exit_reason:
                from core.event_bus import Event as _Evt, EventType as _ET
                await self.event_bus.publish(_Evt(
                    event_type=_ET.EXIT_SIGNAL,
                    instrument=event.instrument,
                    source='analysis_m5_sltp',
                    payload={'reason': exit_reason, 'exit_price': exit_price_val,
                             'candle': candle_payload, 'timestamp': ts}
                ))
                return  # don't also generate entry signal on exit bar

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
    # Position state — called by backtest runner / live orchestrator
    # ------------------------------------------------------------------

    def register_open_position(self, side: str, entry_price: float,
                                sl: float = None, tp: float = None) -> None:
        """Record an open position so M1 exit checks have context."""
        self.current_position    = side
        self.current_entry_price = entry_price
        self.current_sl          = sl
        self.current_tp          = tp
        self._m1_prev_dir        = None   # reset: skip first M1 bar to avoid stale direction

    def clear_position(self) -> None:
        """Clear position state after a trade closes."""
        self.current_position    = None
        self.current_entry_price = None
        self.current_sl          = None
        self.current_tp          = None
        self.current_st_trail    = None
        self._tick_exit_fired    = False
        self._last_tick_check_ts = None
        self._m1_prev_dir        = None

    # ------------------------------------------------------------------
    # Live tick exit — fires on each incoming bid/ask quote
    # ------------------------------------------------------------------

    def _tick_check_interval_sec(self, price: float) -> float:
        """
        Return how many seconds must have elapsed since the last Supertrend
        check before we look again.  Interval shrinks as unrealised profit grows.

        Uses self._tick_exit_levels (sorted ascending by min_profit_pips).
        Returns 0 if tick-based (no throttle).  Returns float('inf') if tick
        exit is disabled or no position is open.

        When in a loss and reverse_on_loss is enabled, returns
        tick_loss_check_interval instead of inf.
        """
        if not self.tick_exit_enabled or not self.current_position or self.current_entry_price is None:
            return float('inf')

        pip = self._pip_size or 1.0
        pnl_pips = (
            (price - self.current_entry_price) / pip if self.current_position == 'BUY'
            else (self.current_entry_price - price) / pip
        )

        # Loss side: only check if reverse-on-loss is enabled
        if pnl_pips < 0:
            return self.tick_loss_check_interval if self.tick_reverse_on_loss else float('inf')

        interval = float('inf')  # no check if no level matches profit thresholds
        for lvl in self._tick_exit_levels:
            if pnl_pips >= lvl['min_profit_pips']:
                interval = float(lvl['check_interval_sec'])
        return interval

    async def on_price_tick(self, price: float, timestamp=None) -> None:
        """
        Called on every live bid/ask tick.  Exits the open position if the
        current price crosses the Supertrend trailing stop (trend reversed).

        Check frequency is profit-dependent (configured via tick_exit.levels):
          - Small/no profit  → check every 3 min (breathing room)
          - Growing profit   → tighten to 2 min, 1 min
          - Target profit    → check every tick (lock in gains)

        Fires at most once per M5 bar (reset on candle close).
        """
        import time as _time

        if not self.current_position or self.current_st_trail is None:
            return
        if self._tick_exit_fired:
            return

        # --- Profit-based throttle -------------------------------------------
        interval = self._tick_check_interval_sec(price)
        if interval == float('inf'):
            return  # tick exit disabled or not applicable

        now = _time.monotonic()
        if interval > 0 and self._last_tick_check_ts is not None:
            if (now - self._last_tick_check_ts) < interval:
                return  # too soon

        self._last_tick_check_ts = now

        # --- Supertrend trail check ------------------------------------------
        crossed = (
            (self.current_position == 'BUY'  and price < self.current_st_trail) or
            (self.current_position == 'SELL' and price > self.current_st_trail)
        )
        if not crossed:
            return

        self._tick_exit_fired = True  # suppress further ticks this bar

        # --- Determine whether to reverse (close + open opposite) -----------
        pip = self._pip_size or 1.0
        pnl_pips = (
            (price - self.current_entry_price) / pip if self.current_position == 'BUY'
            else (self.current_entry_price - price) / pip
        )
        in_loss = pnl_pips < 0

        reverse_signal = None
        if in_loss and self.tick_reverse_on_loss and self.current_sma_bias is not None:
            reverse_to = 'SELL' if self.current_position == 'BUY' else 'BUY'
            # Only reverse if MA100 bias agrees with the new direction
            bias_agrees = (
                (reverse_to == 'SELL' and price < self.current_sma_bias) or
                (reverse_to == 'BUY'  and price > self.current_sma_bias)
            )
            if bias_agrees:
                reverse_signal = reverse_to

        if not self.event_bus:
            return

        from core.event_bus import Event as _Evt, EventType as _ET
        from core.event_bus import create_signal_generated_event

        # Always exit the current position first
        await self.event_bus.publish(_Evt(
            event_type=_ET.EXIT_SIGNAL,
            source='analysis_tick',
            payload={
                'reason': 'ST_TICK_REVERSE' if reverse_signal else 'ST_TICK_EXIT',
                'exit_price': price,
                'timestamp': timestamp,
            }
        ))

        # If bias agrees, immediately open the reverse position
        if reverse_signal:
            sl_pips = self.sl_tp_config.get('stop_loss_pips', 20)
            tp_pips = self.sl_tp_config.get('take_profit_pips', 40)
            if reverse_signal == 'BUY':
                sl = price - sl_pips * pip
                tp = price + tp_pips * pip
            else:
                sl = price + sl_pips * pip
                tp = price - tp_pips * pip

            await self.event_bus.publish(
                create_signal_generated_event(
                    signal=reverse_signal,
                    entry_price=price,
                    sl=sl,
                    tp=tp,
                    instrument=None,
                    timestamp=timestamp,
                )
            )

    # ------------------------------------------------------------------
    # M1 candle handler — exit signal generation
    # ------------------------------------------------------------------

    async def on_m1_candle_closed(self, event: 'Event') -> None:
        """
        Handle M1_CANDLE_CLOSED.
        Maintains a rolling M1 buffer, computes M1 Supertrend, and publishes
        EXIT_SIGNAL when:
          - SL is breached (bar low/high crosses stop level), OR
          - TP is reached, OR
          - M1 ST direction flips against the current position.
        Does nothing if m1_exit_enabled is False or no position is open.
        """
        candle = event.payload.get('candle', {})

        # Always maintain the buffer (needed for ST warmup even before first trade)
        self._m1_buffer.append(candle)
        max_buf = self.m1_st_period * 6
        if len(self._m1_buffer) > max_buf:
            self._m1_buffer = self._m1_buffer[-max_buf:]

        if not self.m1_exit_enabled:
            return

        # Need minimum bars for ST to produce valid output
        if len(self._m1_buffer) < self.m1_st_period + 2:
            return

        # Compute M1 Supertrend on rolling buffer
        from core.indicators import calculate_supertrend as _st
        df_m1 = _to_dataframe(self._m1_buffer)
        _, m1_dir_series, _, _ = _st(df_m1, self.m1_st_period, self.m1_st_multiplier)
        curr_dir = int(m1_dir_series.iloc[-1])

        prev_dir = self._m1_prev_dir
        self._m1_prev_dir = curr_dir

        # Nothing to check if no open position
        if not self.current_position:
            return

        exit_reason: Optional[str] = None
        exit_price = float(candle.get('close', 0))
        high = float(candle.get('high', 0))
        low  = float(candle.get('low',  0))

        # 1. SL check (hard stop — takes priority)
        if self.current_sl is not None:
            if self.current_position == 'BUY'  and low  <= self.current_sl:
                exit_reason = 'SL_HIT'
                exit_price  = self.current_sl
            elif self.current_position == 'SELL' and high >= self.current_sl:
                exit_reason = 'SL_HIT'
                exit_price  = self.current_sl

        # 2. TP check
        if exit_reason is None and self.current_tp is not None:
            if self.current_position == 'BUY'  and high >= self.current_tp:
                exit_reason = 'TP_HIT'
                exit_price  = self.current_tp
            elif self.current_position == 'SELL' and low  <= self.current_tp:
                exit_reason = 'TP_HIT'
                exit_price  = self.current_tp

        # 3. M1 ST reversal — only on a genuine direction flip (skip first bar after entry)
        if exit_reason is None and prev_dir is not None and curr_dir != prev_dir:
            if (self.current_position == 'BUY'  and curr_dir == -1) or \
               (self.current_position == 'SELL' and curr_dir ==  1):
                exit_reason = 'M1_ST_REVERSAL'
                exit_price  = float(candle.get('close', 0))

        if exit_reason and self.event_bus:
            from core.event_bus import Event as _Evt, EventType as _ET
            await self.event_bus.publish(_Evt(
                event_type=_ET.EXIT_SIGNAL,
                instrument=event.instrument,
                source='analysis_m1',
                payload={
                    'reason':     exit_reason,
                    'exit_price': exit_price,
                    'candle':     candle,
                    'timestamp':  candle.get('timestamp'),
                }
            ))

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
            calculate_adx,
        )

        # ATR — always needed (SL/TP + Supertrend). Pass full df.
        df['atr'] = calculate_atr(df, self.st_period)

        if self.st_enabled:
            df['supertrend'], df['supertrend_direction'], df['st_upper'], df['st_lower'] = calculate_supertrend(
                df, self.st_period, self.st_multiplier)

        if self.ema_enabled:
            df['ema'] = calculate_ema(df['close'], self.ema_period)

        if self.sma_enabled:
            df['sma_fast'] = calculate_sma(df['close'], self.sma_fast_period)
            df['sma_slow'] = calculate_sma(df['close'], self.sma_slow_period)

        if self.sma_bias_enabled:
            df['sma_bias'] = calculate_sma(df['close'], self.sma_bias_period)
            if self.sma_bias_slope_bars > 0:
                df['sma_bias_prev'] = df['sma_bias'].shift(self.sma_bias_slope_bars)

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

        if self.adx_enabled:
            df['adx'], df['di_plus'], df['di_minus'] = calculate_adx(df, self.adx_period)

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
            ind['st_lower']             = float(latest['st_lower']) if not pd.isna(latest.get('st_lower')) else None
            ind['st_upper']             = float(latest['st_upper']) if not pd.isna(latest.get('st_upper')) else None

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

        if self.sma_bias_enabled and 'sma_bias' in df.columns:
            if pd.isna(latest.get('sma_bias')):
                return None  # wait for bias MA to warm up
            ind['sma_bias'] = float(latest['sma_bias'])
            if self.sma_bias_slope_bars > 0 and 'sma_bias_prev' in df.columns:
                prev_val = latest.get('sma_bias_prev')
                ind['sma_bias_prev'] = float(prev_val) if not pd.isna(prev_val) else ind['sma_bias']

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

        if self.adx_enabled and 'adx' in df.columns:
            if pd.isna(latest.get('adx')):
                return None
            ind['adx']      = float(latest['adx'])
            ind['di_plus']  = float(latest['di_plus'])  if not pd.isna(latest.get('di_plus'))  else 0.0
            ind['di_minus'] = float(latest['di_minus']) if not pd.isna(latest.get('di_minus')) else 0.0

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

        # --- ADX (trend strength gate — blocks both BUY and SELL in ranging markets) ---
        if self.rules.get('require_adx', False) and self.adx_enabled:
            adx_val  = ind.get('adx', 0) or 0
            trending = adx_val >= self.adx_threshold
            buy_votes.append(trending)
            sell_votes.append(trending)
            if self.adx_di_filter:
                di_plus  = ind.get('di_plus',  0) or 0
                di_minus = ind.get('di_minus', 0) or 0
                buy_votes.append(di_plus > di_minus)
                sell_votes.append(di_minus > di_plus)

        # --- MA directional bias: close > MA100 → BUY only; close < MA100 → SELL only ---
        if self.rules.get('require_sma_bias', False) and self.sma_bias_enabled:
            sma_bias = ind.get('sma_bias', close)
            buy_votes.append(close > sma_bias)    # only BUY when price above MA100
            sell_votes.append(close < sma_bias)   # only SELL when price below MA100
            # Slope gate: MA must also be moving in the signal direction
            if self.sma_bias_slope_bars > 0 and 'sma_bias_prev' in ind:
                ma_rising  = sma_bias >= ind['sma_bias_prev']
                ma_falling = sma_bias <= ind['sma_bias_prev']
                buy_votes.append(ma_rising)
                sell_votes.append(ma_falling)

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

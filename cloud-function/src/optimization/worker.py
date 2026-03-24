"""
Multiprocessing worker for strategy optimisation.

Separated from ``optimize_strategy.py`` so it is:
  - independently importable and unit-testable
  - trivially picklable by ProcessPoolExecutor (top-level module function)

Public API
----------
``build_backtest_config(params, initial_capital)``
    Construct a BacktestConfig from an optimisation parameter dict.

``_backtest_worker_function(args)``
    Process-pool worker.  Receives a packed tuple
    ``(df_train, df_test, params, initial_capital, idx)`` and returns a
    result dict suitable for ``StrategyOptimizer._format_results``.
"""

import logging
import traceback

import pandas as pd

from src.core.strategy import SupertrendVWAPStrategy
from src.strategies.hybrid_zone_supertrend_strategy import HybridZoneSuperTrendStrategy
from src.core.backtester import IntraCandleBacktester, BacktestConfig
from src.optimization.tp_sl import apply_tp_sl_by_strategy


# ---------------------------------------------------------------------------
# Config builder
# ---------------------------------------------------------------------------

def build_backtest_config(params: dict, initial_capital: float) -> BacktestConfig:
    """
    Build a BacktestConfig from an optimisation parameter dict.

    Centralises all the ``params.get('...')`` calls so the worker function
    and ``run_single_backtest_on_data`` share exactly the same config logic.

    Args:
        params: Parameter dict from the optimisation grid
        initial_capital: Starting capital for the backtest

    Returns:
        Populated BacktestConfig
    """
    return BacktestConfig(
        initial_capital=initial_capital,
        pip_value=params.get('pip_value', 1.0),
        default_position_size=params.get('position_size', 10.0),
        spread_cost_usd=params.get('spread_usd', 0.50),
        slippage_cost_usd=params.get('slippage_usd', 0.05),
        max_positions=1,
        # Intraday time-gating
        enable_time_exit=params.get('enable_time_exit', False),
        max_holding_hours=params.get('max_holding_hours', None),
        enable_eod_close=params.get('enable_eod_close', False),
        eod_close_hour=params.get('eod_close_hour', 16),
        enable_eod_blackout=params.get('enable_eod_blackout', False),
        no_entry_before_eod_hours=params.get('no_entry_before_eod_hours', 1),
        # Partial exits
        enable_partial_exit=params.get('enable_partial_exit', False),
        partial_exit_tp1_pips=params.get('partial_exit_tp1_pips', 10),
        partial_exit_tp1_pct=params.get('partial_exit_tp1_pct', 0.5),
        partial_exit_tp2_pips=params.get('partial_exit_tp2_pips', 20),
        partial_exit_tp2_pct=params.get('partial_exit_tp2_pct', 0.5),
        # Event blocking
        enable_event_blocking=params.get('enable_event_blocking', False),
        calendar_path=params.get('calendar_path', None),
    )


# ---------------------------------------------------------------------------
# Strategy factory
# ---------------------------------------------------------------------------

def build_strategy(params: dict):
    """
    Instantiate a strategy from a parameter dict.

    When ``params['strategy_type'] == 'zone_hybrid'`` an
    ``HybridZoneSuperTrendStrategy`` is returned (same interface as the base
    strategy plus zone-filter knobs).  All other values produce a plain
    ``SupertrendVWAPStrategy``.

    ATR strategies pass ``sl_pips`` / ``tp_pips`` as ATR multipliers inside
    the strategy constructor.  For fixed strategies the constructor values are
    immediately overridden by ``apply_tp_sl_by_strategy``, so the defaults
    here are harmless.

    Args:
        params: Parameter dict from the optimisation grid

    Returns:
        Configured strategy instance
    """
    sl_pips = params.get('sl_pips') or 20.0
    tp_pips = params.get('tp_pips') or 40.0

    common_kwargs = dict(
        supertrend_period=params['supertrend_period'],
        supertrend_multiplier=params['supertrend_multiplier'],
        sma_fast=params['sma_fast'],
        sma_slow=params['sma_slow'],
        ema_period=params['ema_period'],
        bb_period=params['bb_period'],
        bb_std=params['bb_std'],
        sl_pips=sl_pips,
        tp_pips=tp_pips,
        pip_value=params.get('pip_value', 1.0),
        # Phase 1 gold-specific filters
        use_rsi_filter=params.get('use_rsi_filter', False),
        rsi_period=params.get('rsi_period', 14),
        rsi_overbought=params.get('rsi_overbought', 70),
        rsi_oversold=params.get('rsi_oversold', 30),
        use_atr_volatility_filter=params.get('use_atr_volatility_filter', False),
        atr_volatility_period=params.get('atr_volatility_period', 14),
        atr_sma_period=params.get('atr_sma_period', 20),
        atr_min_ratio=params.get('atr_min_ratio', 0.7),
        atr_max_ratio=params.get('atr_max_ratio', 1.5),
        use_session_filter=params.get('use_session_filter', False),
        trading_sessions=params.get('trading_sessions', 'london_ny'),
    )

    if params.get('strategy_type') == 'zone_hybrid':
        return HybridZoneSuperTrendStrategy(
            **common_kwargs,
            enable_zone_filter=params.get('enable_zone_filter', True),
            enable_zone_stops=params.get('enable_zone_stops', False),
            zone_block_distance=params.get('zone_block_distance', 1.0),
        )

    return SupertrendVWAPStrategy(**common_kwargs)


# ---------------------------------------------------------------------------
# Signal counting helper
# ---------------------------------------------------------------------------

def _count_signals(signals: pd.DataFrame) -> tuple:
    """Return (buy_count, sell_count, total_count) from a signals DataFrame."""
    buys = int((signals['signal'] == 1).sum())
    sells = int((signals['signal'] == -1).sum())
    return buys, sells, buys + sells


# ---------------------------------------------------------------------------
# Worker function (must be a top-level function to be picklable)
# ---------------------------------------------------------------------------

def _backtest_worker_function(args):
    """
    Multiprocessing worker: run one param combination and return metrics.

    Args:
        args: Tuple of (df_train, df_test, params, initial_capital, idx)
              df_test may be None when no validation split is configured.

    Returns:
        Result dict consumed by StrategyOptimizer._format_results.
    """
    df_train, df_test, params, initial_capital, idx = args

    # Workers inherit the root logger level — silence in child processes
    logging.getLogger().setLevel(logging.ERROR)

    try:
        strategy = build_strategy(params)
        config = build_backtest_config(params, initial_capital)

        # ── Training run ───────────────────────────────────────────────────
        df_ind = strategy.calculate_indicators(df_train.copy())
        signals = strategy.generate_signals(df_ind)
        signals = apply_tp_sl_by_strategy(signals, df_ind, params)

        buys, sells, total = _count_signals(signals)

        backtester = IntraCandleBacktester(config)
        results = backtester.run(df_ind, signals)

        result_dict = {
            'params': params,
            'valid': True,
            'total_signals': total,
            'buy_signals': buys,
            'sell_signals': sells,
            'return_pct': results['return_pct'],
            'total_pnl': results['total_pnl'],
            'sharpe_ratio': results.get('sharpe_ratio', 0),
            'max_drawdown_pct': results.get('max_drawdown_pct', 0),
            'total_trades': results.get('total_trades', 0),
            'win_rate': results.get('win_rate', 0),
            'profit_factor': results.get('profit_factor', 0),
            'avg_win': results.get('avg_win', 0),
            'avg_loss': results.get('avg_loss', 0),
            'final_capital': results['final_capital'],
            'trades': results.get('trades', []),
            'equity_curve': results.get('equity_curve', []),
            '_idx': idx,
        }

        # ── Optional test run (out-of-sample validation) ───────────────────
        if df_test is not None:
            df_test_ind = strategy.calculate_indicators(df_test.copy())
            signals_test = strategy.generate_signals(df_test_ind)
            signals_test = apply_tp_sl_by_strategy(signals_test, df_test_ind, params)

            t_buys, t_sells, t_total = _count_signals(signals_test)
            results_test = backtester.run(df_test_ind, signals_test)

            train_return = results['return_pct']
            test_return = results_test['return_pct']
            degradation = (
                ((train_return - test_return) / train_return) * 100
                if train_return > 0 else 0
            )

            result_dict.update({
                'test_return_pct': test_return,
                'test_total_pnl': results_test['total_pnl'],
                'test_sharpe_ratio': results_test.get('sharpe_ratio', 0),
                'test_max_drawdown_pct': results_test.get('max_drawdown_pct', 0),
                'test_total_trades': results_test.get('total_trades', 0),
                'test_win_rate': results_test.get('win_rate', 0),
                'test_profit_factor': results_test.get('profit_factor', 0),
                'test_avg_win': results_test.get('avg_win', 0),
                'test_avg_loss': results_test.get('avg_loss', 0),
                'test_total_signals': t_total,
                'test_buy_signals': t_buys,
                'test_sell_signals': t_sells,
                'test_trades': results_test.get('trades', []),
                'test_equity_curve': results_test.get('equity_curve', []),
                'oos_degradation_pct': degradation,
            })

        return result_dict

    except Exception as exc:
        return {
            'params': params,
            'valid': False,
            'error': f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}",
            'total_signals': 0,
            '_idx': idx,
        }

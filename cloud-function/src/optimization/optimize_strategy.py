"""
Strategy Parameter Optimization - Test all permutations
Runs backtests across parameter combinations and ranks results
"""

import pandas as pd
import numpy as np
import json
import logging
from datetime import datetime
from pathlib import Path
from itertools import product
from typing import Dict, List, Tuple, Any
import sys
import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from multiprocessing import cpu_count

from src.core.strategy import SupertrendVWAPStrategy
from src.core.backtester import IntraCandleBacktester, BacktestConfig
from src.runners.run_backtest_from_cache import load_cached_data
from src.optimization.worker import _backtest_worker_function, build_backtest_config, build_strategy
from src.optimization.tp_sl import apply_tp_sl_by_strategy

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)



class StrategyOptimizer:
    """
    Parameter optimization engine for strategy tuning with train/test split support
    """
    
    def __init__(self, 
                 df: pd.DataFrame,
                 initial_capital: float = 10000.0,
                 epic: str = 'GOLD',
                 resolution: str = 'M5',
                 n_jobs: int = -1,
                 validation_split: float = 0.0):
        """
        Args:
            df: Historical price data
            initial_capital: Starting capital for backtest
            epic: Instrument name
            resolution: Timeframe
            n_jobs: Number of parallel workers (-1 = all cores, 1 = sequential)
            validation_split: Fraction for test set (0.0 = no split, 0.3 = 30% test)
        """
        self.df = df
        self.initial_capital = initial_capital
        self.epic = epic
        self.resolution = resolution
        self.n_jobs = cpu_count() if n_jobs == -1 else n_jobs
        self.results = []
        
        # Train/test split
        self.validation_split = validation_split
        if validation_split > 0:
            split_idx = int(len(df) * (1 - validation_split))
            self.df_train = df.iloc[:split_idx].copy()
            self.df_test = df.iloc[split_idx:].copy()
            print(f"\n📊 Train/Test Split:")
            print(f"   Train: {len(self.df_train)} bars ({self.df_train.index[0]} to {self.df_train.index[-1]})")
            print(f"   Test:  {len(self.df_test)} bars ({self.df_test.index[0]} to {self.df_test.index[-1]})")
            print(f"   Split: {(1-validation_split)*100:.0f}% / {validation_split*100:.0f}%\n")
        else:
            self.df_train = df
            self.df_test = None
        
    def define_short_grid(self) -> Dict[str, List]:
        """
        Short parameter grid — lean exploratory sweep (~2,000 combos, ~2min with 12 cores).
        
        Locks ema/bb/pip_value to known-good defaults so the search focuses on the
        parameters that actually matter: Supertrend, SMA crossover, and TP/SL.
        
        Returns:
            Dictionary with compact parameter ranges
        """
        return {
            # Core signal parameters — full range, 2 key values each
            'supertrend_period': [7, 10, 14],
            'supertrend_multiplier': [1.5, 2.0, 2.5, 3.0],

            # SMA crossover — test fast values vs 2 slow values
            'sma_fast': [10, 15, 20, 25],
            'sma_slow': [30, 50],          # drop sma_slow=100 for now

            # Lock these — they have little impact from phase tests
            'ema_period': [21],
            'bb_period': [20],
            'bb_std': [2.0],
            'pip_value': [0.5, 1.0],

            # TP/SL — both strategies, tighter range
            'tp_sl_strategy': ['fixed', 'atr'],
            'sl_pips': [10, 15, 20],
            'tp_pips': [20, 30, 40],
            'atr_sl_multiplier': [1.5, 2.0],
            'atr_tp_multiplier': [3.0, 4.0],
        }

    def define_parameter_grid(self) -> Dict[str, List]:
        """
        Define parameter ranges for optimization
        
        Returns:
            Dictionary of parameter names and their test values
        """
        return {
            # Supertrend parameters
            'supertrend_period': [7, 10, 14],
            'supertrend_multiplier': [1.5, 2.0, 2.5, 3.0],
            
            # Moving averages
            'sma_fast': [10, 15, 20, 25],
            'sma_slow': [30, 50, 100],
            'ema_period': [12, 21, 50],
            
            # Bollinger Bands
            'bb_period': [20, 30],
            'bb_std': [1.5, 2.0, 2.5],
            
            # Pip value for position sizing
            'pip_value': [0.5, 1.0, 1.5],
            
            # TP/SL Strategy: 'fixed' or 'atr'
            'tp_sl_strategy': ['fixed', 'atr'],
            
            # For fixed TP/SL
            'sl_pips': [15, 20, 25, 30],  # Used when tp_sl_strategy='fixed'
            'tp_pips': [30, 40, 50, 60],  # Used when tp_sl_strategy='fixed'
            
            # For ATR-based TP/SL
            'atr_sl_multiplier': [1.5, 2.0, 2.5],  # Used when tp_sl_strategy='atr'
            'atr_tp_multiplier': [3.0, 4.0, 5.0],  # Used when tp_sl_strategy='atr'
        }
    
    def define_quick_grid(self) -> Dict[str, List]:
        """
        Quick parameter grid for TRUE INTRADAY trading (M5 timeframe)
        Optimized for 30-50+ trades with tight stops and quick exits (1-4 hour holds)
        
        Returns:
            Dictionary with aggressive intraday-focused parameter ranges
        """
        return {
            'supertrend_period': [10],
            'supertrend_multiplier': [1.5, 2.0, 2.5],  # Added 1.5 for MORE signals
            'sma_fast': [15, 20],
            'sma_slow': [50],
            'ema_period': [21],
            'bb_period': [20],
            'bb_std': [2.0, 2.5],
            'tp_sl_strategy': ['fixed', 'atr'],
            # INTRADAY: Tight stops for quick exits (5-15 pips)
            'sl_pips': [5, 8, 10, 15],
            # INTRADAY: Quick targets with 1:1.5 to 1:3 risk-reward ratios
            'tp_pips': [10, 15, 20, 30],  # Removed 40 to reduce combinations
            # ATR-based: Test around proven 0.7×2.5 winner
            'atr_sl_multiplier': [0.5, 0.7, 1.0],  # 0.7 was previous best
            'atr_tp_multiplier': [2.0, 2.5, 3.0],  # 2.5 was previous best
            # CRITICAL: Small pip_value for INTRADAY (0.5-1.5 creates $15-$45 targets)
            'pip_value': [0.5, 1.0, 1.5],  # Reduced to 3 values for speed
        }
    
    def define_medium_grid(self) -> Dict[str, List]:
        """
        Medium parameter grid - balanced between speed and thorough exploration
        
        Returns:
            Dictionary with moderate parameter ranges
        """
        return {
            'supertrend_period': [7, 10],
            'supertrend_multiplier': [1.5, 2.0, 2.5],
            'sma_fast': [15, 20],
            'sma_slow': [50],
            'ema_period': [21],
            'bb_period': [20],
            'bb_std': [2.0, 2.5],
            'tp_sl_strategy': ['fixed', 'atr'],
            'sl_pips': [8, 10, 15],
            'tp_pips': [10, 15, 20, 30],
            'atr_sl_multiplier': [1.5, 2.0],
            'atr_tp_multiplier': [3.0, 4.0],
            'pip_value': [1.0],  # Fixed for medium mode
        }
    
    def define_intraday_grid(self) -> Dict[str, List]:
        """
        Intraday parameter grid - PHASE 3 TESTING
        
        Phase 2 results showed Dynamic TP/SL and BB sizing hurt performance.
        Focus on Phase 3 (MTF confirmation and S/R filtering) with winning Phase 1 baseline.
        
        Targets ~1-2 hour runtime with 12 workers
        
        Strategy:
        1. Lock winning Phase 1 parameters (ST 2.5, SMA 15/30, ATR 2x4)
        2. Test top Phase 1 filter combinations
        3. Skip Phase 2 features (all disabled - they failed)
        4. Test Phase 3: MTF confirmation and S/R filtering
        
        Returns:
            Dictionary with Phase 3 focused parameters
        """
        return {
            # TEST: Narrow range around winner (2.5)
            'supertrend_period': [7],
            'supertrend_multiplier': [2.0, 2.5, 3.0],
            
            # TEST: Winner (15/30) plus close alternatives
            'sma_fast': [15, 20],  # Winner was 15
            'sma_slow': [30, 50],  # Winner was 30
            
            'ema_period': [12],
            
            # LOCKED: Winner BB settings
            'bb_period': [20],
            'bb_std': [2.0],
            
            # LOCKED: ATR strategy (all top performers used this)
            'tp_sl_strategy': ['atr'],
            
            # For fixed TP/SL (not used)
            'sl_pips': [10],
            'tp_pips': [15],
            
            # TEST: ATR TP/SL multipliers (winner was 4.0x)
            'atr_sl_multiplier': [2.0],
            'atr_tp_multiplier': [3.0, 4.0],
            
            'pip_value': [1.0],
            
            # TEST: RSI filter (the winner!) with minimal threshold variations
            'use_rsi_filter': [True, False],
            'rsi_period': [14],
            'rsi_overbought': [70, 75],  # Winner was 70, test slightly stricter
            'rsi_oversold': [30, 25],    # Winner was 30, test slightly stricter
            
            # TEST: ATR volatility filter (Gold is volatile, worth testing)
            'use_atr_volatility_filter': [False, True],
            'atr_volatility_period': [14],
            'atr_sma_period': [20],
            'atr_min_ratio': [0.7],
            'atr_max_ratio': [1.5],
            
            # TEST: Session filter
            'use_session_filter': [False, True],
            'trading_sessions': ['london_ny'],
            
            # TEST: EOD blackout
            'enable_eod_blackout': [True, False],
            'no_entry_before_eod_hours': [1]
            
            # PHASE 2/3 REMOVED: All failed (ADX, BB sizing: -25.85%, Dynamic TP/SL: -55%, MTF: +0.82%, S/R: -25.90%)
            # Only RSI filter survived: +23.36% avg test improvement
        }
    
    def generate_combinations(self, grid: Dict[str, List]) -> List[Dict]:
        """
        Generate all valid parameter combinations
        
        Args:
            grid: Parameter grid definition
            
        Returns:
            List of parameter dictionaries
        """
        combinations = []
        
        # Get base parameters
        base_params = [
            'supertrend_period', 'supertrend_multiplier',
            'sma_fast', 'sma_slow', 'ema_period',
            'bb_period', 'bb_std', 'pip_value'
        ]
        
        # Check if Phase 1 filter parameters exist in grid
        phase1_params = [
            'use_rsi_filter', 'rsi_period', 'rsi_overbought', 'rsi_oversold',
            'use_atr_volatility_filter', 'atr_volatility_period', 'atr_sma_period',
            'atr_min_ratio', 'atr_max_ratio',
            'use_session_filter', 'trading_sessions',
            'enable_eod_blackout', 'no_entry_before_eod_hours'
        ]
        has_phase1 = all(param in grid for param in phase1_params)
        
        # Check if Phase 4 Friday filter parameters exist in grid
        phase4_params = ['enable_friday_filter', 'friday_cutoff_hour']
        has_phase4 = all(param in grid for param in phase4_params)
        
        # Check if Phase 4 Heiken Ashi parameter exists in grid
        has_heikin_ashi = 'use_heikin_ashi' in grid
        
        # Check if time-exit parameters exist in grid (for testing scalping vs swing)
        time_exit_params = ['enable_time_exit', 'max_holding_hours', 'enable_eod_close', 'eod_close_hour']
        has_time_exit = all(param in grid for param in time_exit_params)
        
        # PHASE 2/3 REMOVED: All failed in testing (ADX: no improvement, BB sizing: -25.85%, 
        # Dynamic TP/SL: -55%, MTF: +0.82% (negligible), S/R: -25.90% (catastrophic))
        # Only RSI filter survived with +30.09% test improvement
        
        # Generate all base combinations
        base_values = [grid[param] for param in base_params]
        
        for base_combo in product(*base_values):
            base_dict = dict(zip(base_params, base_combo))
            
            # Skip invalid SMA combinations (fast must be < slow)
            if base_dict['sma_fast'] >= base_dict['sma_slow']:
                continue
            
            # For each base combo, test TP/SL strategies
            for tp_sl_strat in grid['tp_sl_strategy']:
                tp_sl_combos = []
                
                if tp_sl_strat == 'fixed':
                    # Test all fixed TP/SL combinations
                    for sl_pips in grid['sl_pips']:
                        for tp_pips in grid['tp_pips']:
                            # Only valid if TP > SL (positive risk-reward)
                            if tp_pips > sl_pips:
                                tp_sl_combos.append({
                                    'tp_sl_strategy': 'fixed',
                                    'sl_pips': sl_pips,
                                    'tp_pips': tp_pips,
                                    'atr_sl_multiplier': None,
                                    'atr_tp_multiplier': None
                                })
                
                elif tp_sl_strat == 'atr':
                    # Test all ATR-based TP/SL combinations
                    for sl_mult in grid['atr_sl_multiplier']:
                        for tp_mult in grid['atr_tp_multiplier']:
                            # Only valid if TP multiplier > SL multiplier
                            if tp_mult > sl_mult:
                                tp_sl_combos.append({
                                    'tp_sl_strategy': 'atr',
                                    'sl_pips': None,
                                    'tp_pips': None,
                                    'atr_sl_multiplier': sl_mult,
                                    'atr_tp_multiplier': tp_mult
                                })
                
                # For each TP/SL combo, add Phase 1 filter variations
                for tp_sl_dict in tp_sl_combos:
                    if has_phase1:
                        # Generate all Phase 1 filter combinations
                        phase1_combos = product(
                            grid['use_rsi_filter'],
                            grid['rsi_period'],
                            grid['rsi_overbought'],
                            grid['rsi_oversold'],
                            grid['use_atr_volatility_filter'],
                            grid['atr_volatility_period'],
                            grid['atr_sma_period'],
                            grid['atr_min_ratio'],
                            grid['atr_max_ratio'],
                            grid['use_session_filter'],
                            grid['trading_sessions'],
                            grid['enable_eod_blackout'],
                            grid['no_entry_before_eod_hours']
                        )
                        
                        for phase1_vals in phase1_combos:
                            phase1_dict = dict(zip(phase1_params, phase1_vals))
                            
                            # Skip invalid Phase 1 combinations
                            # RSI parameters only matter when use_rsi_filter=True
                            if not phase1_dict['use_rsi_filter']:
                                if (phase1_dict['rsi_period'] != grid['rsi_period'][0] or
                                    phase1_dict['rsi_overbought'] != grid['rsi_overbought'][0] or
                                    phase1_dict['rsi_oversold'] != grid['rsi_oversold'][0]):
                                    continue
                            
                            # ATR volatility parameters only matter when use_atr_volatility_filter=True
                            if not phase1_dict['use_atr_volatility_filter']:
                                if (phase1_dict['atr_volatility_period'] != grid['atr_volatility_period'][0] or
                                    phase1_dict['atr_sma_period'] != grid['atr_sma_period'][0] or
                                    phase1_dict['atr_min_ratio'] != grid['atr_min_ratio'][0] or
                                    phase1_dict['atr_max_ratio'] != grid['atr_max_ratio'][0]):
                                    continue
                            
                            # Session parameters only matter when use_session_filter=True
                            if not phase1_dict['use_session_filter']:
                                if phase1_dict['trading_sessions'] != grid['trading_sessions'][0]:
                                    continue
                            
                            # no_entry_before_eod_hours only matters when enable_eod_blackout=True
                            if not phase1_dict['enable_eod_blackout']:
                                if phase1_dict['no_entry_before_eod_hours'] != grid['no_entry_before_eod_hours'][0]:
                                    continue
                            
                            # Build combination with Phase 1
                            combo = {
                                **base_dict,
                                **tp_sl_dict,
                                **phase1_dict
                            }
                            
                            # Add Phase 4 and time-exit variations if present
                            if has_phase4 or has_time_exit or has_heikin_ashi:
                                # Generate Phase 4 combos first
                                phase4_combos = []
                                if has_phase4:
                                    for friday_filter_enabled in grid['enable_friday_filter']:
                                        for friday_cutoff in grid['friday_cutoff_hour']:
                                            # friday_cutoff_hour only matters when enable_friday_filter=True
                                            if not friday_filter_enabled and friday_cutoff != grid['friday_cutoff_hour'][0]:
                                                continue
                                            phase4_combos.append({
                                                'enable_friday_filter': friday_filter_enabled,
                                                'friday_cutoff_hour': friday_cutoff
                                            })
                                else:
                                    # No Phase 4, empty dict
                                    phase4_combos.append({})
                                
                                # For each Phase 4 combo, add time-exit and HA variations
                                for phase4_dict in phase4_combos:
                                    if has_time_exit:
                                        # Generate all time-exit combinations
                                        for time_exit_enabled in grid['enable_time_exit']:
                                            for max_hours in grid['max_holding_hours']:
                                                for eod_close_enabled in grid['enable_eod_close']:
                                                    for eod_hour in grid['eod_close_hour']:
                                                        # max_holding_hours only matters when enable_time_exit=True
                                                        if not time_exit_enabled and max_hours != grid['max_holding_hours'][0]:
                                                            continue
                                                        # eod_close_hour only matters when enable_eod_close=True
                                                        if not eod_close_enabled and eod_hour != grid['eod_close_hour'][0]:
                                                            continue
                                                        
                                                        # Add Heiken Ashi variations
                                                        if has_heikin_ashi:
                                                            for use_ha in grid['use_heikin_ashi']:
                                                                combo_final = {
                                                                    **combo,
                                                                    **phase4_dict,
                                                                    'enable_time_exit': time_exit_enabled,
                                                                    'max_holding_hours': max_hours,
                                                                    'enable_eod_close': eod_close_enabled,
                                                                    'eod_close_hour': eod_hour,
                                                                    'use_heikin_ashi': use_ha
                                                                }
                                                                combinations.append(combo_final)
                                                        else:
                                                            combo_final = {
                                                                **combo,
                                                                **phase4_dict,
                                                                'enable_time_exit': time_exit_enabled,
                                                                'max_holding_hours': max_hours,
                                                                'enable_eod_close': eod_close_enabled,
                                                                'eod_close_hour': eod_hour
                                                            }
                                                            combinations.append(combo_final)
                                    else:
                                        # No time-exit params, just add Phase 4 and HA
                                        if has_heikin_ashi:
                                            for use_ha in grid['use_heikin_ashi']:
                                                combo_final = {
                                                    **combo,
                                                    **phase4_dict,
                                                    'use_heikin_ashi': use_ha
                                                }
                                                combinations.append(combo_final)
                                        else:
                                            combo_final = {
                                                **combo,
                                                **phase4_dict
                                            }
                                            combinations.append(combo_final)
                            else:
                                # No Phase 4 or time-exit - Phase 1 only
                                combinations.append(combo)
                    else:
                        # No Phase 1 parameters - check for Phase 4 and time-exit
                        combo = {
                            **base_dict,
                            **tp_sl_dict
                        }
                        
                        if has_phase4 or has_time_exit or has_heikin_ashi:
                            # Generate Phase 4 combos first
                            phase4_combos = []
                            if has_phase4:
                                for friday_filter_enabled in grid['enable_friday_filter']:
                                    for friday_cutoff in grid['friday_cutoff_hour']:
                                        # friday_cutoff_hour only matters when enable_friday_filter=True
                                        if not friday_filter_enabled and friday_cutoff != grid['friday_cutoff_hour'][0]:
                                            continue
                                        phase4_combos.append({
                                            'enable_friday_filter': friday_filter_enabled,
                                            'friday_cutoff_hour': friday_cutoff
                                        })
                            else:
                                # No Phase 4, empty dict
                                phase4_combos.append({})
                            
                            # For each Phase 4 combo, add time-exit and HA variations
                            for phase4_dict in phase4_combos:
                                if has_time_exit:
                                    # Generate all time-exit combinations
                                    for time_exit_enabled in grid['enable_time_exit']:
                                        for max_hours in grid['max_holding_hours']:
                                            for eod_close_enabled in grid['enable_eod_close']:
                                                for eod_hour in grid['eod_close_hour']:
                                                    # max_holding_hours only matters when enable_time_exit=True
                                                    if not time_exit_enabled and max_hours != grid['max_holding_hours'][0]:
                                                        continue
                                                    # eod_close_hour only matters when enable_eod_close=True
                                                    if not eod_close_enabled and eod_hour != grid['eod_close_hour'][0]:
                                                        continue
                                                    
                                                    # Add Heiken Ashi variations
                                                    if has_heikin_ashi:
                                                        for use_ha in grid['use_heikin_ashi']:
                                                            combo_final = {
                                                                **combo,
                                                                **phase4_dict,
                                                                'enable_time_exit': time_exit_enabled,
                                                                'max_holding_hours': max_hours,
                                                                'enable_eod_close': eod_close_enabled,
                                                                'eod_close_hour': eod_hour,
                                                                'use_heikin_ashi': use_ha
                                                            }
                                                            combinations.append(combo_final)
                                                    else:
                                                        combo_final = {
                                                            **combo,
                                                            **phase4_dict,
                                                            'enable_time_exit': time_exit_enabled,
                                                            'max_holding_hours': max_hours,
                                                            'enable_eod_close': eod_close_enabled,
                                                            'eod_close_hour': eod_hour
                                                        }
                                                        combinations.append(combo_final)
                                else:
                                    # No time-exit params, just add Phase 4 and HA
                                    if has_heikin_ashi:
                                        for use_ha in grid['use_heikin_ashi']:
                                            combo_final = {
                                                **combo,
                                                **phase4_dict,
                                                'use_heikin_ashi': use_ha
                                            }
                                            combinations.append(combo_final)
                                    else:
                                        combo_final = {
                                            **combo,
                                            **phase4_dict
                                        }
                                        combinations.append(combo_final)
                        else:
                            # No additional filters - just add base combo
                            combinations.append(combo)
        
        return combinations
    
    def run_single_backtest(self, params: Dict) -> Dict:
        """
        Run backtest with specific parameters (uses train data if split enabled)
        
        Args:
            params: Strategy parameters
            
        Returns:
            Results dictionary with performance metrics (includes test metrics if validation_split > 0)
        """
        # Run on train data
        train_results = self.run_single_backtest_on_data(params, self.df_train, prefix='')
        train_results['params'] = params
        
        # If validation split enabled, also run on test data
        if self.validation_split > 0 and self.df_test is not None:
            test_results = self.run_single_backtest_on_data(params, self.df_test, prefix='test_')
            train_results.update(test_results)
            
            # Calculate degradation if both are valid
            if train_results.get('valid') and test_results.get('test_valid'):
                train_return = train_results.get('return_pct', 0)
                test_return = test_results.get('test_return_pct', 0)
                if train_return != 0:
                    degradation_pct = ((test_return - train_return) / abs(train_return)) * 100
                    train_results['oos_degradation_pct'] = degradation_pct
                else:
                    train_results['oos_degradation_pct'] = 0
        
        return train_results
    
    def run_single_backtest_on_data(self, params: Dict, df: pd.DataFrame, prefix: str = '') -> Dict:
        """
        Run backtest with specific parameters on given dataframe
        
        Args:
            params: Strategy parameters
            df: Price dataframe (train or test)
            prefix: Prefix for result keys (e.g., 'train_', 'test_')
            
        Returns:
            Results dictionary with prefixed performance metrics
        """
        try:
            strategy = build_strategy(params)
            df_with_indicators = strategy.calculate_indicators(df.copy())
            signals = strategy.generate_signals(df_with_indicators)
            signals = apply_tp_sl_by_strategy(signals, df_with_indicators, params)

            # Count signals
            buy_signals = (signals['signal'] == 1).sum()
            sell_signals = (signals['signal'] == -1).sum()
            total_signals = buy_signals + sell_signals

            # Skip if no signals
            if total_signals == 0:
                return {
                    f'{prefix}valid': False,
                    f'{prefix}error': 'No signals generated',
                    f'{prefix}total_signals': 0
                }

            config = build_backtest_config(params, self.initial_capital)
            backtester = IntraCandleBacktester(config)
            results = backtester.run(df_with_indicators, signals)
            
            return {
                f'{prefix}valid': True,
                f'{prefix}total_signals': total_signals,
                f'{prefix}return_pct': results['return_pct'],
                f'{prefix}total_pnl': results['total_pnl'],
                f'{prefix}sharpe_ratio': results.get('sharpe_ratio', 0),
                f'{prefix}max_drawdown_pct': results.get('max_drawdown_pct', 0),
                f'{prefix}total_trades': results.get('total_trades', 0),
                f'{prefix}win_rate': results.get('win_rate', 0),
                f'{prefix}profit_factor': results.get('profit_factor', 0),
                f'{prefix}avg_win': results.get('avg_win', 0),
                f'{prefix}avg_loss': results.get('avg_loss', 0),
                f'{prefix}final_capital': results['final_capital'],
            }
            
        except Exception as e:
            return {
                f'{prefix}valid': False,
                f'{prefix}error': str(e),
                f'{prefix}total_signals': 0
            }
    
    def run_optimization(self, mode: str = 'quick', parallel: bool = True, max_combos: int = None) -> pd.DataFrame:
        """
        Run full parameter optimization
        
        Args:
            mode: 'quick', 'medium', or 'full' - determines grid size
            parallel: Use parallel processing (default True)
            max_combos: If set, randomly sample this many combinations instead of testing all.
                        e.g. max_combos=3000 finishes in minutes vs hours for full grid.
            
        Returns:
            DataFrame with all results sorted by performance
        """
        # Get parameter grid
        if mode == 'short':
            grid = self.define_short_grid()
            print(f"🎯 Short Optimization Mode  (~2,000 combos, ~2min)")
        elif mode == 'quick':
            grid = self.define_quick_grid()
            print(f"🎯 Quick Optimization Mode")
        elif mode == 'medium':
            grid = self.define_medium_grid()
            print(f"🎯 Medium Optimization Mode")
        elif mode == 'intraday':
            grid = self.define_intraday_grid()
            print(f"🎯 INTRADAY Optimization Mode (same-day close with EOD blackout)")
            print(f"⏰ Testing time-based features: time_exit, eod_close, eod_blackout, partial_exit")
        else:
            grid = self.define_parameter_grid()
            print(f"🎯 Full Optimization Mode")
        
        # Generate combinations
        combinations = self.generate_combinations(grid)
        total = len(combinations)
        
        # Random sampling to keep runtime manageable
        if max_combos and max_combos < total:
            import random
            random.seed(42)
            combinations = random.sample(combinations, max_combos)
            print(f"🎲 Random sample: {max_combos:,} / {total:,} combinations ({max_combos/total*100:.1f}% of grid)")
            total = max_combos
        
        print(f"📊 Testing {total} parameter combinations")
        print(f"📈 Data: {len(self.df)} bars ({self.df.index[0]} to {self.df.index[-1]})")
        print(f"💰 Initial capital: ${self.initial_capital:,.2f}")
        
        if parallel and self.n_jobs > 1:
            print(f"🚀 Parallel mode: {self.n_jobs} workers\n")
            results = self._run_parallel(combinations)
        else:
            print(f"⏱️ Sequential mode\n")
            results = self._run_sequential(combinations)
        
        print("\n")
        
        # Convert to DataFrame
        self.results = results
        df_results = self._format_results(results)
        
        return df_results
    
    def _run_sequential(self, combinations: List[Dict]) -> List[Dict]:
        """Run backtests sequentially (original method)"""
        results = []
        total = len(combinations)
        
        for idx, params in enumerate(combinations, 1):
            print(f"\r⏳ Progress: {idx}/{total} ({idx/total*100:.1f}%)", end='', flush=True)
            result = self.run_single_backtest(params)
            results.append(result)
        
        return results
    
    def _run_parallel(self, combinations: List[Dict]) -> List[Dict]:
        """Run backtests in parallel using ProcessPoolExecutor"""
        results = []
        total = len(combinations)
        completed = 0
        
        # Prepare arguments for worker function
        # Pass train and test dataframes for validation
        df_train = self.df_train if hasattr(self, 'df_train') else self.df
        df_test = self.df_test if hasattr(self, 'df_test') else None
        
        worker_args = [
            (df_train, df_test, params, self.initial_capital, idx)
            for idx, params in enumerate(combinations)
        ]
        
        # Submit in batches to avoid queueing all 100k+ tasks at once (memory + macOS fork limits)
        batch_size = self.n_jobs * 64  # keep ~64 tasks queued per worker at a time
        start_time = __import__('time').time()

        with ProcessPoolExecutor(max_workers=self.n_jobs) as executor:
            for batch_start in range(0, total, batch_size):
                batch = worker_args[batch_start: batch_start + batch_size]
                futures = {
                    executor.submit(_backtest_worker_function, args): args
                    for args in batch
                }

                for future in as_completed(futures):
                    completed += 1
                    elapsed = __import__('time').time() - start_time
                    rate = completed / elapsed if elapsed > 0 else 0
                    eta = (total - completed) / rate if rate > 0 else 0
                    print(
                        f"\r⏳ {completed}/{total} ({completed/total*100:.1f}%)  "
                        f"{rate:.0f}/s  ETA {eta/60:.1f}min   ",
                        end='', flush=True
                    )

                    try:
                        result = future.result()
                        results.append(result)
                    except Exception as e:
                        print(f"\n⚠️  Task failed: {e}")
                        results.append({
                            'params': {},
                            'valid': False,
                            'error': str(e),
                            'total_signals': 0,
                            '_idx': completed - 1
                        })
        
        # Sort by original order
        results.sort(key=lambda x: x.get('_idx', 999999))
        
        return results
    
    def _run_backtest_worker(self, params: Dict, idx: int) -> Dict:
        """
        Worker function for parallel execution
        Must be picklable (no lambda, no nested functions with external refs)
        
        Args:
            params: Strategy parameters
            idx: Index for tracking
            
        Returns:
            Result dictionary
        """
        # This runs in a separate process, so we need to suppress logging
        logging.getLogger().setLevel(logging.ERROR)
        
        try:
            result = self.run_single_backtest(params)
            result['_idx'] = idx  # Track original order
            return result
        except Exception as e:
            return {
                'params': params,
                'valid': False,
                'error': str(e),
                'total_signals': 0,
                '_idx': idx
            }
    
    def _format_results(self, results: List[Dict]) -> pd.DataFrame:
        """
        Format results into a clean DataFrame
        
        Args:
            results: List of result dictionaries
            
        Returns:
            Formatted DataFrame
        """
        rows = []
        invalid_count = 0
        
        for result in results:
            if not result.get('valid', False):
                invalid_count += 1
                if invalid_count <= 3:  # Show first 3 errors
                    print(f"\n⚠️  Invalid result: {result.get('error', 'Unknown error')}")
                continue
            
            params = result['params']
            
            # Format TP/SL info
            if params['tp_sl_strategy'] == 'fixed':
                tp_sl_info = f"Fixed {params['sl_pips']}:{params['tp_pips']}"
            else:
                tp_sl_info = f"ATR {params['atr_sl_multiplier']}x:{params['atr_tp_multiplier']}x"
            
            row = {
                # Performance metrics (IN-SAMPLE / TRAIN)
                'return_pct': result['return_pct'],
                'total_pnl': result['total_pnl'],
                'sharpe_ratio': result['sharpe_ratio'],
                'win_rate': result['win_rate'],
                'profit_factor': result['profit_factor'],
                'max_drawdown_pct': result['max_drawdown_pct'],
                'total_trades': result['total_trades'],
                'total_signals': result['total_signals'],
                'buy_signals': result.get('buy_signals', 0),
                'sell_signals': result.get('sell_signals', 0),
                
                # Strategy parameters
                'st_period': params['supertrend_period'],
                'st_mult': params['supertrend_multiplier'],
                'sma_fast': params['sma_fast'],
                'sma_slow': params['sma_slow'],
                'ema': params['ema_period'],
                'bb_period': params['bb_period'],
                'bb_std': params['bb_std'],
                'pip_value': params.get('pip_value', 1.0),
                'tp_sl': tp_sl_info,
                
                # ATR-based TP/SL multipliers (Phase 4)
                'atr_sl_multiplier': params.get('atr_sl_multiplier', 2.0),
                'atr_tp_multiplier': params.get('atr_tp_multiplier', 4.0),
                
                # Friday filter (Phase 4)
                'enable_friday_filter': params.get('enable_friday_filter', False),
                'friday_cutoff_hour': params.get('friday_cutoff_hour', 15),
                
                # Intraday time-based parameters (legacy - for backward compatibility)
                'enable_time_exit': params.get('enable_time_exit', False),
                'max_holding_hours': params.get('max_holding_hours', None),
                'enable_eod_close': params.get('enable_eod_close', False),
                'eod_close_hour': params.get('eod_close_hour', 16),
                'enable_eod_blackout': params.get('enable_eod_blackout', False),
                'no_entry_before_eod_hours': params.get('no_entry_before_eod_hours', 1),
                'enable_partial_exit': params.get('enable_partial_exit', False),
                'partial_exit_tp1_pips': params.get('partial_exit_tp1_pips', 10),
                'partial_exit_tp2_pips': params.get('partial_exit_tp2_pips', 20),
                
                # Phase 1: Gold-specific filter parameters
                'use_rsi_filter': params.get('use_rsi_filter', False),
                'rsi_period': params.get('rsi_period', 14),
                'rsi_overbought': params.get('rsi_overbought', 70),
                'rsi_oversold': params.get('rsi_oversold', 30),
                'use_atr_volatility_filter': params.get('use_atr_volatility_filter', False),
                'atr_volatility_period': params.get('atr_volatility_period', 14),
                'atr_sma_period': params.get('atr_sma_period', 20),
                'atr_min_ratio': params.get('atr_min_ratio', 0.7),
                'atr_max_ratio': params.get('atr_max_ratio', 1.5),
                'use_session_filter': params.get('use_session_filter', False),
                'trading_sessions': params.get('trading_sessions', 'london_ny'),
                
                # Phase 4: Heiken Ashi
                'use_heikin_ashi': params.get('use_heikin_ashi', False),
                
                # PHASE 2/3 REMOVED: All failed in testing (ADX: no improvement, BB sizing: -25.85%, 
                # Dynamic TP/SL: -55%, MTF: +0.82% (negligible), S/R: -25.90% (catastrophic))
                # Only RSI filter survived: +30.09% test improvement
                
                # Raw values for filtering
                'avg_win': result['avg_win'],
                'avg_loss': result['avg_loss'],
                
                # CRITICAL FIX: Preserve original test index for lookup
                '_idx': result.get('_idx', 0),
            }
            
            # Add OUT-OF-SAMPLE metrics if validation split was used
            if 'test_return_pct' in result:
                row.update({
                    'test_return_pct': result.get('test_return_pct', 0),
                    'test_total_pnl': result.get('test_total_pnl', 0),
                    'test_sharpe_ratio': result.get('test_sharpe_ratio', 0),
                    'test_win_rate': result.get('test_win_rate', 0),
                    'test_profit_factor': result.get('test_profit_factor', 0),
                    'test_max_drawdown_pct': result.get('test_max_drawdown_pct', 0),
                    'test_total_trades': result.get('test_total_trades', 0),
                    'test_total_signals': result.get('test_total_signals', 0),
                    'test_buy_signals': result.get('test_buy_signals', 0),
                    'test_sell_signals': result.get('test_sell_signals', 0),
                    'test_avg_win': result.get('test_avg_win', 0),
                    'test_avg_loss': result.get('test_avg_loss', 0),
                    'oos_degradation_pct': result.get('oos_degradation_pct', 0),
                })
            
            rows.append(row)
        
        if invalid_count > 0:
            print(f"\n⚠️  Total invalid results: {invalid_count}/{len(results)}")
        
        if not rows:
            print(f"\n❌ ERROR: No valid results! All {len(results)} backtests failed.")
            return pd.DataFrame()  # Return empty DataFrame
        
        df = pd.DataFrame(rows)
        
        # Sort by return_pct descending
        df = df.sort_values('return_pct', ascending=False).reset_index(drop=True)
        
        print(f"\n✅ Valid results: {len(rows)}/{len(results)}")
        
        return df
    
    def _generate_strategy_names(self, df_results: pd.DataFrame) -> Dict[int, str]:
        """
        Generate descriptive strategy names based on parameters
        
        Args:
            df_results: Results DataFrame
            
        Returns:
            Dictionary mapping index to strategy name
        """
        names = {}
        
        for idx, row in df_results.iterrows():
            # Build name from key parameters
            st_mult = row.get('st_mult', 2.5)
            sma_fast = int(row.get('sma_fast', 20))
            sma_slow = int(row.get('sma_slow', 50))
            bb_std = row.get('bb_std', 2.0)
            pip_val = row.get('pip_value', 1.0)
            tp_sl = str(row.get('tp_sl', 'Fixed 20:40'))
            
            # Format TP/SL for name
            if 'Fixed' in tp_sl:
                # Extract numbers: "Fixed 20:60" -> "F20-60"
                parts = tp_sl.replace('Fixed ', '').split(':')
                if len(parts) == 2:
                    tp_sl_name = f"F{parts[0]}-{parts[1]}"
                else:
                    tp_sl_name = "Fixed"
            elif 'ATR' in tp_sl:
                # Extract multipliers: "ATR 2.0x:4.0x" -> "ATR2x4"
                parts = tp_sl.replace('ATR ', '').replace('x', '').split(':')
                if len(parts) == 2:
                    sl_mult = parts[0].replace('.0', '')
                    tp_mult = parts[1].replace('.0', '')
                    tp_sl_name = f"ATR{sl_mult}x{tp_mult}"
                else:
                    tp_sl_name = "ATR"
            else:
                tp_sl_name = "Unknown"
            
            # Format pip_value for name (remove trailing zeros)
            pip_str = f"{pip_val:.2f}" if pip_val < 1 else f"{int(pip_val)}"
            
            # Format: ST2.0_SMA15-50_BB2.0_PIP1_F20-60
            name = f"ST{st_mult}_SMA{sma_fast}-{sma_slow}_BB{bb_std}_PIP{pip_str}_{tp_sl_name}"
            
            # Add rank prefix for easy sorting
            names[idx] = f"rank{idx+1:02d}_{name}"
        
        return names
    
    def _create_final_summary(self, df_results: pd.DataFrame, base_dir: Path, date_str: str, timestamp: str):
        """
        Create comprehensive final summary report
        
        Args:
            df_results: Results DataFrame with all strategies
            base_dir: Output directory
            date_str: Date string
            timestamp: Timestamp string
        """
        # Group by TP/SL strategy type
        fixed_strategies = df_results[df_results['tp_sl'].str.contains('Fixed', na=False)]
        atr_strategies = df_results[df_results['tp_sl'].str.contains('ATR', na=False)]
        
        summary = {
            'optimization_run': {
                'date': date_str,
                'timestamp': timestamp,
                'instrument': self.epic,
                'timeframe': self.resolution,
                'data_bars': len(self.df),
                'date_range': {
                    'start': str(self.df.index[0]),
                    'end': str(self.df.index[-1]),
                    'days': (self.df.index[-1] - self.df.index[0]).days
                }
            },
            'results_overview': {
                'total_combinations_tested': len(self.results),
                'valid_strategies': len(df_results),
                'fixed_sl_tp_strategies': len(fixed_strategies),
                'atr_based_strategies': len(atr_strategies)
            },
            'overall_best': {
                'strategy_name': df_results.iloc[0]['strategy_name'] if len(df_results) > 0 else 'N/A',
                'initial_capital': float(self.initial_capital),
                'final_capital': float(self.initial_capital + df_results.iloc[0]['total_pnl']) if len(df_results) > 0 else float(self.initial_capital),
                'total_pnl': float(df_results.iloc[0]['total_pnl']) if len(df_results) > 0 else 0,
                'return_pct': float(df_results.iloc[0]['return_pct']) if len(df_results) > 0 else 0,
                'sharpe_ratio': float(df_results.iloc[0]['sharpe_ratio']) if len(df_results) > 0 else 0,
                'win_rate': float(df_results.iloc[0]['win_rate']) if len(df_results) > 0 else 0,
                'profit_factor': float(df_results.iloc[0]['profit_factor']) if len(df_results) > 0 else 0,
                'total_trades': int(df_results.iloc[0]['total_trades']) if len(df_results) > 0 else 0
            },
            'best_by_metric': {
                'highest_return': {
                    'strategy': df_results.iloc[0]['strategy_name'] if len(df_results) > 0 else 'N/A',
                    'value': float(df_results['return_pct'].max()) if len(df_results) > 0 else 0
                },
                'highest_sharpe': {
                    'strategy': df_results.loc[df_results['sharpe_ratio'].idxmax(), 'strategy_name'] if len(df_results) > 0 else 'N/A',
                    'value': float(df_results['sharpe_ratio'].max()) if len(df_results) > 0 else 0
                },
                'highest_win_rate': {
                    'strategy': df_results.loc[df_results['win_rate'].idxmax(), 'strategy_name'] if len(df_results) > 0 else 'N/A',
                    'value': float(df_results['win_rate'].max()) if len(df_results) > 0 else 0
                },
                'highest_profit_factor': {
                    'strategy': df_results.loc[df_results['profit_factor'].idxmax(), 'strategy_name'] if len(df_results) > 0 else 'N/A',
                    'value': float(df_results['profit_factor'].max()) if len(df_results) > 0 else 0
                },
                'lowest_drawdown': {
                    'strategy': df_results.loc[df_results['max_drawdown_pct'].idxmin(), 'strategy_name'] if len(df_results) > 0 else 'N/A',
                    'value': float(df_results['max_drawdown_pct'].min()) if len(df_results) > 0 else 0
                }
            },
            'fixed_sl_tp_analysis': {
                'best_strategy': fixed_strategies.iloc[0]['strategy_name'] if len(fixed_strategies) > 0 else 'N/A',
                'avg_return_pct': float(fixed_strategies['return_pct'].mean()) if len(fixed_strategies) > 0 else 0,
                'avg_win_rate': float(fixed_strategies['win_rate'].mean()) if len(fixed_strategies) > 0 else 0,
                'avg_sharpe': float(fixed_strategies['sharpe_ratio'].mean()) if len(fixed_strategies) > 0 else 0,
                'best_sl_tp_ratio': self._find_best_ratio(fixed_strategies) if len(fixed_strategies) > 0 else 'N/A'
            },
            'atr_based_analysis': {
                'best_strategy': atr_strategies.iloc[0]['strategy_name'] if len(atr_strategies) > 0 else 'N/A',
                'avg_return_pct': float(atr_strategies['return_pct'].mean()) if len(atr_strategies) > 0 else 0,
                'avg_win_rate': float(atr_strategies['win_rate'].mean()) if len(atr_strategies) > 0 else 0,
                'avg_sharpe': float(atr_strategies['sharpe_ratio'].mean()) if len(atr_strategies) > 0 else 0,
                'best_multipliers': self._find_best_atr_multipliers(atr_strategies) if len(atr_strategies) > 0 else 'N/A'
            },
            'top_10_strategies': df_results.head(10)[['strategy_name', 'return_pct', 'sharpe_ratio', 'win_rate', 'profit_factor', 'total_trades']].to_dict('records'),
            'parameter_insights': {
                'best_supertrend_multiplier': self._find_best_param(df_results, 'st_mult'),
                'best_sma_fast': self._find_best_param(df_results, 'sma_fast'),
                'best_bb_std': self._find_best_param(df_results, 'bb_std')
            },
            'recommendation': self._generate_recommendation(df_results, fixed_strategies, atr_strategies)
        }
        
        # Save comprehensive summary
        summary_file = base_dir / 'FINAL_SUMMARY.json'
        with open(summary_file, 'w') as f:
            json.dump(summary, f, indent=2)
        
        print(f"\n{'='*80}")
        print(f"📊 FINAL OPTIMIZATION SUMMARY")
        print(f"{'='*80}\n")
        print(f"📁 Tested: {len(self.results)} strategy combinations")
        print(f"✅ Valid: {len(df_results)} strategies with trades\n")
        
        print(f"🏆 OVERALL BEST: {summary['overall_best']['strategy_name']}")
        print(f"   Return: {summary['overall_best']['return_pct']:.3f}%")
        print(f"   Sharpe: {summary['overall_best']['sharpe_ratio']:.2f}")
        print(f"   Win Rate: {summary['overall_best']['win_rate']:.1f}%")
        print(f"   Profit Factor: {summary['overall_best']['profit_factor']:.2f}\n")
        
        print(f"📈 BEST BY METRIC:")
        for metric, data in summary['best_by_metric'].items():
            print(f"   {metric.replace('_', ' ').title()}: {data['value']:.3f} ({data['strategy']})")
        
        print(f"\n💡 RECOMMENDATION:")
        print(f"   {summary['recommendation']}\n")
        
        print(f"💾 Full summary: {summary_file}")
        print(f"{'='*80}\n")
    
    def _find_best_ratio(self, df: pd.DataFrame) -> str:
        """Find best fixed SL:TP ratio"""
        if len(df) == 0:
            return 'N/A'
        best = df.iloc[0]
        tp_sl = str(best.get('tp_sl', 'N/A'))
        return tp_sl.replace('Fixed ', '')
    
    def _find_best_atr_multipliers(self, df: pd.DataFrame) -> str:
        """Find best ATR multipliers"""
        if len(df) == 0:
            return 'N/A'
        best = df.iloc[0]
        tp_sl = str(best.get('tp_sl', 'N/A'))
        return tp_sl.replace('ATR ', '')
    
    def _find_best_param(self, df: pd.DataFrame, param_col: str) -> float:
        """Find best parameter value by average return"""
        if len(df) == 0 or param_col not in df.columns:
            return 0
        
        # Group by parameter and get average return
        grouped = df.groupby(param_col)['return_pct'].mean()
        best_param = grouped.idxmax()
        return float(best_param)
    
    def _generate_recommendation(self, df_all: pd.DataFrame, df_fixed: pd.DataFrame, df_atr: pd.DataFrame) -> str:
        """Generate recommendation based on results"""
        if len(df_all) == 0:
            return "No valid strategies found"
        
        best = df_all.iloc[0]
        
        # Compare fixed vs ATR
        fixed_avg = df_fixed['return_pct'].mean() if len(df_fixed) > 0 else 0
        atr_avg = df_atr['return_pct'].mean() if len(df_atr) > 0 else 0
        
        tp_sl_type = "Fixed SL/TP" if fixed_avg > atr_avg else "ATR-based SL/TP"
        
        return (f"Use {best['strategy_name']} for best overall performance. "
                f"{tp_sl_type} strategies performed better on average "
                f"({max(fixed_avg, atr_avg):.3f}% vs {min(fixed_avg, atr_avg):.3f}%). "
                f"Supertrend multiplier {best.get('st_mult', 2.5)} with "
                f"SMA {int(best.get('sma_fast', 20))}/{int(best.get('sma_slow', 50))} shows strongest results.")
    
    def export_results(self, df_results: pd.DataFrame, output_dir: str = 'data/optimization'):
        """
        Export optimization results with organized date-wise folder structure
        Each strategy gets its own folder with orders, config, and summary
        
        Args:
            df_results: Results DataFrame with full trade data
            output_dir: Base output directory
        """
        if len(df_results) == 0:
            print("⚠️ No results to export")
            return
        
        # Create date/run_id folder structure: data/optimization/YYYY-MM-DD/run_<timestamp>/
        date_str = datetime.now().strftime('%Y-%m-%d')
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        run_id = f"run_{timestamp}"
        
        # Create hierarchical structure: output_dir/date/run_id/
        date_dir = Path(output_dir) / date_str
        base_dir = date_dir / run_id
        base_dir.mkdir(parents=True, exist_ok=True)
        
        print(f"\n📁 Run ID: {run_id}")
        print(f"📁 Exporting to: {base_dir}\n")
        
        # Save results reference for trade lookup
        # CRITICAL FIX: Use _idx as key (original test order) not enumerate index
        results_lookup = {result.get('_idx', i): result for i, result in enumerate(self.results) if result.get('valid', False)}
        
        # Generate strategy names
        strategy_names = self._generate_strategy_names(df_results)
        
        # Export each strategy to its own folder
        for idx, row in df_results.iterrows():
            strategy_num = idx + 1
            strategy_name = strategy_names.get(idx, f"strategy_{strategy_num:03d}")
            # Strategy folder without timestamp (run_id already contains it)
            strategy_dir = base_dir / strategy_name
            strategy_dir.mkdir(exist_ok=True)
            
            # Get full result data including trades
            # CRITICAL FIX: Use _idx from row to get correct result data
            result_idx = int(row.get('_idx', idx))
            result_data = results_lookup.get(result_idx, {})
            
            # Check if this is a train/test split run
            has_validation = 'test_return_pct' in row and pd.notna(row.get('test_return_pct'))
            
            # 1. Save orders/trades CSV - TRAIN SET
            if 'trades' in result_data and result_data['trades'] and len(result_data['trades']) > 0:
                trades_df = pd.DataFrame(result_data['trades'])
                
                # Add order value calculation (position size * entry_price)
                if 'size' in trades_df.columns and 'entry_price' in trades_df.columns:
                    trades_df['order_value_usd'] = trades_df['size'] * trades_df['entry_price']
                
                # Convert timestamps to string for CSV export
                if 'entry_time' in trades_df.columns:
                    trades_df['entry_time'] = trades_df['entry_time'].astype(str)
                if 'exit_time' in trades_df.columns:
                    trades_df['exit_time'] = trades_df['exit_time'].astype(str)
                
                # Save with appropriate filename based on validation mode
                if has_validation:
                    orders_file = strategy_dir / 'orders_train.csv'
                else:
                    orders_file = strategy_dir / 'orders.csv'
                trades_df.to_csv(orders_file, index=False)
            
            # 1b. Save TEST orders/trades CSV if validation enabled
            if has_validation and 'test_trades' in result_data and result_data['test_trades'] and len(result_data['test_trades']) > 0:
                test_trades_df = pd.DataFrame(result_data['test_trades'])
                
                # Add order value calculation
                if 'size' in test_trades_df.columns and 'entry_price' in test_trades_df.columns:
                    test_trades_df['order_value_usd'] = test_trades_df['size'] * test_trades_df['entry_price']
                
                # Convert timestamps to string
                if 'entry_time' in test_trades_df.columns:
                    test_trades_df['entry_time'] = test_trades_df['entry_time'].astype(str)
                if 'exit_time' in test_trades_df.columns:
                    test_trades_df['exit_time'] = test_trades_df['exit_time'].astype(str)
                
                test_orders_file = strategy_dir / 'orders_test.csv'
                test_trades_df.to_csv(test_orders_file, index=False)
            
            # 2. Save strategy configuration JSON
            tp_sl_str = str(row.get('tp_sl', 'Fixed 20:40'))
            config = {
                'strategy_name': strategy_name,
                'strategy_number': strategy_num,
                'rank': idx + 1,
                'instrument': self.epic,
                'timeframe': self.resolution,
                'optimization_date': date_str,
                'parameters': {
                    'supertrend_period': int(row.get('st_period', 10)),
                    'supertrend_multiplier': float(row.get('st_mult', 2.5)),
                    'sma_fast': int(row.get('sma_fast', 20)),
                    'sma_slow': int(row.get('sma_slow', 50)),
                    'ema_period': int(row.get('ema', 21)),
                    'bb_period': int(row.get('bb_period', 20)),
                    'bb_std': float(row.get('bb_std', 2.0)),
                    'tp_sl_strategy': tp_sl_str
                },
                'position_sizing': {
                    'default_position_size': 1.0,
                    'position_type': 'contracts',
                    'note': 'For GOLD: 1 contract = 1 troy oz (~$5,200 per trade at current prices)'
                }
            }
            
            config_file = strategy_dir / 'config.json'
            with open(config_file, 'w') as f:
                json.dump(config, f, indent=2)
            
            # 3. Save performance summary JSON
            total_pnl = float(row.get('total_pnl', 0))
            return_pct = float(row.get('return_pct', 0))
            max_dd_pct = float(row.get('max_drawdown_pct', 0))
            sharpe = float(row.get('sharpe_ratio', 0))
            avg_win = float(row.get('avg_win', 0))
            avg_loss = float(row.get('avg_loss', 0))
            
            # Calculate additional analytics for train
            recovery_factor = abs(return_pct / max_dd_pct) if max_dd_pct != 0 else 0
            calmar_ratio = return_pct / max_dd_pct if max_dd_pct != 0 else 0
            expectancy = (avg_win * row.get('win_rate', 0) / 100) + (avg_loss * (1 - row.get('win_rate', 0) / 100))
            
            # Base summary structure
            summary = {
                'strategy_name': strategy_name,
                'strategy_number': strategy_num,
                'rank': idx + 1,
                'validation_mode': 'train_test_split' if has_validation else 'full_data',
                'capital': {
                    'initial_capital': float(self.initial_capital)
                }
            }
            
            # Add TRAIN metrics
            summary['train'] = {
                'capital': {
                    'final_capital': float(self.initial_capital + total_pnl),
                    'total_pnl': total_pnl,
                    'return_pct': return_pct
                },
                'performance': {
                    'return_pct': return_pct,
                    'total_pnl': total_pnl,
                    'sharpe_ratio': sharpe,
                    'profit_factor': float(row.get('profit_factor', 0)),
                    'max_drawdown_pct': max_dd_pct,
                    'recovery_factor': recovery_factor,
                    'calmar_ratio': calmar_ratio,
                    'expectancy_per_trade': expectancy
                },
                'trades': {
                    'total': int(row.get('total_trades', 0)),
                    'wins': int(row.get('total_trades', 0) * row.get('win_rate', 0) / 100),
                    'losses': int(row.get('total_trades', 0) * (1 - row.get('win_rate', 0) / 100)),
                    'win_rate_pct': float(row.get('win_rate', 0)),
                    'avg_win': avg_win,
                    'avg_loss': avg_loss
                },
                'signals': {
                    'total': int(row.get('total_signals', 0)),
                    'buy': int(row.get('buy_signals', 0)),
                    'sell': int(row.get('sell_signals', 0))
                }
            }
            
            # Add TEST metrics if validation enabled
            if has_validation:
                test_return_pct = float(row.get('test_return_pct', 0))
                test_total_pnl = float(row.get('test_total_pnl', 0))
                test_max_dd_pct = float(row.get('test_max_drawdown_pct', 0))
                test_sharpe = float(row.get('test_sharpe_ratio', 0))
                test_avg_win = float(row.get('test_avg_win', 0))
                test_avg_loss = float(row.get('test_avg_loss', 0))
                
                # Calculate test analytics
                test_recovery_factor = abs(test_return_pct / test_max_dd_pct) if test_max_dd_pct != 0 else 0
                test_calmar_ratio = test_return_pct / test_max_dd_pct if test_max_dd_pct != 0 else 0
                test_expectancy = (test_avg_win * row.get('test_win_rate', 0) / 100) + (test_avg_loss * (1 - row.get('test_win_rate', 0) / 100))
                
                summary['test'] = {
                    'capital': {
                        'final_capital': float(self.initial_capital + test_total_pnl),
                        'total_pnl': test_total_pnl,
                        'return_pct': test_return_pct
                    },
                    'performance': {
                        'return_pct': test_return_pct,
                        'total_pnl': test_total_pnl,
                        'sharpe_ratio': test_sharpe,
                        'profit_factor': float(row.get('test_profit_factor', 0)),
                        'max_drawdown_pct': test_max_dd_pct,
                        'recovery_factor': test_recovery_factor,
                        'calmar_ratio': test_calmar_ratio,
                        'expectancy_per_trade': test_expectancy
                    },
                    'trades': {
                        'total': int(row.get('test_total_trades', 0)),
                        'wins': int(row.get('test_total_trades', 0) * row.get('test_win_rate', 0) / 100),
                        'losses': int(row.get('test_total_trades', 0) * (1 - row.get('test_win_rate', 0) / 100)),
                        'win_rate_pct': float(row.get('test_win_rate', 0)),
                        'avg_win': test_avg_win,
                        'avg_loss': test_avg_loss
                    },
                    'signals': {
                        'total': int(row.get('test_total_signals', 0)),
                        'buy': int(row.get('test_buy_signals', 0)),
                        'sell': int(row.get('test_sell_signals', 0))
                    }
                }
                
                # Add out-of-sample comparison
                summary['out_of_sample'] = {
                    'degradation_pct': float(row.get('oos_degradation_pct', 0)),
                    'return_delta': test_return_pct - return_pct,
                    'sharpe_delta': test_sharpe - sharpe,
                    'pf_delta': float(row.get('test_profit_factor', 0)) - float(row.get('profit_factor', 0)),
                    'comment': 'Positive degradation = worse performance on test set, negative = better on test'
                }
            
            summary_file = strategy_dir / 'summary.json'
            with open(summary_file, 'w') as f:
                json.dump(summary, f, indent=2)
        
        print(f"✅ Exported {len(df_results)} strategies to individual folders")
        
        # Add strategy names to results
        df_export = df_results.copy()
        df_export.insert(0, 'strategy_name', [strategy_names.get(i, f"strategy_{i+1:03d}") for i in range(len(df_export))])
        
        # Export master summary CSV (all strategies) with timestamp
        master_csv = base_dir / f"{self.epic}_{self.resolution}_all_strategies_{timestamp}.csv"
        df_export.to_csv(master_csv, index=False)
        print(f"📊 Master CSV: {master_csv}")
        
        # Create comprehensive final summary
        self._create_final_summary(df_export, base_dir, date_str, timestamp)
        
        # Create 'latest' directory copy (point to run folder)
        try:
            latest_dir = Path(output_dir) / 'latest'
            if latest_dir.exists():
                import shutil
                shutil.rmtree(latest_dir)
            
            import shutil
            shutil.copytree(base_dir, latest_dir)
            print(f"📌 Latest run: {latest_dir}")
        except Exception as e:
            print(f"⚠️ Could not create latest copy: {e}")
    
    def print_summary(self, df_results: pd.DataFrame, top_n: int = 10):
        """
        Print summary of optimization results
        
        Args:
            df_results: Results DataFrame
            top_n: Number of top results to show
        """
        if len(df_results) == 0:
            print("❌ No valid results found")
            return
        
        print("\n" + "="*100)
        print(f"📊 OPTIMIZATION RESULTS - TOP {top_n}")
        print("="*100)
        
        # Display settings
        pd.set_option('display.max_columns', None)
        pd.set_option('display.width', None)
        pd.set_option('display.max_colwidth', None)
        
        # Show top results
        display_cols = [
            'return_pct', 'sharpe_ratio', 'win_rate', 'profit_factor',
            'total_trades', 'st_mult', 'sma_fast', 'sma_slow', 
            'bb_std', 'tp_sl'
        ]
        
        print(df_results[display_cols].head(top_n).to_string(index=True))
        
        print("\n" + "="*100)
        print(f"� CAPITAL PERFORMANCE")
        print("="*100)
        best_return_pct = df_results.iloc[0]['return_pct']
        best_total_pnl = df_results.iloc[0]['total_pnl']
        print(f"Initial Capital: ${self.initial_capital:,.2f}")
        print(f"Best Final Capital: ${self.initial_capital + best_total_pnl:,.2f}")
        print(f"Best P&L: ${best_total_pnl:,.2f} ({best_return_pct:.3f}%)")
        
        print("\n" + "="*100)
        print(f"📈 BEST METRICS ACROSS ALL STRATEGIES")
        print("="*100)
        print(f"📈 Best Return: {df_results['return_pct'].max():.2f}%")
        print(f"🎯 Best Sharpe: {df_results['sharpe_ratio'].max():.2f}")
        print(f"✅ Best Win Rate: {df_results['win_rate'].max():.1f}%")
        print(f"💰 Best Profit Factor: {df_results['profit_factor'].max():.2f}")
        
        # Calculate recovery factor (Return / Max Drawdown)
        df_results_temp = df_results.copy()
        df_results_temp['recovery_factor'] = df_results_temp['return_pct'] / df_results_temp['max_drawdown_pct'].abs()
        print(f"🔄 Best Recovery Factor: {df_results_temp['recovery_factor'].max():.2f}")
        print("="*100 + "\n")


def main():
    """Main optimization routine"""
    import argparse
    
    # Parse command-line arguments
    parser = argparse.ArgumentParser(description='Strategy Parameter Optimization with Train/Test Split')
    parser.add_argument('--instrument', default='GOLD', help='Instrument to optimize')
    parser.add_argument('--timeframe', default='M5', help='Timeframe')
    parser.add_argument('--max-bars', type=int, default=5000, help='Max bars to load')
    parser.add_argument('--capital', type=float, default=10000.0, help='Initial capital')
    parser.add_argument('--mode', default='quick', choices=['short', 'quick', 'medium', 'full', 'intraday'], help='Optimization mode')
    parser.add_argument('--position-size', type=float, default=10.0, help='Position size in lots')
    parser.add_argument('--no-parallel', action='store_true', help='Disable parallel processing')
    parser.add_argument('--n-jobs', type=int, default=-1, help='Number of parallel workers')
    parser.add_argument('--validation-split', type=float, default=0.0, help='Fraction for test set (0.3 = 30%% test, 0 = no split)')
    
    args = parser.parse_args()
    
    print("\n" + "="*70)
    print("🎯 Strategy Parameter Optimization")
    if args.validation_split > 0:
        print(f"✨ WITH OUT-OF-SAMPLE VALIDATION ({args.validation_split*100:.0f}% test set)")
    print("="*70 + "\n")
    
    # Config from args
    EPIC = args.instrument
    RESOLUTION = args.timeframe
    MAX_BARS = args.max_bars
    INITIAL_CAPITAL = args.capital
    MODE = args.mode
    N_JOBS = args.n_jobs
    PARALLEL = not args.no_parallel
    VALIDATION_SPLIT = args.validation_split
    
    # Load data
    print(f"📊 Loading {EPIC} {RESOLUTION} data from cache...")
    df = load_cached_data(EPIC, RESOLUTION, MAX_BARS)
    
    if df is None:
        print("❌ Could not load data")
        sys.exit(1)
    
    print(f"✅ Loaded {len(df)} bars")
    print(f"   Range: {df.index[0]} to {df.index[-1]}")
    
    # Run optimization
    optimizer = StrategyOptimizer(df, INITIAL_CAPITAL, EPIC, RESOLUTION, n_jobs=N_JOBS, validation_split=VALIDATION_SPLIT)
    results_df = optimizer.run_optimization(mode=MODE, parallel=PARALLEL)
    
    # Show summary
    optimizer.print_summary(results_df, top_n=10)
    
    # Export results
    optimizer.export_results(results_df)
    
    if VALIDATION_SPLIT > 0:
        print("\n" + "="*70)
        print("📈 OUT-OF-SAMPLE VALIDATION ENABLED")
        print("="*70)
        print("✅ Results include both IN-SAMPLE (train) and OUT-OF-SAMPLE (test) metrics")
        print(f"   - Train columns: return_pct, sharpe_ratio, win_rate, etc.")
        print(f"   - Test columns: test_return_pct, test_sharpe_ratio, test_win_rate, etc.")
        print(f"   - Degradation: oos_degradation_pct shows performance drop from train to test")
        print("\n💡 TIP: Use scripts/analyze-optimization-results.py --mode validate to analyze")
        print("="*70 + "\n")
    
    print("✅ Optimization complete!\n")


if __name__ == '__main__':
    main()

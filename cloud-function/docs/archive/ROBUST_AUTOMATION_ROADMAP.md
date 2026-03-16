# Robust Trading Automation Roadmap
## Moving Beyond TradingView Dependency

**Based on:** Ernie Chan's "Quantitative Trading" Framework  
**Current Status:** TradingView-dependent with webhook triggers  
**Goal:** Independent, backtested, self-contained trading system

---

## 🚨 Critical Problem: TradingView Dependency

### Why TradingView is a Drawback

| Issue | Impact | Solution |
|-------|--------|----------|
| **Single Point of Failure** | If TV goes down, trading stops | Python-based signal generation |
| **Limited Backtesting** | TV backtester doesn't include spreads/slippage | Custom backtest engine |
| **No Live Monitoring** | Can't track real-time performance metrics | Build monitoring system |
| **Webhook Delays** | 3-5 second latency on alerts | Direct market data → signals |
| **Can't Paper Trade Properly** | TV strategy ≠ real execution | Python simulation environment |
| **No Position Sizing** | Fixed size=200, no Kelly Criterion | Dynamic position sizing in Python |
| **Parameter Optimization** | Manual trial/error in TV | Automated optimization in Python |

**Ernie Chan's Warning:**
> "Any system that depends on a third-party service for signal generation is not production-ready. You must control the entire stack from data ingestion to order execution."

---

## 📊 Missing Pieces for Robust Automation

### 1. ❌ Data Pipeline (Critical)
**What You Have:** TradingView charts (visual)  
**What You Need:** Automated historical + real-time data fetching

### 2. ❌ Signal Generation Engine (Critical)
**What You Have:** PineScript strategy in TradingView  
**What You Need:** Python strategy that generates signals independently

### 3. ❌ Backtesting Framework (Critical)
**What You Have:** TradingView replay mode (unrealistic)  
**What You Need:** Python backtester with transaction costs

### 4. ❌ Performance Tracking (Critical)
**What You Have:** None  
**What You Need:** Sharpe ratio, drawdown, win rate calculations

### 5. ❌ Position Sizing (High Priority)
**What You Have:** Fixed size=200  
**What You Need:** Kelly Criterion-based dynamic sizing

### 6. ❌ Risk Management (High Priority)
**What You Have:** Basic stop loss  
**What You Need:** Drawdown limits, correlation checks, exposure limits

### 7. ❌ Market Regime Detection (Medium Priority)
**What You Have:** Same strategy always  
**What You Need:** Adaptive strategy selection (trending vs ranging)

### 8. ✅ Execution Layer (You Have This!)
**Status:** Cloud Function with Capital.com API integration ✓

---

## 🏗️ Implementation Roadmap

### Phase 1: Data Infrastructure (Week 1) 🔴 START HERE

**Goal:** Get historical data from Capital.com for backtesting

```python
# File: src/data_fetcher.py
import requests
import pandas as pd
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)

class CapitalComDataFetcher:
    """
    Fetch historical price data from Capital.com
    Ernie Chan: "Quality data is the foundation of quantitative trading"
    """
    
    def __init__(self, api_key, username, password):
        self.api_key = api_key
        self.username = username
        self.password = password
        self.base_url = "https://api-capital.backend-capital.com"
        self.token = None
        
    def authenticate(self):
        """Get authentication token"""
        url = f"{self.base_url}/api/v1/session"
        headers = {
            'X-CAP-API-KEY': self.api_key,
            'Content-Type': 'application/json'
        }
        payload = {
            'identifier': self.username,
            'password': self.password,
            'encryptedPassword': False
        }
        
        response = requests.post(url, json=payload, headers=headers)
        if response.ok:
            self.token = response.headers.get('CST')
            self.security_token = response.headers.get('X-SECURITY-TOKEN')
            logger.info("✅ Authentication successful")
            return True
        else:
            logger.error(f"❌ Authentication failed: {response.text}")
            return False
    
    def fetch_historical_prices(self, epic, resolution='MINUTE', num_points=1000):
        """
        Fetch historical price data
        
        Args:
            epic: Instrument identifier (e.g., 'GOLD', 'EURUSD')
            resolution: MINUTE, MINUTE_5, MINUTE_15, HOUR, HOUR_4, DAY, WEEK
            num_points: Number of data points (max 1000 per request)
            
        Returns:
            pandas DataFrame with OHLCV data
        """
        if not self.token:
            if not self.authenticate():
                return None
        
        url = f"{self.base_url}/api/v1/prices/{epic}"
        headers = {
            'X-CAP-API-KEY': self.api_key,
            'CST': self.token,
            'X-SECURITY-TOKEN': self.security_token
        }
        params = {
            'resolution': resolution,
            'max': num_points  # Capital.com max is 1000
        }
        
        response = requests.get(url, headers=headers, params=params)
        
        if not response.ok:
            logger.error(f"Failed to fetch data: {response.text}")
            return None
        
        data = response.json()
        prices = data.get('prices', [])
        
        # Convert to pandas DataFrame
        df_data = []
        for bar in prices:
            df_data.append({
                'timestamp': pd.to_datetime(bar['snapshotTimeUTC']),
                'open': float(bar['openPrice']['bid']),
                'high': float(bar['highPrice']['bid']),
                'low': float(bar['lowPrice']['bid']),
                'close': float(bar['closePrice']['bid']),
                'volume': int(bar['lastTradedVolume'])
            })
        
        df = pd.DataFrame(df_data)
        df.set_index('timestamp', inplace=True)
        df.sort_index(inplace=True)
        
        logger.info(f"✅ Fetched {len(df)} bars for {epic} ({resolution})")
        return df
    
    def fetch_multiple_timeframes(self, epic, days_back=90):
        """
        Fetch data for multiple timeframes (for comprehensive backtesting)
        Chan: "Test your strategy on multiple timeframes"
        """
        timeframes = {
            'M5': 'MINUTE_5',
            'M15': 'MINUTE_15', 
            'H1': 'HOUR',
            'H4': 'HOUR_4',
            'D1': 'DAY'
        }
        
        data = {}
        for tf_name, resolution in timeframes.items():
            df = self.fetch_historical_prices(epic, resolution, 1000)
            if df is not None:
                data[tf_name] = df
        
        return data


# Usage Example:
if __name__ == "__main__":
    import json
    import os
    from dotenv import load_dotenv
    
    load_dotenv()
    secrets = json.loads(os.getenv('apicredentials', '{}'))
    
    fetcher = CapitalComDataFetcher(
        api_key=secrets['apikey'],
        username=secrets['username'],
        password=secrets['password']
    )
    
    # Fetch 5-minute data for GOLD
    gold_data = fetcher.fetch_historical_prices('GOLD', 'MINUTE_5', 1000)
    
    if gold_data is not None:
        print(gold_data.head())
        print(f"\\nData range: {gold_data.index[0]} to {gold_data.index[-1]}")
        print(f"Total bars: {len(gold_data)}")
        
        # Save to CSV for analysis
        gold_data.to_csv('gold_5min_historical.csv')
        print("✅ Saved to gold_5min_historical.csv")
```

**Action:** Create this file and test data fetching
```bash
cd /Users/kirtanbhatt/code/stockScreener/cloud-function
python -c "from src.data_fetcher import CapitalComDataFetcher; print('Import successful')"
```

---

### Phase 2: Strategy Implementation in Python (Week 1-2)

**Goal:** Replicate your TradingView strategy in Python

```python
# File: src/strategy.py
import pandas as pd
import numpy as np
import pandas_ta as ta
import logging

logger = logging.getLogger(__name__)

class SupertrendVWAPStrategy:
    """
    Python implementation of your TradingView strategy
    
    Indicators:
    - Supertrend (momentum)
    - Bollinger Bands (mean reversion)
    - VWAP (institutional levels)
    - MA55 (trend filter)
    
    Chan's Principle: "Know whether you're trading mean reversion or momentum"
    """
    
    def __init__(self, params=None):
        # Default parameters (from your PineScript)
        self.params = params or {
            'atr_period': 21,
            'atr_factor': 3.0,
            'bb_length': 20,
            'bb_mult': 1.0,
            'ma_period': 55,
            'use_supertrend': True,
            'use_bb': False,
            'use_vwap': True,
            'use_ma': True,
            'start_hour': 3,
            'end_hour': 22,
            'stoploss_factor': 0.5,  # SL = 50% of TP distance
            'hist_bars': 50,  # Lookback for support/resistance
        }
    
    def calculate_indicators(self, df):
        """
        Calculate all technical indicators
        Returns: DataFrame with indicator columns added
        """
        df = df.copy()
        
        # 1. Supertrend
        if self.params['use_supertrend']:
            supertrend = ta.supertrend(
                df['high'], 
                df['low'], 
                df['close'],
                length=self.params['atr_period'],
                multiplier=self.params['atr_factor']
            )
            df['supertrend'] = supertrend[f"SUPERT_{self.params['atr_period']}_{self.params['atr_factor']}"]
            df['supertrend_direction'] = supertrend[f"SUPERTd_{self.params['atr_period']}_{self.params['atr_factor']}"]
            df['trend_change'] = df['supertrend_direction'].diff()
        
        # 2. Bollinger Bands
        if self.params['use_bb']:
            bb = ta.bbands(
                df['close'],
                length=self.params['bb_length'],
                std=self.params['bb_mult']
            )
            df['bb_upper'] = bb[f"BBU_{self.params['bb_length']}_{self.params['bb_mult']}"]
            df['bb_mid'] = bb[f"BBM_{self.params['bb_length']}_{self.params['bb_mult']}"]
            df['bb_lower'] = bb[f"BBL_{self.params['bb_length']}_{self.params['bb_mult']}"]
        
        # 3. VWAP (daily reset)
        if self.params['use_vwap']:
            # Simple VWAP calculation (for intraday data)
            df['vwap'] = (df['close'] * df['volume']).cumsum() / df['volume'].cumsum()
            # For proper daily VWAP, would need to reset at start of each day
        
        # 4. Moving Average
        if self.params['use_ma']:
            df['ma55'] = ta.sma(df['close'], length=self.params['ma_period'])
        
        # 5. ATR (for stop loss calculation)
        df['atr'] = ta.atr(df['high'], df['low'], df['close'], length=self.params['atr_period'])
        
        # 6. Support/Resistance
        df['swing_high'] = df['high'].rolling(self.params['hist_bars']).max()
        df['swing_low'] = df['low'].rolling(self.params['hist_bars']).min()
        
        return df
    
    def generate_signals(self, df):
        """
        Generate buy/sell signals based on strategy logic
        
        Returns: DataFrame with 'signal' column
            1 = BUY
            -1 = SELL
            0 = HOLD
        """
        df = self.calculate_indicators(df)
        df['signal'] = 0
        
        # Time filter (only trade during specified hours)
        df['hour'] = df.index.hour
        df['in_trade_time'] = (df['hour'] >= self.params['start_hour']) & (df['hour'] < self.params['end_hour'])
        
        # Long condition (from your PineScript)
        long_conditions = [
            df['in_trade_time'],
        ]
        
        if self.params['use_supertrend']:
            long_conditions.append(df['trend_change'] < 0)  # Supertrend turns bullish
        
        if self.params['use_bb']:
            long_conditions.append(df['close'] < df['bb_upper'])
        
        if self.params['use_vwap']:
            long_conditions.append(df['close'] > df['vwap'])
        
        if self.params['use_ma']:
            long_conditions.append(df['close'] > df['ma55'])
        
        # Short condition
        short_conditions = [
            df['in_trade_time'],
        ]
        
        if self.params['use_supertrend']:
            short_conditions.append(df['trend_change'] > 0)  # Supertrend turns bearish
        
        if self.params['use_bb']:
            short_conditions.append(df['close'] > df['bb_lower'])
        
        if self.params['use_vwap']:
            short_conditions.append(df['close'] < df['vwap'])
        
        if self.params['use_ma']:
            short_conditions.append(df['close'] < df['ma55'])
        
        # Apply conditions
        df.loc[pd.concat(long_conditions, axis=1).all(axis=1), 'signal'] = 1
        df.loc[pd.concat(short_conditions, axis=1).all(axis=1), 'signal'] = -1
        
        return df
    
    def calculate_stop_and_target(self, df, entry_price, direction):
        """
        Calculate stop loss and take profit levels
        
        Args:
            df: DataFrame with indicators
            entry_price: Entry price
            direction: 1 for long, -1 for short
            
        Returns:
            dict with stop_loss, take_profit levels
        """
        current_row = df.iloc[-1]
        
        if direction == 1:  # Long
            # Support-based stop
            support = current_row['swing_low']
            # TP based on distance to resistance
            resistance = current_row['swing_high']
            fib_range = resistance - entry_price
            
            take_profit_1 = entry_price + fib_range * 0.7
            take_profit_2 = entry_price + fib_range * 0.8
            take_profit_3 = entry_price + fib_range * 0.9
            
            # Stop loss: 50% of TP distance
            tp_distance = take_profit_1 - entry_price
            stop_loss = entry_price - (tp_distance * self.params['stoploss_factor'])
            
            # Alternative: ATR-based stop
            atr_stop = entry_price - (current_row['atr'] * 2.0)
            
            # Use tighter of the two
            stop_loss = max(stop_loss, atr_stop, support)
            
        else:  # Short
            resistance = current_row['swing_high']
            support = current_row['swing_low']
            fib_range = entry_price - support
            
            take_profit_1 = entry_price - fib_range * 0.7
            take_profit_2 = entry_price - fib_range * 0.8
            take_profit_3 = entry_price - fib_range * 0.9
            
            tp_distance = entry_price - take_profit_1
            stop_loss = entry_price + (tp_distance * self.params['stoploss_factor'])
            
            atr_stop = entry_price + (current_row['atr'] * 2.0)
            stop_loss = min(stop_loss, atr_stop, resistance)
        
        return {
            'stop_loss': stop_loss,
            'take_profit_1': take_profit_1,
            'take_profit_2': take_profit_2,
            'take_profit_3': take_profit_3,
            'atr': current_row['atr']
        }


# Usage Example:
if __name__ == "__main__":
    # Load data
    df = pd.read_csv('gold_5min_historical.csv', index_col=0, parse_dates=True)
    
    # Initialize strategy
    strategy = SupertrendVWAPStrategy()
    
    # Generate signals
    df_with_signals = strategy.generate_signals(df)
    
    # Show recent signals
    signals = df_with_signals[df_with_signals['signal'] != 0].tail(10)
    print("Recent signals:")
    print(signals[['close', 'signal', 'ma55', 'vwap']])
```

---

### Phase 3: Backtesting Engine (Week 2) 🔴 CRITICAL

**This is THE most important piece according to Ernie Chan**

```python
# File: src/backtester.py
import pandas as pd
import numpy as np
import logging
from typing import Dict, List

logger = logging.getLogger(__name__)

class Backtest:
    """
    Backtesting engine with realistic transaction costs
    
    Ernie Chan's Requirements:
    - Include spreads, slippage, commissions
    - Track equity curve
    - Calculate Sharpe ratio, max drawdown
    - Out-of-sample validation
    """
    
    def __init__(self, 
                 initial_capital=10000,
                 spread_pips=2.0,        # Typical spread for majors
                 slippage_pips=0.5,      # Average slippage
                 commission=0,           # Capital.com is commission-free
                 position_size_pct=0.02  # 2% risk per trade
                ):
        
        self.initial_capital = initial_capital
        self.spread_pips = spread_pips
        self.slippage_pips = slippage_pips
        self.commission = commission
        self.position_size_pct = position_size_pct
        
        # Track results
        self.trades = []
        self.equity_curve = []
        self.current_capital = initial_capital
        self.current_position = None
        
    def run(self, df, strategy, epic='GOLD'):
        """
        Run backtest on historical data
        
        Args:
            df: DataFrame with OHLCV data
            strategy: Strategy object with generate_signals() method
            epic: Instrument name (for pip value calculation)
            
        Returns:
            dict with performance metrics
        """
        # Generate signals
        df = strategy.generate_signals(df)
        
        # Determine pip value for position sizing
        pip_value = self._get_pip_value(epic)
        
        # Iterate through each bar
        for i in range(len(df)):
            current_bar = df.iloc[i]
            current_price = current_bar['close']
            
            # Update equity curve
            if self.current_position:
                unrealized_pnl = self._calculate_unrealized_pnl(
                    self.current_position, 
                    current_price
                )
                current_equity = self.current_capital + unrealized_pnl
            else:
                current_equity = self.current_capital
            
            self.equity_curve.append({
                'timestamp': current_bar.name,
                'equity': current_equity,
                'cash': self.current_capital,
                'returns': (current_equity - self.initial_capital) / self.initial_capital
            })
            
            # Check for exits first
            if self.current_position:
                exit_signal = self._check_exit(current_bar, self.current_position)
                if exit_signal:
                    self._close_position(current_bar, exit_signal['reason'])
            
            # Check for new entry
            if current_bar['signal'] != 0 and not self.current_position:
                # Calculate position size
                stop_distance = self._calculate_stop_distance(df.iloc[:i+1], strategy)
                if stop_distance > 0:
                    position_size = self._calculate_position_size(stop_distance, pip_value)
                    
                    # Open position
                    self._open_position(
                        current_bar,
                        direction='LONG' if current_bar['signal'] == 1 else 'SHORT',
                        size=position_size,
                        strategy=strategy,
                        df=df.iloc[:i+1]
                    )
        
        # Close any open position at end
        if self.current_position:
            self._close_position(df.iloc[-1], 'END_OF_DATA')
        
        # Calculate performance metrics
        return self._calculate_metrics()
    
    def _get_pip_value(self, epic):
        """Get pip value for position sizing"""
        pip_values = {
            'GOLD': 0.01,     # Gold: $0.01 per pip
            'EURUSD': 0.0001, # Forex: 0.0001
            'GBPUSD': 0.0001,
        }
        return pip_values.get(epic, 0.0001)
    
    def _calculate_stop_distance(self, df_history, strategy):
        """Calculate stop distance from current price"""
        current_price = df_history.iloc[-1]['close']
        levels = strategy.calculate_stop_and_target(
            df_history, 
            current_price, 
            direction=1  # Doesn't matter for stop calculation
        )
        return abs(current_price - levels['stop_loss'])
    
    def _calculate_position_size(self, stop_distance, pip_value):
        """
        Calculate position size based on risk percentage
        Chan: "Position sizing is more important than entry signals"
        """
        risk_amount = self.current_capital * self.position_size_pct
        stop_distance_pips = stop_distance / pip_value
        
        # Position size = Risk Amount / (Stop Distance in pips * pip_value * leverage)
        # For simplicity, assume 1:1 (no leverage)
        position_size = risk_amount / stop_distance
        
        return position_size
    
    def _open_position(self, bar, direction, size, strategy, df):
        """Open a new position"""
        entry_price = bar['close']
        
        # Apply transaction costs
        if direction == 'LONG':
            # Buy at ask (add spread)
            entry_price += (self.spread_pips + self.slippage_pips) * self._get_pip_value('GOLD')
        else:
            # Sell at bid (subtract spread)
            entry_price -= (self.spread_pips + self.slippage_pips) * self._get_pip_value('GOLD')
        
        # Calculate stops and targets
        levels = strategy.calculate_stop_and_target(df, entry_price, 1 if direction == 'LONG' else -1)
        
        self.current_position = {
            'entry_time': bar.name,
            'entry_price': entry_price,
            'direction': direction,
            'size': size,
            'stop_loss': levels['stop_loss'],
            'take_profit': levels['take_profit_1'],
            'highest_price': entry_price if direction == 'LONG' else None,
            'lowest_price': entry_price if direction == 'SHORT' else None,
        }
        
        logger.info(f"📈 ENTER {direction} at {entry_price:.2f} | SL: {levels['stop_loss']:.2f} | TP: {levels['take_profit_1']:.2f}")
    
    def _check_exit(self, bar, position):
        """Check if position should be exited"""
        # Check stop loss
        if position['direction'] == 'LONG':
            if bar['low'] <= position['stop_loss']:
                return {'reason': 'STOP_LOSS', 'exit_price': position['stop_loss']}
            if bar['high'] >= position['take_profit']:
                return {'reason': 'TAKE_PROFIT', 'exit_price': position['take_profit']}
        else:  # SHORT
            if bar['high'] >= position['stop_loss']:
                return {'reason': 'STOP_LOSS', 'exit_price': position['stop_loss']}
            if bar['low'] <= position['take_profit']:
                return {'reason': 'TAKE_PROFIT', 'exit_price': position['take_profit']}
        
        return None
    
    def _close_position(self, bar, reason):
        """Close current position"""
        if not self.current_position:
            return
        
        exit_price = bar['close']
        
        # Apply transaction costs
        if self.current_position['direction'] == 'LONG':
            # Sell at bid (subtract spread)
            exit_price -= (self.spread_pips + self.slippage_pips) * self._get_pip_value('GOLD')
        else:
            # Buy at ask (add spread)
            exit_price += (self.spread_pips + self.slippage_pips) * self._get_pip_value('GOLD')
        
        # Calculate P&L
        if self.current_position['direction'] == 'LONG':
            pnl = (exit_price - self.current_position['entry_price']) * self.current_position['size']
        else:
            pnl = (self.current_position['entry_price'] - exit_price) * self.current_position['size']
        
        # Subtract commission
        pnl -= self.commission * 2  # Entry + exit
        
        # Update capital
        self.current_capital += pnl
        
        # Record trade
        holding_period = (bar.name - self.current_position['entry_time']).total_seconds() / 3600
        
        trade_record = {
            'entry_time': self.current_position['entry_time'],
            'exit_time': bar.name,
            'direction': self.current_position['direction'],
            'entry_price': self.current_position['entry_price'],
            'exit_price': exit_price,
            'size': self.current_position['size'],
            'pnl': pnl,
            'pnl_pct': (pnl / self.current_capital) * 100,
            'holding_hours': holding_period,
            'exit_reason': reason
        }
        
        self.trades.append(trade_record)
        
        logger.info(f"📉 EXIT {reason} at {exit_price:.2f} | P&L: ${pnl:.2f} ({trade_record['pnl_pct']:.2f}%)")
        
        self.current_position = None
    
    def _calculate_unrealized_pnl(self, position, current_price):
        """Calculate unrealized P&L for open position"""
        if position['direction'] == 'LONG':
            return (current_price - position['entry_price']) * position['size']
        else:
            return (position['entry_price'] - current_price) * position['size']
    
    def _calculate_metrics(self):
        """
        Calculate performance metrics
        Chan's Essential Metrics: Sharpe, Max Drawdown, Win Rate, Profit Factor
        """
        if not self.trades:
            return {
                'error': 'No trades executed',
                'total_trades': 0
            }
        
        trades_df = pd.DataFrame(self.trades)
        equity_df = pd.DataFrame(self.equity_curve)
        
        # 1. Total return
        total_return = (self.current_capital - self.initial_capital) / self.initial_capital
        
        # 2. Number of trades
        total_trades = len(self.trades)
        winning_trades = trades_df[trades_df['pnl'] > 0]
        losing_trades = trades_df[trades_df['pnl'] < 0]
        
        # 3. Win rate
        win_rate = len(winning_trades) / total_trades if total_trades > 0 else 0
        
        # 4. Average win/loss
        avg_win = winning_trades['pnl'].mean() if len(winning_trades) > 0 else 0
        avg_loss = abs(losing_trades['pnl'].mean()) if len(losing_trades) > 0 else 0
        
        # 5. Profit factor
        gross_profit = winning_trades['pnl'].sum() if len(winning_trades) > 0 else 0
        gross_loss = abs(losing_trades['pnl'].sum()) if len(losing_trades) > 0 else 0
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0
        
        # 6. Sharpe ratio (annualized)
        returns = equity_df['returns'].pct_change().dropna()
        if len(returns) > 0 and returns.std() > 0:
            sharpe_ratio = (returns.mean() / returns.std()) * np.sqrt(252 * 24)  # Annualized for hourly data
        else:
            sharpe_ratio = 0
        
        # 7. Maximum drawdown
        equity_curve = equity_df['equity'].values
        peak = np.maximum.accumulate(equity_curve)
        drawdown = (equity_curve - peak) / peak
        max_drawdown = np.min(drawdown)
        
        # 8. Calmar ratio (annual return / max drawdown)
        annual_return = total_return * (252 / (len(equity_df) / (24 * 5)))  # Rough annualization
        calmar_ratio = abs(annual_return / max_drawdown) if max_drawdown < 0 else 0
        
        # 9. Average holding period
        avg_holding_hours = trades_df['holding_hours'].mean()
        
        # Chan's Evaluation
        evaluation = "❌ NOT TRADABLE"
        if sharpe_ratio > 1.0 and max_drawdown > -0.20 and profit_factor > 1.5:
            evaluation = "✅ GOOD - Ready for live trading"
        elif sharpe_ratio > 0.5 and max_drawdown > -0.30:
            evaluation = "⚠️ MARGINAL - Needs improvement"
        
        return {
            'total_return': total_return,
            'total_return_pct': total_return * 100,
            'final_capital': self.current_capital,
            'total_trades': total_trades,
            'winning_trades': len(winning_trades),
            'losing_trades': len(losing_trades),
            'win_rate': win_rate,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'profit_factor': profit_factor,
            'sharpe_ratio': sharpe_ratio,
            'max_drawdown': max_drawdown,
            'max_drawdown_pct': max_drawdown * 100,
            'calmar_ratio': calmar_ratio,
            'avg_holding_hours': avg_holding_hours,
            'evaluation': evaluation,
            'trades': trades_df.to_dict('records'),
            'equity_curve': equity_df.to_dict('records')
        }


# Usage Example:
if __name__ == "__main__":
    from src.data_fetcher import CapitalComDataFetcher
    from src.strategy import SupertrendVWAPStrategy
    
    # 1. Fetch data
    fetcher = CapitalComDataFetcher(api_key, username, password)
    df = fetcher.fetch_historical_prices('GOLD', 'MINUTE_5', 1000)
    
    # 2. Initialize strategy
    strategy = SupertrendVWAPStrategy()
    
    # 3. Run backtest
    backtest = Backtest(initial_capital=10000)
    results = backtest.run(df, strategy, 'GOLD')
    
    # 4. Print results
    print("\\n" + "="*60)
    print("BACKTEST RESULTS")
    print("="*60)
    print(f"Total Return: {results['total_return_pct']:.2f}%")
    print(f"Total Trades: {results['total_trades']}")
    print(f"Win Rate: {results['win_rate']:.1%}")
    print(f"Profit Factor: {results['profit_factor']:.2f}")
    print(f"Sharpe Ratio: {results['sharpe_ratio']:.2f}")
    print(f"Max Drawdown: {results['max_drawdown_pct']:.2f}%")
    print(f"\\n{results['evaluation']}")
    print("="*60)
```

---

### Phase 4: Entry/Exit Strategy Design (Week 2-3)

**Ernie Chan's Framework for Entry/Exit:**

#### A. Entry Strategy (When to Enter)

**Current Issues with Your TradingView Strategy:**
1. **Mixed Signals**: Momentum (Supertrend) + Mean Reversion (BB)
2. **No Quality Filter**: Enters on any crossover
3. **No Regime Awareness**: Same strategy in trending vs ranging markets

**Chan's Recommendation: Market Regime-Based Entry**

```python
# File: src/entry_exit_strategies.py
import pandas as pd
import numpy as np

class EntryExitManager:
    """
    Sophisticated entry/exit logic based on market regime
    Chan: "Different markets require different strategies"
    """
    
    @staticmethod
    def detect_market_regime(df, lookback=100):
        """
        Determine if market is trending or ranging
        
        Returns:
            'trending_up', 'trending_down', 'ranging', or 'high_volatility'
        """
        # 1. Calculate ADX (trend strength)
        adx = calculate_adx(df, period=14)
        
        # 2. Calculate Hurst exponent (trend persistence)
        hurst = calculate_hurst_exponent(df['close'].tail(lookback))
        
        # 3. Calculate volatility
        returns = df['close'].pct_change()
        volatility = returns.std() * np.sqrt(252 * 24)  # Annualized
        
        # Decision logic
        current_adx = adx.iloc[-1]
        
        if volatility > 0.5:  # High volatility
            return 'high_volatility'  # DON'T TRADE
        
        if current_adx > 25 and hurst > 0.55:  # Strong trend
            # Check direction
            ma_short = df['close'].rolling(20).mean().iloc[-1]
            ma_long = df['close'].rolling(50).mean().iloc[-1]
            
            if ma_short > ma_long:
                return 'trending_up'
            else:
                return 'trending_down'
        
        elif current_adx < 20 and hurst < 0.45:  # Ranging
            return 'ranging'
        
        else:
            return 'undefined'  # Don't trade
    
    @staticmethod
    def momentum_entry(df, regime):
        """
        Entry logic for trending markets
        Chan: "Momentum strategies work in trending markets"
        """
        if regime not in ['trending_up', 'trending_down']:
            return None
        
        # Use Supertrend + MA filter
        supertrend_signal = df['trend_change'].iloc[-1]
        above_ma = df['close'].iloc[-1] > df['ma55'].iloc[-1]
        
        # Quality filter: Check momentum consistency
        recent_returns = df['close'].pct_change().tail(10)
        consistency = (recent_returns > 0).sum() / len(recent_returns)
        
        if regime == 'trending_up':
            if supertrend_signal < 0 and above_ma and consistency > 0.6:
                return {
                    'action': 'BUY',
                    'confidence': 'HIGH',
                    'reason': 'Momentum entry in uptrend'
                }
        
        elif regime == 'trending_down':
            if supertrend_signal > 0 and not above_ma and consistency < 0.4:
                return {
                    'action': 'SELL',
                    'confidence': 'HIGH',
                    'reason': 'Momentum entry in downtrend'
                }
        
        return None
    
    @staticmethod
    def mean_reversion_entry(df, regime):
        """
        Entry logic for ranging markets
        Chan: "Mean reversion works in ranging markets"
        """
        if regime != 'ranging':
            return None
        
        # Use Bollinger Bands + RSI
        current_price = df['close'].iloc[-1]
        bb_upper = df['bb_upper'].iloc[-1]
        bb_lower = df['bb_lower'].iloc[-1]
        bb_mid = df['bb_mid'].iloc[-1]
        
        # Calculate RSI (overbought/oversold)
        rsi = calculate_rsi(df['close'], period=14).iloc[-1]
        
        # Calculate z-score
        z_score = (current_price - bb_mid) / (bb_upper - bb_mid)
        
        # Mean reversion entry
        if current_price < bb_lower and rsi < 30 and z_score < -1.5:
            return {
                'action': 'BUY',
                'confidence': 'HIGH',
                'reason': 'Mean reversion - oversold in range'
            }
        
        elif current_price > bb_upper and rsi > 70 and z_score > 1.5:
            return {
                'action': 'SELL',
                'confidence': 'HIGH',
                'reason': 'Mean reversion - overbought in range'
            }
        
        return None
    
    @staticmethod
    def get_entry_signal(df):
        """
        Main entry decision logic
        """
        # 1. Detect regime
        regime = EntryExitManager.detect_market_regime(df)
        
        # 2. Don't trade in unfavorable conditions
        if regime in ['high_volatility', 'undefined']:
            return {
                'action': 'HOLD',
                'reason': f'Regime: {regime} - not tradable'
            }
        
        # 3. Apply appropriate strategy
        if regime in ['trending_up', 'trending_down']:
            signal = EntryExitManager.momentum_entry(df, regime)
        else:  # ranging
            signal = EntryExitManager.mean_reversion_entry(df, regime)
        
        if signal:
            signal['regime'] = regime
            return signal
        else:
            return {'action': 'HOLD', 'reason': 'No valid setup'}


def calculate_adx(df, period=14):
    """Calculate Average Directional Index"""
    import pandas_ta as ta
    adx = ta.adx(df['high'], df['low'], df['close'], length=period)
    return adx[f'ADX_{period}']


def calculate_hurst_exponent(prices, lags=range(2, 20)):
    """
    Calculate Hurst exponent
    H > 0.5: Trending
    H < 0.5: Mean reverting
    H = 0.5: Random walk
    """
    tau = [np.std(np.subtract(prices[lag:], prices[:-lag])) for lag in lags]
    poly = np.polyfit(np.log(lags), np.log(tau), 1)
    return poly[0] * 2.0


def calculate_rsi(prices, period=14):
    """Calculate Relative Strength Index"""
    delta = prices.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return rsi
```

#### B. Exit Strategy (When to Exit)

**Chan's Exit Principles:**

1. **Exit quickly on losses** (cut losses short)
2. **Let winners run** (but with trailing stops)
3. **Partial exits** (scale out at targets)
4. **Time-based exits** (if trade goes nowhere)

```python
class ExitManager:
    """
    Advanced exit logic
    Chan: "Exit strategy is MORE important than entry"
    """
    
    @staticmethod
    def check_exit(position, current_bar, df_history):
        """
        Comprehensive exit logic
        
        Returns:
            dict with exit decision or None
        """
        current_price = current_bar['close']
        entry_price = position['entry_price']
        direction = position['direction']
        
        # 1. STOP LOSS (always check first)
        if direction == 'LONG':
            if current_price <= position['stop_loss']:
                return {'action': 'EXIT', 'reason': 'STOP_LOSS', 'urgency': 'IMMEDIATE'}
        else:
            if current_price >= position['stop_loss']:
                return {'action': 'EXIT', 'reason': 'STOP_LOSS', 'urgency': 'IMMEDIATE'}
        
        # 2. TAKE PROFIT (static targets)
        if direction == 'LONG':
            if current_price >= position['take_profit']:
                return {'action': 'EXIT', 'reason': 'TAKE_PROFIT', 'urgency': 'HIGH'}
        else:
            if current_price <= position['take_profit']:
                return {'action': 'EXIT', 'reason': 'TAKE_PROFIT', 'urgency': 'HIGH'}
        
        # 3. TRAILING STOP (for winning trades)
        profit_pct = abs(current_price - entry_price) / entry_price
        if profit_pct > 0.01:  # Trade is 1%+ in profit
            trailing_stop = ExitManager.calculate_trailing_stop(
                position, current_bar, df_history
            )
            
            if direction == 'LONG' and current_price < trailing_stop:
                return {'action': 'EXIT', 'reason': 'TRAILING_STOP', 'urgency': 'HIGH'}
            elif direction == 'SHORT' and current_price > trailing_stop:
                return {'action': 'EXIT', 'reason': 'TRAILING_STOP', 'urgency': 'HIGH'}
        
        # 4. TIME-BASED EXIT (trade going nowhere)
        holding_hours = (current_bar.name - position['entry_time']).total_seconds() / 3600
        if holding_hours > 24 and abs(profit_pct) < 0.005:  # 24h+ and less than 0.5% move
            return {'action': 'EXIT', 'reason': 'TIME_DECAY', 'urgency': 'MEDIUM'}
        
        # 5. REGIME CHANGE EXIT
        current_regime = EntryExitManager.detect_market_regime(df_history)
        if current_regime == 'high_volatility':
            return {'action': 'EXIT', 'reason': 'REGIME_CHANGE', 'urgency': 'HIGH'}
        
        # 6. ADVERSE SIGNAL (opposite setup forming)
        signal = EntryExitManager.get_entry_signal(df_history)
        if signal['action'] == 'BUY' and direction == 'SHORT':
            return {'action': 'EXIT', 'reason': 'SIGNAL_REVERSAL', 'urgency': 'MEDIUM'}
        elif signal['action'] == 'SELL' and direction == 'LONG':
            return {'action': 'EXIT', 'reason': 'SIGNAL_REVERSAL', 'urgency': 'MEDIUM'}
        
        return None  # Hold position
    
    @staticmethod
    def calculate_trailing_stop(position, current_bar, df_history):
        """
        Calculate dynamic trailing stop based on ATR
        Chan: "Use ATR for trailing stops - adapts to volatility"
        """
        atr = df_history['atr'].iloc[-1]
        current_price = current_bar['close']
        
        if position['direction'] == 'LONG':
            # Trail below price by 2x ATR
            trailing_stop = current_price - (2.0 * atr)
            # Never lower the stop (only trail up)
            return max(trailing_stop, position['stop_loss'])
        else:
            # Trail above price by 2x ATR
            trailing_stop = current_price + (2.0 * atr)
            # Never raise the stop (only trail down)
            return min(trailing_stop, position['stop_loss'])
```

---

## 🎯 Complete Implementation Checklist

### Week 1: Foundation
- [ ] Create `src/data_fetcher.py` - Fetch historical data
- [ ] Test data fetching for GOLD, EURUSD, GBPUSD
- [ ] Save historical data to CSV for testing
- [ ] Create `src/strategy.py` - Python strategy implementation
- [ ] Verify strategy generates same signals as TradingView

### Week 2: Backtesting
- [ ] Create `src/backtester.py` - Backtest engine
- [ ] Run backtest on 6 months of data
- [ ] Calculate Sharpe ratio, drawdown, win rate
- [ ] **CRITICAL**: Verify Sharpe > 1.0 before going live
- [ ] Create `src/entry_exit_strategies.py` - Advanced entry/exit logic

### Week 3: Integration
- [ ] Create `src/live_signal_generator.py` - Real-time signal generation
- [ ] Integrate with Cloud Function
- [ ] Add performance tracking to Firestore
- [ ] Create monitoring dashboard

### Week 4: Testing
- [ ] Paper trade for 2 weeks minimum
- [ ] Compare paper trading vs backtest results
- [ ] Verify < 10% difference (Chan's guideline)
- [ ] Enable live trading with minimal size

---

## 📈 Expected Timeline

| Phase | Duration | Outcome |
|-------|----------|---------|
| Data Pipeline | 2-3 days | Historical data available |
| Strategy in Python | 3-4 days | Signals match TradingView |
| Backtesting | 2-3 days | Know if strategy has edge |
| Entry/Exit Logic | 4-5 days | Regime-aware trading |
| Live Integration | 3-4 days | Automated signal generation |
| Paper Trading | 14 days | Verify real performance |
| **TOTAL** | **4-5 weeks** | **Production-ready system** |

---

## 🚀 Next Immediate Action

**Run this script to start:**

```python
# File: tests/test_full_system.py
"""
Complete end-to-end test
This demonstrates the entire workflow
"""

import sys
sys.path.append('/Users/kirtanbhatt/code/stockScreener/cloud-function')

from src.data_fetcher import CapitalComDataFetcher
from src.strategy import SupertrendVWAPStrategy
from src.backtester import Backtest
import json
import os
from dotenv import load_dotenv

# Load credentials
load_dotenv()
secrets = json.loads(os.getenv('apicredentials', '{}'))

# 1. Fetch Data
print("📡 Fetching historical data...")
fetcher = CapitalComDataFetcher(
    api_key=secrets['apikey'],
    username=secrets['username'],
    password=secrets['password']
)

df = fetcher.fetch_historical_prices('GOLD', 'MINUTE_15', 1000)
print(f"✅ Fetched {len(df)} bars")

# 2. Initialize Strategy
print("\\n🎯 Initializing strategy...")
strategy = SupertrendVWAPStrategy()

# 3. Run Backtest
print("\\n⚙️ Running backtest...")
backtest = Backtest(initial_capital=10000)
results = backtest.run(df, strategy, 'GOLD')

# 4. Display Results
print("\\n" + "="*70)
print("BACKTEST RESULTS - ERNIE CHAN EVALUATION")
print("="*70)
print(f"Total Return:        {results['total_return_pct']:>8.2f}%")
print(f"Final Capital:       ${results['final_capital']:>8,.2f}")
print(f"Total Trades:        {results['total_trades']:>8}")
print(f"Win Rate:            {results['win_rate']:>8.1%}")
print(f"Profit Factor:       {results['profit_factor']:>8.2f}")
print(f"Sharpe Ratio:        {results['sharpe_ratio']:>8.2f}  {'✅ GOOD' if results['sharpe_ratio'] > 1.0 else '❌ POOR'}")
print(f"Max Drawdown:        {results['max_drawdown_pct']:>8.2f}%  {'✅ GOOD' if results['max_drawdown'] > -0.20 else '❌ HIGH'}")
print(f"Calmar Ratio:        {results['calmar_ratio']:>8.2f}")
print(f"Avg Hold Time:       {results['avg_holding_hours']:>8.1f} hours")
print("="*70)
print(f"\\n{results['evaluation']}\\n")

# Chan's Decision Framework
if results['sharpe_ratio'] > 1.0 and results['max_drawdown'] > -0.20:
    print("✅ DECISION: Proceed to paper trading")
    print("   - Run for 2 weeks")
    print("   - Track real-time performance")
    print("   - Verify results match backtest")
else:
    print("❌ DECISION: Strategy needs optimization")
    print("   - Sharpe ratio too low (need > 1.0)")
    print("   - Consider:")
    print("     • Separating momentum and mean reversion")
    print("     • Adding regime filter")
    print("     • Adjusting position sizing")
    print("     • Testing different timeframes")
```

---

## 💡 Key Takeaways (Ernie Chan's Wisdom)

1. **"Backtest or Die"**: No strategy should go live without rigorous backtesting
2. **"Transaction Costs Matter"**: Include spreads, slippage - they can destroy profitability
3. **"Sharpe > 1.0"**: Minimum threshold for considering a strategy
4. **"Know Your Regime"**: Don't trade momentum in ranging markets or mean reversion in trends
5. **"Position Sizing > Entry Signals"**: Kelly Criterion can double your returns
6. **"Out-of-Sample Validation"**: Reserve 30% of data for final test
7. **"Paper Trade First"**: 2 weeks minimum before risking real money

**Most Important Quote:**
> "The difference between profitable and unprofitable traders is not the strategy itself, but the discipline to measure, optimize, and execute it systematically."

---

Would you like me to create these files and start with the data fetcher implementation?

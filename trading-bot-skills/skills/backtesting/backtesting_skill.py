"""
Backtesting Skill - Simulates trading strategy on historical data

⚠️  SIMULATION ONLY - NO REAL ORDERS ⚠️
- Pure in-memory simulation
- Does NOT connect to Capital.com API
- Does NOT place real trades
- All trades are simulated using historical data
"""

import sys
import os
from pathlib import Path
# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

from skills.base_skill import Skill, Context


class OrderSide(Enum):
    """Trade direction"""
    BUY = 'BUY'
    SELL = 'SELL'


class OrderStatus(Enum):
    """Trade status"""
    OPEN = 'OPEN'
    CLOSED = 'CLOSED'


@dataclass
class SimulatedTrade:
    """Represents a simulated trade in backtest"""
    entry_time: datetime
    entry_price: float
    side: OrderSide
    size: float
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    
    # Exit information
    exit_time: Optional[datetime] = None
    exit_price: Optional[float] = None
    exit_reason: Optional[str] = None
    status: OrderStatus = OrderStatus.OPEN
    
    # P&L
    pnl: float = 0.0
    pnl_pct: float = 0.0
    
    # Costs
    spread_cost: float = 0.0
    slippage_cost: float = 0.0
    
    def calculate_pnl(self):
        """Calculate P&L for the trade"""
        if self.exit_price is None:
            return
        
        if self.side == OrderSide.BUY:
            pnl_points = self.exit_price - self.entry_price
        else:  # SELL
            pnl_points = self.entry_price - self.exit_price
        
        # Subtract costs
        total_costs = self.spread_cost + self.slippage_cost
        pnl_points -= total_costs
        
        self.pnl = pnl_points * self.size
        self.pnl_pct = (pnl_points / self.entry_price) * 100
    
    def to_dict(self):
        """Convert trade to dictionary"""
        return {
            'entry_time': self.entry_time,
            'entry_price': self.entry_price,
            'side': self.side.value,
            'size': self.size,
            'stop_loss': self.stop_loss,
            'take_profit': self.take_profit,
            'exit_time': self.exit_time,
            'exit_price': self.exit_price,
            'exit_reason': self.exit_reason,
            'status': self.status.value,
            'pnl': self.pnl,
            'pnl_pct': self.pnl_pct,
            'spread_cost': self.spread_cost,
            'slippage_cost': self.slippage_cost
        }


class BacktestingSkill(Skill):
    """
    Backtesting Skill - Simulates trading strategy on historical data
    
    Features:
    - Intra-candle SL/TP simulation (uses high/low to detect hits)
    - Transaction costs (spread, slippage)
    - Position sizing (fixed, percentage-based)
    - Performance metrics calculation
    - Trade history logging
    
    Example Usage:
        # Load historical candles
        df = pd.read_csv('GOLD_M5.csv')
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        
        # Create backtesting skill
        config = {
            'backtesting': {
                'initial_capital': 10000,
                'position_size': 1.0,
                'spread_cost_usd': 0.50,
                'slippage_cost_usd': 0.05,
                'stop_loss_pips': 20,
                'take_profit_pips': 40
            }
        }
        backtest = BacktestingSkill(config)
        
        # Run backtest with analysis and risk skills
        for idx, candle in df.iterrows():
            # 1. Update context with candle
            context.candle = candle.to_dict()
            context.timestamp = candle['timestamp']
            
            # 2. Run analysis skill to generate signal
            analysis_skill.execute(context)
            
            # 3. Run risk skill to validate signal
            if risk_skill.execute(context):
                # 4. Simulate order execution
                backtest.execute(context)
            
            # 5. Check for SL/TP hits
            backtest.check_exits(context)
        
        # Get results
        results = backtest.get_results()
        print(f"P&L: ${results['total_pnl']:.2f}")
        print(f"Win Rate: {results['win_rate']:.1f}%")
        print(f"Sharpe Ratio: {results['sharpe_ratio']:.2f}")
    """
    
    def __init__(self, config: dict):
        super().__init__(config)
        
        # Backtesting configuration
        bt_config = config.get('backtesting', {})
        self.initial_capital = bt_config.get('initial_capital', 10000.0)
        self.position_size = bt_config.get('position_size', 1.0)
        self.spread_cost_usd = bt_config.get('spread_cost_usd', 0.50)
        self.slippage_cost_usd = bt_config.get('slippage_cost_usd', 0.05)
        
        # Get SL/TP from risk config
        risk_config = config.get('risk', {})
        self.stop_loss_pips = risk_config.get('stop_loss_pips', 20)
        self.take_profit_pips = risk_config.get('take_profit_pips', 40)
        
        # State tracking
        self.capital = self.initial_capital
        self.equity_curve = []
        self.open_positions: List[SimulatedTrade] = []
        self.closed_positions: List[SimulatedTrade] = []
        
        # Performance tracking
        self.total_pnl = 0.0
        self.total_trades = 0
        self.winning_trades = 0
        self.losing_trades = 0
        self.max_equity = self.initial_capital
        self.max_drawdown = 0.0
        
        print(f"🧪 Backtesting Skill initialized")
        print(f"   Initial Capital: ${self.initial_capital:,.2f}")
        print(f"   Position Size: {self.position_size}")
        print(f"   SL: {self.stop_loss_pips} pips, TP: {self.take_profit_pips} pips")
    
    def validate_config(self) -> bool:
        """Validate backtesting configuration"""
        if self.initial_capital <= 0:
            print(f"❌ Invalid initial_capital: {self.initial_capital}")
            return False
        
        if self.position_size <= 0:
            print(f"❌ Invalid position_size: {self.position_size}")
            return False
        
        return True
    
    def execute(self, context: Context) -> bool:
        """
        Simulate trade execution based on signal in context.
        
        Args:
            context: Trading context with signal ('BUY' or 'SELL')
        
        Returns:
            True if trade was simulated, False otherwise
        """
        # Check if we have a signal
        if not context.signal or context.signal not in ['BUY', 'SELL']:
            return False
        
        # Check if we already have an open position
        if len(self.open_positions) > 0:
            return False
        
        # Get current price from candle
        candle = context.candle
        if not candle:
            return False
        
        entry_price = candle.get('close', candle.get('price', 0))
        if entry_price <= 0:
            return False
        
        # Calculate SL and TP
        if context.signal == 'BUY':
            side = OrderSide.BUY
            stop_loss = entry_price - self.stop_loss_pips
            take_profit = entry_price + self.take_profit_pips
        else:  # SELL
            side = OrderSide.SELL
            stop_loss = entry_price + self.stop_loss_pips
            take_profit = entry_price - self.take_profit_pips
        
        # Create simulated trade
        trade = SimulatedTrade(
            entry_time=context.timestamp,
            entry_price=entry_price,
            side=side,
            size=self.position_size,
            stop_loss=stop_loss,
            take_profit=take_profit,
            spread_cost=self.spread_cost_usd,
            slippage_cost=self.slippage_cost_usd
        )
        
        self.open_positions.append(trade)
        self.total_trades += 1
        
        print(f"📊 Simulated {side.value} @ {entry_price:.2f}, SL={stop_loss:.2f}, TP={take_profit:.2f}")
        
        return True
    
    def check_exits(self, context: Context) -> List[SimulatedTrade]:
        """
        Check if any open positions should be closed (SL/TP hit).
        Uses intra-candle high/low to detect SL/TP hits.
        
        Args:
            context: Trading context with current candle
        
        Returns:
            List of closed trades
        """
        candle = context.candle
        if not candle:
            return []
        
        high = candle.get('high', 0)
        low = candle.get('low', 0)
        close_price = candle.get('close', 0)
        
        if high <= 0 or low <= 0:
            return []
        
        closed_trades = []
        
        for trade in self.open_positions[:]:  # Iterate over copy
            exit_price = None
            exit_reason = None
            
            # Check Stop Loss
            if trade.side == OrderSide.BUY and low <= trade.stop_loss:
                exit_price = trade.stop_loss
                exit_reason = 'SL_HIT'
            elif trade.side == OrderSide.SELL and high >= trade.stop_loss:
                exit_price = trade.stop_loss
                exit_reason = 'SL_HIT'
            
            # Check Take Profit (only if SL not hit)
            elif trade.side == OrderSide.BUY and high >= trade.take_profit:
                exit_price = trade.take_profit
                exit_reason = 'TP_HIT'
            elif trade.side == OrderSide.SELL and low <= trade.take_profit:
                exit_price = trade.take_profit
                exit_reason = 'TP_HIT'
            
            # Close position if exit triggered
            if exit_price:
                self._close_position(trade, exit_price, exit_reason, context.timestamp)
                closed_trades.append(trade)
                self.open_positions.remove(trade)
        
        return closed_trades
    
    def _close_position(self, trade: SimulatedTrade, exit_price: float, exit_reason: str, exit_time: datetime):
        """Close a simulated position and calculate P&L"""
        trade.exit_price = exit_price
        trade.exit_reason = exit_reason
        trade.exit_time = exit_time
        trade.status = OrderStatus.CLOSED
        
        # Calculate P&L
        trade.calculate_pnl()
        
        # Update capital
        self.capital += trade.pnl
        self.total_pnl += trade.pnl
        
        # Update statistics
        if trade.pnl > 0:
            self.winning_trades += 1
        else:
            self.losing_trades += 1
        
        # Track equity curve
        self.equity_curve.append({
            'timestamp': exit_time,
            'equity': self.capital,
            'pnl': trade.pnl
        })
        
        # Update drawdown
        if self.capital > self.max_equity:
            self.max_equity = self.capital
        
        drawdown = self.max_equity - self.capital
        if drawdown > self.max_drawdown:
            self.max_drawdown = drawdown
        
        # Add to closed positions
        self.closed_positions.append(trade)
        
        pnl_emoji = "💰" if trade.pnl > 0 else "📉"
        print(f"{pnl_emoji} Closed {trade.side.value} @ {exit_price:.2f} ({exit_reason}): P&L=${trade.pnl:.2f}, Capital=${self.capital:,.2f}")
    
    def get_results(self) -> Dict:
        """
        Calculate and return backtest performance metrics.
        
        Returns:
            Dictionary with performance metrics
        """
        win_rate = (self.winning_trades / self.total_trades * 100) if self.total_trades > 0 else 0
        avg_win = sum(t.pnl for t in self.closed_positions if t.pnl > 0) / max(self.winning_trades, 1)
        avg_loss = sum(t.pnl for t in self.closed_positions if t.pnl < 0) / max(self.losing_trades, 1)
        
        # Profit factor
        total_wins = sum(t.pnl for t in self.closed_positions if t.pnl > 0)
        total_losses = abs(sum(t.pnl for t in self.closed_positions if t.pnl < 0))
        profit_factor = total_wins / max(total_losses, 0.01)
        
        # Sharpe ratio (simplified)
        if len(self.equity_curve) > 1:
            equity_series = pd.Series([e['equity'] for e in self.equity_curve])
            returns = equity_series.pct_change().dropna()
            sharpe_ratio = (returns.mean() / returns.std()) * np.sqrt(252) if returns.std() > 0 else 0
        else:
            sharpe_ratio = 0
        
        # Expectancy per trade
        expectancy = (win_rate/100 * avg_win) + ((100-win_rate)/100 * avg_loss)
        
        results = {
            'initial_capital': self.initial_capital,
            'final_capital': self.capital,
            'total_pnl': self.total_pnl,
            'total_return_pct': (self.capital - self.initial_capital) / self.initial_capital * 100,
            'total_trades': self.total_trades,
            'winning_trades': self.winning_trades,
            'losing_trades': self.losing_trades,
            'win_rate': win_rate,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'profit_factor': profit_factor,
            'max_drawdown': self.max_drawdown,
            'max_drawdown_pct': (self.max_drawdown / self.max_equity * 100) if self.max_equity > 0 else 0,
            'sharpe_ratio': sharpe_ratio,
            'expectancy_per_trade': expectancy,
            'trades': [t.to_dict() for t in self.closed_positions]
        }
        
        return results
    
    def reset(self):
        """Reset backtest state for new run"""
        self.capital = self.initial_capital
        self.equity_curve = []
        self.open_positions = []
        self.closed_positions = []
        self.total_pnl = 0.0
        self.total_trades = 0
        self.winning_trades = 0
        self.losing_trades = 0
        self.max_equity = self.initial_capital
        self.max_drawdown = 0.0
        print("🔄 Backtest reset")


# Example usage
if __name__ == "__main__":
    print("="*70)
    print("Backtesting Skill - Example Usage")
    print("="*70)
    
    # Configuration
    config = {
        'backtesting': {
            'initial_capital': 10000,
            'position_size': 1.0,
            'spread_cost_usd': 0.50,
            'slippage_cost_usd': 0.05
        },
        'risk': {
            'stop_loss_pips': 20,
            'take_profit_pips': 40
        }
    }
    
    # Create skill
    backtest = BacktestingSkill(config)
    
    # Simulate some trades
    print("\n📊 Simulating trades...")
    
    # Trade 1: BUY that hits TP
    context = Context(timestamp=datetime(2024, 1, 1, 10, 0))
    context.signal = 'BUY'
    context.candle = {'close': 1900.0, 'high': 1950.0, 'low': 1890.0}
    backtest.execute(context)
    
    # Check exit on next candle (TP hit)
    context.timestamp = datetime(2024, 1, 1, 10, 5)
    context.candle = {'close': 1942.0, 'high': 1945.0, 'low': 1935.0}  # TP = 1940
    backtest.check_exits(context)
    
    # Trade 2: SELL that hits SL
    context.timestamp = datetime(2024, 1, 1, 11, 0)
    context.signal = 'SELL'
    context.candle = {'close': 1950.0, 'high': 1955.0, 'low': 1945.0}
    backtest.execute(context)
    
    # Check exit (SL hit)
    context.timestamp = datetime(2024, 1, 1, 11, 5)
    context.candle = {'close': 1975.0, 'high': 1980.0, 'low': 1970.0}  # SL = 1970
    backtest.check_exits(context)
    
    # Get results
    print("\n" + "="*70)
    print("BACKTEST RESULTS")
    print("="*70)
    results = backtest.get_results()
    print(f"Initial Capital: ${results['initial_capital']:,.2f}")
    print(f"Final Capital: ${results['final_capital']:,.2f}")
    print(f"Total P&L: ${results['total_pnl']:.2f}")
    print(f"Total Return: {results['total_return_pct']:.2f}%")
    print(f"Total Trades: {results['total_trades']}")
    print(f"Win Rate: {results['win_rate']:.1f}%")
    print(f"Profit Factor: {results['profit_factor']:.2f}")
    print(f"Sharpe Ratio: {results['sharpe_ratio']:.2f}")
    print(f"Max Drawdown: ${results['max_drawdown']:.2f} ({results['max_drawdown_pct']:.1f}%)")
    print(f"Expectancy per Trade: ${results['expectancy_per_trade']:.2f}")
    print("="*70)

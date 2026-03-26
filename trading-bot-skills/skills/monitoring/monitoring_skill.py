"""
Monitoring Skill
Tracks bot health, P&L, and performance metrics.
"""
from typing import Dict, Optional
from datetime import datetime
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from skills.base_skill import Skill, Context, SkillExecutionError


class MonitoringSkill(Skill):
    """
    Monitoring skill that tracks performance metrics.
    
    Responsibilities:
    - Track P&L (real-time, daily, total)
    - Calculate win rate, profit factor
    - Monitor drawdown
    - Heartbeat / health checks
    """
    
    def __init__(self, config: Dict):
        super().__init__(config)
        
        self.track_pnl = config.get('track_pnl', True)
        self.update_interval = config.get('update_interval_seconds', 60)
        
        # Metrics
        self.total_pnl = 0.0
        self.daily_pnl = 0.0
        self.total_trades = 0
        self.winning_trades = 0
        self.losing_trades = 0
        self.max_drawdown = 0.0
        self.peak_equity = 10000.0  # Starting capital
        
        # Last heartbeat
        self.last_heartbeat = datetime.now()
        
        print(f"📊 Monitoring Skill initialized: track_pnl={self.track_pnl}")
    
    async def execute(self, context: Context) -> Context:
        """
        Update metrics based on context
        
        Args:
            context: Context with position/pnl data
            
        Returns:
            Updated context with metrics
        """
        # Update P&L if position exists
        if context.current_position and context.current_candle:
            current_price = context.current_candle['close']
            pnl = self._calculate_pnl(context.current_position, current_price)
            context.pnl = pnl
            
            # Track peak and drawdown
            current_equity = self.peak_equity + pnl
            if current_equity > self.peak_equity:
                self.peak_equity = current_equity
            
            drawdown = (self.peak_equity - current_equity) / self.peak_equity * 100
            if drawdown > self.max_drawdown:
                self.max_drawdown = drawdown
        
        # Update win rate
        if self.total_trades > 0:
            context.win_rate = (self.winning_trades / self.total_trades) * 100
        
        # Heartbeat
        if (datetime.now() - self.last_heartbeat).total_seconds() > 30:
            print(f"💓 Heartbeat: {self.total_trades} trades, P&L: ${self.total_pnl:.2f}, DD: {self.max_drawdown:.1f}%")
            self.last_heartbeat = datetime.now()
        
        return context
    
    def _calculate_pnl(self, position: Dict, current_price: float) -> float:
        """
        Calculate P&L for open position
        
        Args:
            position: Position dict
            current_price: Current market price
            
        Returns:
            P&L in dollars
        """
        entry_price = position.get('entry_price', 0)
        size = position.get('size', 0)
        direction = position.get('direction', 'BUY')
        
        if direction == 'BUY':
            pnl = (current_price - entry_price) * size
        else:  # SELL
            pnl = (entry_price - current_price) * size
        
        return pnl
    
    def on_position_closed(self, pnl: float):
        """
        Update metrics when position closes
        
        Args:
            pnl: Realized P&L
        """
        self.total_trades += 1
        self.total_pnl += pnl
        self.daily_pnl += pnl
        
        if pnl > 0:
            self.winning_trades += 1
        else:
            self.losing_trades += 1
        
        print(f"📈 Trade closed: P&L=${pnl:.2f}, Total=${self.total_pnl:.2f}, Win Rate={self.winning_trades}/{self.total_trades}")
    
    def get_metrics(self) -> Dict:
        """Get current metrics"""
        return {
            'total_pnl': self.total_pnl,
            'daily_pnl': self.daily_pnl,
            'total_trades': self.total_trades,
            'winning_trades': self.winning_trades,
            'losing_trades': self.losing_trades,
            'win_rate': (self.winning_trades / self.total_trades * 100) if self.total_trades > 0 else 0,
            'max_drawdown': self.max_drawdown
        }
    
    def validate_config(self) -> bool:
        """Validate monitoring configuration"""
        return True


# Example usage
if __name__ == "__main__":
    import asyncio
    
    config = {
        'track_pnl': True,
        'update_interval_seconds': 60
    }
    
    skill = MonitoringSkill(config)
    
    async def test():
        # Mock open position
        context = Context(
            current_position={
                'deal_id': 'DEAL123',
                'direction': 'BUY',
                'size': 0.5,
                'entry_price': 2650.0
            },
            current_candle={'close': 2660.0}  # +10 pips profit
        )
        
        context = await skill.execute(context)
        print(f"P&L: ${context.pnl:.2f}")
        
        # Close position
        skill.on_position_closed(pnl=5.0)
        
        print(f"\nMetrics: {skill.get_metrics()}")
    
    asyncio.run(test())

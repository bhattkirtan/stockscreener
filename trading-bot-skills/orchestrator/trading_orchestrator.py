"""
Trading Orchestrator
Central controller that coordinates all skills.
"""
import asyncio
from typing import Dict, List
from datetime import datetime
import sys
import os

# Add skills directory to path
sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from skills.base_skill import Skill, Context


class TradingOrchestrator:
    """
    Orchestrator coordinates skill execution and manages bot lifecycle.
    
    Responsibilities:
    - Initialize all skills with configuration
    - Route data between skills
    - Handle event loop (WebSocket ticks, timers)
    - Error handling and recovery
    - Logging and monitoring
    """
    
    def __init__(self, config: Dict):
        """
        Initialize orchestrator with configuration.
        
        Args:
            config: Full bot configuration with skill settings
        """
        self.config = config
        self.skills: Dict[str, Skill] = {}
        self.running = False
        
        # Initialize metrics
        self.total_signals = 0
        self.total_trades = 0
        self.start_time = None
        
    def register_skill(self, name: str, skill: Skill):
        """
        Register a skill with the orchestrator.
        
        Args:
            name: Skill name (e.g., 'market_data', 'analysis')
            skill: Skill instance
        """
        if not skill.validate_config():
            raise ValueError(f"Invalid configuration for skill: {name}")
        
        self.skills[name] = skill
        print(f"✅ Registered skill: {name}")
    
    def get_skill(self, name: str) -> Skill:
        """Get skill by name"""
        return self.skills.get(name)
    
    async def start(self):
        """Start the orchestrator and all skills"""
        self.running = True
        self.start_time = datetime.now()
        print(f"🚀 Orchestrator started at {self.start_time}")
        print(f"📋 Registered skills: {list(self.skills.keys())}")
        
        # TODO: Start WebSocket connection
        # TODO: Start event loop
        
    async def stop(self):
        """Stop the orchestrator and cleanup"""
        self.running = False
        print("🛑 Orchestrator stopped")
        
        # Print stats
        runtime = (datetime.now() - self.start_time).total_seconds() / 60
        print(f"\n📊 Session Stats:")
        print(f"  Runtime: {runtime:.1f} minutes")
        print(f"  Total signals: {self.total_signals}")
        print(f"  Total trades: {self.total_trades}")
    
    async def on_candle(self, candle: Dict):
        """
        Handle new candle event.
        
        This is the main trading loop:
        1. Market Data → Update context with new candle
        2. Analysis → Generate signal from indicators
        3. Risk → Validate signal
        4. Execution → Place order if allowed
        5. Storage → Save position to Firestore
        6. Monitoring → Update P&L metrics
        7. Alerting → Send notifications
        
        Args:
            candle: OHLC candle dict with {open, high, low, close, timestamp}
        """
        # Create new context for this candle
        context = Context(
            current_candle=candle,
            timestamp=datetime.now()
        )
        
        try:
            # Execute skills in sequence
            
            # 1. Market Data Skill (update candle buffer)
            if 'market_data' in self.skills:
                context = await self.skills['market_data'].execute(context)
            
            # 2. Analysis Skill (calculate indicators, generate signal)
            if 'analysis' in self.skills:
                context = await self.skills['analysis'].execute(context)
                if context.signal:
                    self.total_signals += 1
                    print(f"📊 Signal: {context.signal} at {candle['close']}")
            
            # 3. Risk Skill (validate signal, check cooldown)
            if 'risk' in self.skills and context.signal:
                context = await self.skills['risk'].execute(context)
                if not context.is_allowed:
                    print(f"⚠️ Signal blocked: {context.risk_reason}")
                    return  # Stop here, signal not allowed
            
            # 4. Execution Skill (place order)
            if 'execution' in self.skills and context.is_allowed:
                context = await self.skills['execution'].execute(context)
                if context.deal_id:
                    self.total_trades += 1
                    print(f"✅ Trade opened: {context.signal} @ {candle['close']}, deal={context.deal_id}")
            
            # 5. Storage Skill (save to Firestore)
            if 'storage' in self.skills and context.deal_id:
                context = await self.skills['storage'].execute(context)
            
            # 6. Monitoring Skill (update metrics)
            if 'monitoring' in self.skills:
                context = await self.skills['monitoring'].execute(context)
            
            # 7. Alerting Skill (send notifications)
            if 'alerting' in self.skills and context.deal_id:
                context = await self.skills['alerting'].execute(context)
        
        except Exception as e:
            print(f"❌ Error in orchestrator: {e}")
            context.errors.append({
                'location': 'orchestrator.on_candle',
                'error': str(e),
                'timestamp': datetime.now()
            })
    
    async def on_position_closed(
        self, 
        deal_id: str, 
        direction: str, 
        close_reason: str,
        pnl: float,
        entry_price: float = 0.0,
        close_price: float = 0.0
    ):
        """
        Handle position closed event.
        
        Args:
            deal_id: Position deal ID
            direction: 'BUY' or 'SELL'
            close_reason: 'SL_HIT', 'TP_HIT', or 'SIGNAL'
            pnl: Profit/loss for the trade
            entry_price: Entry price
            close_price: Close price
        """
        print(f"🔴 Position closed: {deal_id}, {close_reason}, P&L: ${pnl:.2f}")
        
        # Update risk skill with closed position (for cooldown)
        if 'risk' in self.skills:
            risk_skill = self.skills['risk']
            risk_skill.on_position_closed(
                direction=direction,
                close_reason=close_reason,
                entry_price=entry_price,
                close_price=close_price
            )
        
        # Update storage (close position in Firestore) - ALWAYS in finally block
        if 'storage' in self.skills:
            try:
                storage_skill = self.skills['storage']
                await storage_skill.close_position(deal_id, close_price, close_reason)
            except Exception as e:
                print(f"⚠️ Storage close failed: {e}")
        
        # Update monitoring (track P&L)
        if 'monitoring' in self.skills:
            monitoring_skill = self.skills['monitoring']
            monitoring_skill.on_position_closed(pnl)
        
        # Send alert
        if 'alerting' in self.skills:
            alerting_skill = self.skills['alerting']
            await alerting_skill.send_trade_closed_alert(
                direction=direction,
                entry_price=entry_price,
                close_price=close_price,
                close_reason=close_reason,
                pnl=pnl
            )


# Example usage
if __name__ == "__main__":
    from skills.risk.risk_skill import RiskSkill
    
    async def main():
        # Configuration
        config = {
            'risk': {
                'sl_cooldown_minutes': 15,
                'tp_cooldown_minutes': 5,
                'position_size_pct': 2.0,
                'max_drawdown_pct': 20.0,
                'max_positions': 1
            }
        }
        
        # Create orchestrator
        orchestrator = TradingOrchestrator(config)
        
        # Register skills (for demo, only risk skill)
        risk_skill = RiskSkill(config['risk'])
        orchestrator.register_skill('risk', risk_skill)
        
        # Start orchestrator
        await orchestrator.start()
        
        # Simulate candle with BUY signal
        print("\n--- Candle 1: BUY Signal ---")
        candle1 = {
            'open': 2650.0,
            'high': 2652.0,
            'low': 2649.0,
            'close': 2651.0,
            'timestamp': datetime.now()
        }
        
        # Mock context with signal
        context = Context(signal='BUY', timestamp=datetime.now())
        context = await risk_skill.execute(context)
        print(f"Signal allowed: {context.is_allowed}, Reason: {context.risk_reason}")
        
        # Simulate position close with SL
        print("\n--- Position Closed: SL_HIT ---")
        await orchestrator.on_position_closed(
            deal_id='DEAL123',
            direction='BUY',
            close_reason='SL_HIT',
            pnl=-20.0
        )
        
        # Try same signal immediately (should be blocked)
        print("\n--- Candle 2: BUY Signal (immediate) ---")
        context = Context(signal='BUY', timestamp=datetime.now())
        context = await risk_skill.execute(context)
        print(f"Signal allowed: {context.is_allowed}, Reason: {context.risk_reason}")
        
        # Try opposite signal (should be allowed)
        print("\n--- Candle 3: SELL Signal (opposite) ---")
        context = Context(signal='SELL', timestamp=datetime.now())
        context = await risk_skill.execute(context)
        print(f"Signal allowed: {context.is_allowed}, Reason: {context.risk_reason}")
        
        # Stop orchestrator
        await orchestrator.stop()
    
    # Run example
    asyncio.run(main())

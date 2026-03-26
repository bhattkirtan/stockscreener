"""
Integration Test - Full Trading Flow

Tests the complete trading flow through all skills:
Market Data → Analysis → Risk → Execution → Storage → Monitoring → Alerting
"""

import unittest
import asyncio
import sys
import os
from pathlib import Path
from datetime import datetime, timedelta

# Add parent directories to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from skills.base_skill import Context
from skills.market_data import MarketDataSkill
from skills.analysis import AnalysisSkill
from skills.risk import RiskSkill
from skills.execution import ExecutionSkill
from skills.storage import StorageSkill
from skills.monitoring import MonitoringSkill
from skills.alerting import AlertingSkill


class TestFullTradingFlow(unittest.TestCase):
    """Tests full trading flow through all skills"""
    
    def setUp(self):
        """Setup test configuration"""
        self.config = {
            'trading': {
                'symbol': 'GOLD',
                'timeframe': 'M5',
                'mode': 'AUTO'
            },
            'market_data': {
                'buffer_size': 100,
                'timeframe': 'M5'
            },
            'indicators': {
                'supertrend': {'period': 10, 'multiplier': 2.0},
                'sma_fast': {'period': 25},
                'sma_slow': {'period': 30},
                'ema': {'period': 20},
                'bollinger': {'period': 20, 'std': 2.0}
            },
            'risk': {
                'sl_cooldown_minutes': 15,
                'tp_cooldown_minutes': 5,
                'enabled': True,
                'stop_loss_pips': 20,
                'take_profit_pips': 40
            },
            'execution': {
                'enabled': True,
                'position_size': 0.1
            },
            'storage': {
                'enabled': True,
                'firestore_project': 'test-project'
            },
            'monitoring': {
                'enabled': True,
                'heartbeat_seconds': 30
            },
            'alerting': {
                'enabled': True,
                'telegram_token': 'test_token',
                'telegram_chat_id': 'test_chat'
            }
        }
        
        # Initialize all skills
        self.market_data = MarketDataSkill(self.config)
        self.analysis = AnalysisSkill(self.config)
        self.risk = RiskSkill(self.config)
        self.execution = ExecutionSkill(self.config)
        self.storage = StorageSkill(self.config)
        self.monitoring = MonitoringSkill(self.config)
        self.alerting = AlertingSkill(self.config)
    
    def test_full_flow_buy_signal(self):
        """Test complete flow with BUY signal"""
        
        # Create initial context with empty position
        context = Context(
            timestamp=datetime.now(),
            current_position=None
        )
        
        # 1. Market Data: Add candles to build history
        for i in range(50):
            candle = {
                'timestamp': datetime.now() - timedelta(minutes=50-i),
                'open': 1900.0 + i * 0.5,
                'high': 1901.0 + i * 0.5,
                'low': 1899.0 + i * 0.5,
                'close': 1900.5 + i * 0.5,
                'volume': 100
            }
            context.candle = candle
            self.market_data.execute(context)
        
        # Should have 50 candles in history
        self.assertEqual(len(context.candle_history), 50)
        
        # 2. Analysis: Calculate indicators and generate signal
        self.analysis.execute(context)
        
        # Should have some signal (BUY, SELL, or HOLD)
        self.assertIsNotNone(context.signal)
        self.assertIn(context.signal, ['BUY', 'SELL', 'HOLD'])
        print(f"✅ Signal generated: {context.signal}")
        
        # 3. Risk: Validate signal (assuming BUY signal)
        if context.signal == 'BUY':
            is_valid = self.risk.execute(context)
            # First signal should be valid (no cooldown)
            self.assertTrue(is_valid)
            print(f"✅ Risk validation: PASSED")
            
            # 4. Execution: Place order (mocked)
            result = asyncio.run(self.execution.execute(context))
            
            # Verify position was created
            self.assertIsNotNone(context.current_position)
            self.assertEqual(context.current_position['direction'], 'BUY')
            print(f"✅ Position opened: {context.current_position['deal_id']}")
            
            # 5. Storage: Save position (mocked)
            asyncio.run(self.storage.execute(context))
            print(f"✅ Position saved to storage")
            
            # 6. Monitoring: Track position
            self.monitoring.execute(context)
            print(f"✅ Monitoring active")
            
            # 7. Alerting: Send notification (mocked)
            asyncio.run(self.alerting.execute(context))
            print(f"✅ Alert sent")
    
    def test_cooldown_enforcement(self):
        """Test that cooldown prevents duplicate trades"""
        
        context = Context(
            timestamp=datetime.now(),
            current_position=None
        )
        
        # Add candles
        for i in range(50):
            candle = {
                'timestamp': datetime.now() - timedelta(minutes=50-i),
                'open': 1900.0,
                'high': 1901.0,
                'low': 1899.0,
                'close': 1900.5,
                'volume': 100
            }
            context.candle = candle
            self.market_data.execute(context)
        
        # Generate signal
        self.analysis.execute(context)
        
        if context.signal in ['BUY', 'SELL']:
            # First signal should pass
            is_valid_1 = self.risk.execute(context)
            self.assertTrue(is_valid_1)
            
            # Simulate SL hit
            self.risk.on_position_closed(
                direction=context.signal,
                close_reason='SL_HIT',
                entry_price=1900.0,
                close_price=1880.0
            )
            
            # Same signal immediately after SL should be blocked
            context.timestamp = datetime.now()
            is_valid_2 = self.risk.execute(context)
            self.assertFalse(is_valid_2)
            print(f"✅ Cooldown enforced: duplicate {context.signal} blocked after SL")
            
            # Signal after cooldown should pass
            context.timestamp = datetime.now() + timedelta(minutes=20)
            is_valid_3 = self.risk.execute(context)
            self.assertTrue(is_valid_3)
            print(f"✅ Cooldown expired: {context.signal} allowed after 20min")
    
    def test_position_close_flow(self):
        """Test complete position close flow"""
        
        # Simulate closed position
        pnl = 50.0
        
        # Monitoring should track P&L
        self.monitoring.on_position_closed(pnl)
        
        # Should have 1 winning trade
        self.assertEqual(self.monitoring.metrics['total_trades'], 1)
        self.assertEqual(self.monitoring.metrics['winning_trades'], 1)
        self.assertEqual(self.monitoring.metrics['total_pnl'], pnl)
        
        print(f"✅ Position closed: P&L=${pnl}, Win Rate={self.monitoring.metrics['win_rate']:.1f}%")
    
    def test_signal_edge_detection(self):
        """Test that Analysis skill only triggers on signal changes"""
        
        context = Context(timestamp=datetime.now())
        
        # Add candles to build history
        for i in range(50):
            candle = {
                'timestamp': datetime.now() - timedelta(minutes=50-i),
                'open': 1900.0,
                'high': 1901.0,
                'low': 1899.0,
                'close': 1900.5,
                'volume': 100
            }
            context.candle = candle
            self.market_data.execute(context)
        
        # First analysis - should generate signal
        self.analysis.execute(context)
        first_signal = context.signal
        
        # Second analysis with same conditions - should be HOLD (no edge)
        self.analysis.execute(context)
        second_signal = context.signal
        
        # If first signal was not HOLD, second should be HOLD (edge detection)
        if first_signal != 'HOLD':
            self.assertEqual(second_signal, 'HOLD')
            print(f"✅ Edge detection: {first_signal} → {second_signal} (no duplicate)")


def run_integration_tests():
    """Run all integration tests"""
    suite = unittest.TestLoader().loadTestsFromTestCase(TestFullTradingFlow)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    print("\n" + "="*70)
    print("INTEGRATION TEST SUMMARY")
    print("="*70)
    print(f"Tests run: {result.testsRun}")
    print(f"Successes: {result.testsRun - len(result.failures) - len(result.errors)}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    print("="*70)
    
    return result.wasSuccessful()


if __name__ == '__main__':
    success = run_integration_tests()
    sys.exit(0 if success else 1)

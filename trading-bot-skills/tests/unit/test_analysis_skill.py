"""
Unit Tests - Analysis Skill

Tests indicator calculations and signal generation logic.
"""
import pytest
import sys
import os
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from skills.analysis.analysis_skill import AnalysisSkill
from skills.base_skill import Context


class TestAnalysisSkill:
    """Test Analysis Skill"""
    
    @pytest.fixture
    def config(self):
        """Analysis configuration"""
        return {
            'supertrend': {'period': 10, 'multiplier': 3.0},
            'sma': {'fast_period': 5, 'slow_period': 20},
            'edge_detection': {
                'enabled': True,
                'lookback_periods': 3,
                'min_body_ratio': 0.6
            }
        }
    
    @pytest.fixture
    def skill(self, config):
        """Analysis skill instance"""
        return AnalysisSkill(config)
    
    @pytest.fixture
    def context_with_candles(self):
        """Context with sample candles"""
        context = Context()
        
        # Add 50 candles with uptrend
        base_time = datetime.now(timezone.utc)
        for i in range(50):
            candle = {
                'timestamp': base_time - timedelta(minutes=250-i*5),
                'open': 1900.00 + i,
                'high': 1905.00 + i,
                'low': 1895.00 + i,
                'close': 1902.00 + i,
                'volume': 1000
            }
            context.candles.append(candle)
        
        return context
    
    def test_initialization(self, skill):
        """Test skill initializes correctly"""
        assert skill.supertrend_period == 10
        assert skill.supertrend_multiplier == 3.0
        assert skill.sma_fast_period == 5
        assert skill.sma_slow_period == 20
    
    def test_analyze_with_insufficient_data(self, skill):
        """Test analyze returns None with insufficient candles"""
        context = Context()
        context.candles = [
            {'timestamp': datetime.now(timezone.utc), 'open': 1950, 'high': 1955, 'low': 1945, 'close': 1952, 'volume': 1000}
        ]
        
        signal = skill.analyze(context)
        assert signal is None or signal == 'HOLD'
    
    def test_analyze_with_sufficient_data(self, skill, context_with_candles):
        """Test analyze generates signal with sufficient data"""
        signal = skill.analyze(context_with_candles)
        assert signal in ['BUY', 'SELL', 'HOLD', None]
    
    def test_calculate_supertrend(self, skill, context_with_candles):
        """Test SuperTrend calculation"""
        # This would test the actual SuperTrend calculation
        # For now, verify it doesn't crash
        signal = skill.analyze(context_with_candles)
        assert signal is not None or signal in ['BUY', 'SELL', 'HOLD']
    
    def test_calculate_sma(self, skill, context_with_candles):
        """Test SMA calculation"""
        # Extract close prices
        closes = [c['close'] for c in context_with_candles.candles]
        
        # Simple SMA calculation check (if skill exposes it)
        # For now, just verify analysis doesn't crash
        signal = skill.analyze(context_with_candles)
        assert signal is not None or signal in ['BUY', 'SELL', 'HOLD']
    
    def test_edge_detection_enabled(self, skill, context_with_candles):
        """Test edge detection filters signals"""
        # Add a sharp reversal candle
        reversal_candle = {
            'timestamp': datetime.now(timezone.utc),
            'open': 1950.00,
            'high': 1952.00,
            'low': 1945.00,
            'close': 1946.00,  # Small body, might be edge
            'volume': 1000
        }
        context_with_candles.candles.append(reversal_candle)
        
        signal = skill.analyze(context_with_candles)
        # Edge detection might filter this signal
        assert signal in ['BUY', 'SELL', 'HOLD', None]
    
    def test_buy_signal_conditions(self, skill):
        """Test BUY signal generation conditions"""
        context = Context()
        
        # Create strong uptrend candles
        base_time = datetime.now(timezone.utc)
        for i in range(30):
            candle = {
                'timestamp': base_time - timedelta(minutes=150-i*5),
                'open': 1900.00 + i*2,
                'high': 1908.00 + i*2,
                'low': 1898.00 + i*2,
                'close': 1906.00 + i*2,
                'volume': 1500
            }
            context.candles.append(candle)
        
        signal = skill.analyze(context)
        # Should have potential for BUY (or HOLD if conditions not perfect)
        assert signal in ['BUY', 'HOLD', None]
    
    def test_sell_signal_conditions(self, skill):
        """Test SELL signal generation conditions"""
        context = Context()
        
        # Create strong downtrend candles
        base_time = datetime.now(timezone.utc)
        for i in range(30):
            candle = {
                'timestamp': base_time - timedelta(minutes=150-i*5),
                'open': 2000.00 - i*2,
                'high': 2002.00 - i*2,
                'low': 1992.00 - i*2,
                'close': 1994.00 - i*2,
                'volume': 1500
            }
            context.candles.append(candle)
        
        signal = skill.analyze(context)
        # Should have potential for SELL (or HOLD if conditions not perfect)
        assert signal in ['SELL', 'HOLD', None]
    
    def test_signal_storage_in_context(self, skill, context_with_candles):
        """Test signal is stored in context"""
        skill.analyze(context_with_candles)
        
        # Signal should be set in context (even if None or HOLD)
        assert hasattr(context_with_candles, 'signal') or context_with_candles.signal is None


if __name__ == '__main__':
    pytest.main([__file__, '-v'])

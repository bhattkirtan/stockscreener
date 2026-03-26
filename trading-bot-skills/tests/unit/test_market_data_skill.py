"""
Unit Tests - Market Data Skill

Tests candle reception, deduplication, aggregation, and buffer management.
"""
import pytest
import sys
import os
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from skills.market_data.market_data_skill import MarketDataSkill
from skills.base_skill import Context


class TestMarketDataSkill:
    """Test Market Data Skill"""
    
    @pytest.fixture
    def config(self):
        """Market data configuration"""
        return {
            'symbol': 'GOLD',
            'timeframe': '5min',
            'buffer_size': 100,
            'dedup_enabled': True
        }
    
    @pytest.fixture
    def skill(self, config):
        """Market data skill instance"""
        return MarketDataSkill(config)
    
    @pytest.fixture
    def context(self):
        """Fresh trading context"""
        return Context()
    
    def test_initialization(self, skill):
        """Test skill initializes correctly"""
        assert skill.symbol == 'GOLD'
        assert skill.timeframe == '5min'
        assert skill.buffer_size == 100
        assert skill.dedup_enabled == True
    
    def test_single_candle_processing(self, skill, context):
        """Test processing a single candle"""
        candle = {
            'timestamp': datetime.now(timezone.utc),
            'open': 1950.00,
            'high': 1955.00,
            'low': 1945.00,
            'close': 1952.00,
            'volume': 1000
        }
        
        skill.process_candle(context, candle)
        
        assert len(context.candles) == 1
        assert context.candles[0]['close'] == 1952.00
    
    def test_multiple_candles_processing(self, skill, context):
        """Test processing multiple candles"""
        candles = [
            {'timestamp': datetime.now(timezone.utc) - timedelta(minutes=10), 'open': 1940, 'high': 1945, 'low': 1935, 'close': 1942, 'volume': 1000},
            {'timestamp': datetime.now(timezone.utc) - timedelta(minutes=5), 'open': 1942, 'high': 1950, 'low': 1940, 'close': 1948, 'volume': 1100},
            {'timestamp': datetime.now(timezone.utc), 'open': 1948, 'high': 1955, 'low': 1945, 'close': 1952, 'volume': 1200}
        ]
        
        for candle in candles:
            skill.process_candle(context, candle)
        
        assert len(context.candles) == 3
        assert context.candles[-1]['close'] == 1952.00
    
    def test_candle_deduplication(self, skill, context):
        """Test that duplicate candles are filtered"""
        candle = {
            'timestamp': datetime.now(timezone.utc),
            'open': 1950.00,
            'high': 1955.00,
            'low': 1945.00,
            'close': 1952.00,
            'volume': 1000
        }
        
        # Process same candle twice
        skill.process_candle(context, candle)
        skill.process_candle(context, candle)
        
        assert len(context.candles) == 1  # Should only add once
    
    def test_buffer_size_enforcement(self, skill, context):
        """Test buffer maintains max size"""
        # Process more candles than buffer size
        for i in range(150):
            candle = {
                'timestamp': datetime.now(timezone.utc) - timedelta(minutes=750-i*5),
                'open': 1950.00 + i,
                'high': 1955.00 + i,
                'low': 1945.00 + i,
                'close': 1952.00 + i,
                'volume': 1000
            }
            skill.process_candle(context, candle)
        
        assert len(context.candles) <= skill.buffer_size
    
    def test_candle_ordering(self, skill, context):
        """Test candles are ordered by timestamp"""
        candles = [
            {'timestamp': datetime.now(timezone.utc), 'open': 1950, 'high': 1955, 'low': 1945, 'close': 1952, 'volume': 1000},
            {'timestamp': datetime.now(timezone.utc) - timedelta(minutes=10), 'open': 1940, 'high': 1945, 'low': 1935, 'close': 1942, 'volume': 1000},
            {'timestamp': datetime.now(timezone.utc) - timedelta(minutes=5), 'open': 1942, 'high': 1950, 'low': 1940, 'close': 1948, 'volume': 1100}
        ]
        
        for candle in candles:
            skill.process_candle(context, candle)
        
        # Verify ordering (oldest first)
        for i in range(len(context.candles) - 1):
            assert context.candles[i]['timestamp'] <= context.candles[i+1]['timestamp']
    
    def test_invalid_candle_rejection(self, skill, context):
        """Test invalid candles are rejected"""
        invalid_candles = [
            {'open': 1950, 'high': 1955, 'low': 1945, 'close': 1952},  # Missing timestamp
            {'timestamp': datetime.now(timezone.utc), 'high': 1955, 'low': 1945, 'close': 1952},  # Missing open
            {'timestamp': datetime.now(timezone.utc), 'open': 1950, 'high': 1955, 'close': 1952},  # Missing low
        ]
        
        for candle in invalid_candles:
            skill.process_candle(context, candle)
        
        assert len(context.candles) == 0  # No invalid candles added
    
    def test_get_latest_candle(self, skill, context):
        """Test retrieving latest candle"""
        candles = [
            {'timestamp': datetime.now(timezone.utc) - timedelta(minutes=10), 'open': 1940, 'high': 1945, 'low': 1935, 'close': 1942, 'volume': 1000},
            {'timestamp': datetime.now(timezone.utc) - timedelta(minutes=5), 'open': 1942, 'high': 1950, 'low': 1940, 'close': 1948, 'volume': 1100},
            {'timestamp': datetime.now(timezone.utc), 'open': 1948, 'high': 1955, 'low': 1945, 'close': 1952, 'volume': 1200}
        ]
        
        for candle in candles:
            skill.process_candle(context, candle)
        
        latest = context.candles[-1]
        assert latest['close'] == 1952.00
    
    def test_candle_aggregation_by_timeframe(self, skill, context):
        """Test candles are aggregated correctly by timeframe"""
        # Add multiple 1-min candles to be aggregated into 5-min
        base_time = datetime.now(timezone.utc)
        for i in range(5):
            candle = {
                'timestamp': base_time + timedelta(minutes=i),
                'open': 1950.00 + i,
                'high': 1955.00 + i,
                'low': 1945.00 + i,
                'close': 1952.00 + i,
                'volume': 200
            }
            skill.process_candle(context, candle)
        
        # Verify candles are stored
        assert len(context.candles) > 0


if __name__ == '__main__':
    pytest.main([__file__, '-v'])

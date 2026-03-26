"""
Unit Tests - Market Data Skill

Tests candle reception, deduplication, aggregation, and buffer management.
"""
import pytest
import sys
import os
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from skills.market_data.market_data_skill import MarketDataSkill


class TestMarketDataSkill:
    """Test Market Data Skill"""
    
    @pytest.fixture
    def config(self):
        """Market data configuration"""
        return {
            'instrument': 'GOLD',
            'timeframe': 'M5',
            'buffer_size': 100,
            'dedup_enabled': True
        }
    
    @pytest.fixture
    def mock_event_bus(self):
        """Mock event bus"""
        bus = AsyncMock()
        bus.publish = AsyncMock()
        return bus
    
    @pytest.fixture
    def skill(self, config, mock_event_bus):
        """Market data skill instance"""
        return MarketDataSkill(config, event_bus=mock_event_bus)
    
    def test_initialization(self, skill):
        """Test skill initializes correctly"""
        assert skill.symbol == 'GOLD'
        assert skill.timeframe == 'M5'
        assert skill.buffer_size == 100
        assert skill.dedup_enabled == True
    
    @pytest.mark.asyncio
    async def test_single_candle_processing(self, skill):
        """Test processing a single candle"""
        candle = {
            'timestamp': datetime.now(timezone.utc),
            'open': 1950.00,
            'high': 1955.00,
            'low': 1945.00,
            'close': 1952.00,
            'volume': 1000
        }
        
        await skill.process_candle(candle)
        
        assert len(skill.m5_history) == 1
        assert skill.m5_history[0]['close'] == 1952.00
    
    @pytest.mark.asyncio
    async def test_multiple_candles_processing(self, skill):
        """Test processing multiple candles"""
        candles = [
            {'timestamp': datetime.now(timezone.utc) - timedelta(minutes=10), 'open': 1940, 'high': 1945, 'low': 1935, 'close': 1942, 'volume': 1000},
            {'timestamp': datetime.now(timezone.utc) - timedelta(minutes=5), 'open': 1942, 'high': 1950, 'low': 1940, 'close': 1948, 'volume': 1100},
            {'timestamp': datetime.now(timezone.utc), 'open': 1948, 'high': 1955, 'low': 1945, 'close': 1952, 'volume': 1200}
        ]
        
        for candle in candles:
            await skill.process_candle(candle)
        
        assert len(skill.m5_history) == 3
        assert skill.m5_history[-1]['close'] == 1952.00
    
    @pytest.mark.asyncio
    async def test_candle_deduplication(self, skill):
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
        await skill.process_candle(candle)
        await skill.process_candle(candle)
        
        assert len(skill.m5_history) == 1  # Should only add once
    
    @pytest.mark.asyncio
    async def test_buffer_size_enforcement(self, skill):
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
            await skill.process_candle(candle)
        
        assert len(skill.m5_history) <= skill.buffer_size
    
    @pytest.mark.asyncio
    async def test_candle_ordering(self, skill):
        """Test candles are ordered by timestamp"""
        candles = [
            {'timestamp': datetime.now(timezone.utc), 'open': 1950, 'high': 1955, 'low': 1945, 'close': 1952, 'volume': 1000},
            {'timestamp': datetime.now(timezone.utc) - timedelta(minutes=10), 'open': 1940, 'high': 1945, 'low': 1935, 'close': 1942, 'volume': 1000},
            {'timestamp': datetime.now(timezone.utc) - timedelta(minutes=5), 'open': 1942, 'high': 1950, 'low': 1940, 'close': 1948, 'volume': 1100}
        ]
        
        for candle in candles:
            await skill.process_candle(candle)
        
        # Verify ordering (oldest first)
        for i in range(len(skill.m5_history) - 1):
            assert skill.m5_history[i]['timestamp'] <= skill.m5_history[i+1]['timestamp']
    
    @pytest.mark.asyncio
    async def test_invalid_candle_rejection(self, skill):
        """Test invalid candles are rejected"""
        invalid_candles = [
            {'open': 1950, 'high': 1955, 'low': 1945, 'close': 1952},  # Missing timestamp
            {'timestamp': datetime.now(timezone.utc), 'high': 1955, 'low': 1945, 'close': 1952},  # Missing open
            {'timestamp': datetime.now(timezone.utc), 'open': 1950, 'high': 1955, 'close': 1952},  # Missing low
        ]
        
        for candle in invalid_candles:
            await skill.process_candle(candle)
        
        assert len(skill.m5_history) == 0  # No invalid candles added
    
    @pytest.mark.asyncio
    async def test_get_latest_candle(self, skill):
        """Test retrieving latest candle"""
        candles = [
            {'timestamp': datetime.now(timezone.utc) - timedelta(minutes=10), 'open': 1940, 'high': 1945, 'low': 1935, 'close': 1942, 'volume': 1000},
            {'timestamp': datetime.now(timezone.utc) - timedelta(minutes=5), 'open': 1942, 'high': 1950, 'low': 1940, 'close': 1948, 'volume': 1100},
            {'timestamp': datetime.now(timezone.utc), 'open': 1948, 'high': 1955, 'low': 1945, 'close': 1952, 'volume': 1200}
        ]
        
        for candle in candles:
            await skill.process_candle(candle)
        
        latest = skill.m5_history[-1]
        assert latest['close'] == 1952.00
    
    @pytest.mark.asyncio
    async def test_candle_aggregation_by_timeframe(self, config, mock_event_bus):
        """Test candles are aggregated correctly by timeframe"""
        # Create skill with M15 timeframe
        config['timeframe'] = 'M15'
        skill = MarketDataSkill(config, event_bus=mock_event_bus)
        
        # Add 3 M5 candles at M15-aligned times (last one at 10:15 triggers M15 bar)
        base_time = datetime(2024, 1, 1, 10, 5, tzinfo=timezone.utc)
        for i in range(3):
            candle = {
                'timestamp': base_time + timedelta(minutes=i*5),
                'open': 1950.00 + i,
                'high': 1955.00 + i,
                'low': 1945.00 + i,
                'close': 1952.00 + i,
                'volume': 200
            }
            await skill.process_candle(candle)
        
        # Verify M5 candles are stored
        assert len(skill.m5_history) == 3
        # Verify M15 bar was created (last candle at 10:15 aligns with M15 boundary)
        assert len(skill.m15_history) == 1


if __name__ == '__main__':
    pytest.main([__file__, '-v'])

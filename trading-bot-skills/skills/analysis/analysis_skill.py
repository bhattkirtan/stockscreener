"""
Analysis Skill
Calculates technical indicators and generates trading signals.

EVENT-DRIVEN:
- Subscribes to: CANDLE_CLOSED
- Publishes: SIGNAL_GENERATED (when new signal detected)
"""
from typing import Dict, Optional, TYPE_CHECKING
import pandas as pd
import numpy as np
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from skills.base_skill import Skill, SkillExecutionError

if TYPE_CHECKING:
    from core.event_bus import EventBus, Event


class AnalysisSkill(Skill):
    """
    Analysis skill that calculates indicators and generates signals.
    
    EVENT-DRIVEN HANDLERS:
    - on_candle_closed(event): Calculate indicators and generate signal
    
    Responsibilities:
    - Calculate Supertrend, SMA, EMA, Bollinger Bands
    - Detect crossovers
    - Generate BUY/SELL signals
    - Track signal state (edge detection)
    - Publish SIGNAL_GENERATED event when new signal detected
    """
    
    def __init__(self, config: Dict, event_bus: Optional['EventBus'] = None, market_data_skill=None):
        super().__init__(config, event_bus)
        self.market_data = market_data_skill
        
        # Supertrend settings
        self.st_period = config.get('supertrend', {}).get('atr_period', 10)
        self.st_multiplier = config.get('supertrend', {}).get('multiplier', 2.0)
        
        # SMA settings
        self.sma_fast = config.get('sma', {}).get('fast_period', 25)
        self.sma_slow = config.get('sma', {}).get('slow_period', 30)
        
        # Bollinger settings
        self.bb_period = config.get('bollinger', {}).get('period', 20)
        self.bb_std = config.get('bollinger', {}).get('std_dev', 2.0)
        
        # EMA settings
        self.ema_period = config.get('ema_period', 30)
        
        # Signal state tracking (for edge detection)
        self.last_signal_state = None
    
    async def on_candle_closed(self, event: 'Event') -> None:
        """
        Handle CANDLE_CLOSED event - calculate indicators and generate signal.
        
        Args:
            event: Event with candle data
        """
        # Get candle history from market data skill
        if not self.market_data:
            print("⚠️ Analysis: No market data skill connected")
            return
        
        candle_history = self.market_data.get_candle_history()
        if not candle_history or len(candle_history) < 50:
            return
        
        # Convert to DataFrame
        df = pd.DataFrame(candle_history)
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df.set_index('timestamp', inplace=True)
        
        # Extract indicators
        latest = df.iloc[-1]
        indicators = {
            'supertrend': float(latest['supertrend']),
            'supertrend_direction': int(latest['direction']),
            'sma_fast': float(latest['sma_fast']),
            'sma_slow': float(latest['sma_slow']),
            'ema': float(latest['ema']),
            'bb_upper': float(latest['bb_upper']),
            'bb_middle': float(latest['bb_middle']),
            'bb_lower': float(latest['bb_lower']),
            'current_price': float(latest['close'])
        }
        
        # Generate signal
        signal = self._generate_signal(df)
        
        # Edge detection: only trigger on signal change
        if signal and signal != self.last_signal_state:
            self.last_signal_state = signal
            print(f"🎯 New signal: {signal}")
            
            # Publish SIGNAL_GENERATED event
            if self.event_bus:
                from core.event_bus import create_signal_generated_event
                await self.event_bus.publish(
                    create_signal_generated_event(
                        instrument=event.instrument,
                        signal=signal,
                        indicators=indicators,
                        correlation_id=event.correlation_id
                    )
                )
    
    def _calculate_supertrend(self, df: pd.DataFrame) -> pd.DataFrame:
        """Calculate Supertrend indicator"""
        # Calculate ATR
        df['tr'] = pd.concat([
            df['high'] - df['low'],
            abs(df['high'] - df['close'].shift(1)),
            abs(df['low'] - df['close'].shift(1))
        ], axis=1).max(axis=1)
        df['atr'] = df['tr'].rolling(self.st_period).mean()
        
        # Basic bands
        hl_avg = (df['high'] + df['low']) / 2
        df['basic_upper'] = hl_avg + (self.st_multiplier * df['atr'])
        df['basic_lower'] = hl_avg - (self.st_multiplier * df['atr'])
        
        # Final bands
        df['final_upper'] = df['basic_upper']
        df['final_lower'] = df['basic_lower']
        
        for i in range(1, len(df)):
            if df['close'].iloc[i-1] <= df['final_upper'].iloc[i-1]:
                df.loc[df.index[i], 'final_upper'] = min(df['basic_upper'].iloc[i], df['final_upper'].iloc[i-1])
            else:
                df.loc[df.index[i], 'final_upper'] = df['basic_upper'].iloc[i]
                
            if df['close'].iloc[i-1] >= df['final_lower'].iloc[i-1]:
                df.loc[df.index[i], 'final_lower'] = max(df['basic_lower'].iloc[i], df['final_lower'].iloc[i-1])
            else:
                df.loc[df.index[i], 'final_lower'] = df['basic_lower'].iloc[i]
        
        # Supertrend
        df['supertrend'] = np.nan
        df['direction'] = 1  # 1 = uptrend, -1 = downtrend
        
        for i in range(1, len(df)):
            if df['close'].iloc[i] > df['final_upper'].iloc[i-1]:
                df.loc[df.index[i], 'direction'] = 1
            elif df['close'].iloc[i] < df['final_lower'].iloc[i-1]:
                df.loc[df.index[i], 'direction'] = -1
            else:
                df.loc[df.index[i], 'direction'] = df['direction'].iloc[i-1]
            
            if df['direction'].iloc[i] == 1:
                df.loc[df.index[i], 'supertrend'] = df['final_lower'].iloc[i]
            else:
                df.loc[df.index[i], 'supertrend'] = df['final_upper'].iloc[i]
        
        return df
    
    def _calculate_sma(self, df: pd.DataFrame) -> pd.DataFrame:
        """Calculate Simple Moving Averages"""
        df['sma_fast'] = df['close'].rolling(self.sma_fast).mean()
        df['sma_slow'] = df['close'].rolling(self.sma_slow).mean()
        return df
    
    def _calculate_ema(self, df: pd.DataFrame) -> pd.DataFrame:
        """Calculate Exponential Moving Average"""
        df['ema'] = df['close'].ewm(span=self.ema_period, adjust=False).mean()
        return df
    
    def _calculate_bollinger_bands(self, df: pd.DataFrame) -> pd.DataFrame:
        """Calculate Bollinger Bands"""
        df['bb_middle'] = df['close'].rolling(self.bb_period).mean()
        bb_std = df['close'].rolling(self.bb_period).std()
        df['bb_upper'] = df['bb_middle'] + (self.bb_std * bb_std)
        df['bb_lower'] = df['bb_middle'] - (self.bb_std * bb_std)
        return df
    
    def _generate_signal(self, df: pd.DataFrame) -> Optional[str]:
        """
        Generate trading signal from indicators
        
        Returns:
            'BUY', 'SELL', or None
        """
        if len(df) < 2:
            return None
        
        latest = df.iloc[-1]
        prev = df.iloc[-2]
        
        # Check for NaN
        if pd.isna(latest['supertrend']) or pd.isna(latest['sma_fast']):
            return None
        
        close = latest['close']
        supertrend_dir = latest['direction']
        sma_fast = latest['sma_fast']
        sma_slow = latest['sma_slow']
        ema = latest['ema']
        
        sma_fast_prev = prev['sma_fast']
        sma_slow_prev = prev['sma_slow']
        
        # Detect crossovers
        golden_cross = (sma_fast > sma_slow) and (sma_fast_prev <= sma_slow_prev)
        death_cross = (sma_fast < sma_slow) and (sma_fast_prev >= sma_slow_prev)
        
        # BUY Signal
        if (supertrend_dir == 1 and
            close > ema and
            (golden_cross or sma_fast > sma_slow)):
            return 'BUY'
        
        # SELL Signal
        elif (supertrend_dir == -1 and
              close < ema and
              (death_cross or sma_fast < sma_slow)):
            return 'SELL'
        
        return None
    
    def validate_config(self) -> bool:
        """Validate analysis configuration"""
        if self.st_period < 1 or self.st_multiplier <= 0:
            raise SkillExecutionError("Invalid Supertrend parameters")
        if self.sma_fast < 1 or self.sma_slow < 1:
            raise SkillExecutionError("Invalid SMA parameters")
        return True


# Example usage
if __name__ == "__main__":
    import asyncio
    
    config = {
        'supertrend': {
            'atr_period': 10,
            'multiplier': 2.0
        },
        'sma': {
            'fast_period': 25,
            'slow_period': 30
        },
        'bollinger': {
            'period': 20,
            'std_dev': 2.0
        },
        'ema_period': 30
    }
    
    skill = AnalysisSkill(config)
    
    async def test():
        # Create sample candle history
        candles = []
        base_price = 2650
        for i in range(100):
            candles.append({
                'timestamp': f'2024-01-15T{10+i//12:02d}:{(i%12)*5:02d}:00',
                'open': base_price + i * 0.1,
                'high': base_price + i * 0.1 + 2,
                'low': base_price + i * 0.1 - 2,
                'close': base_price + i * 0.1 + 1,
                'volume': 1000
            })
        
        context = Context(candle_history=candles)
        context = await skill.execute(context)
        
        print(f"\nSignal: {context.signal}")
        print(f"Indicators: {context.indicators}")
    
    asyncio.run(test())

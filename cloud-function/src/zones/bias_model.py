"""Directional bias model using EMA crossovers."""

from enum import Enum
from typing import Optional
import pandas as pd
import numpy as np


class BiasState(Enum):
    """Directional bias states (Section 11.2)."""
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


class BiasModel:
    """Directional bias calculation from H4 and H1 (Section 11)."""
    
    def __init__(self, fast_period: int = 20, slow_period: int = 50):
        """Initialize bias model.
        
        Args:
            fast_period: Fast EMA period (default 20)
            slow_period: Slow EMA period (default 50)
        """
        self.fast_period = fast_period
        self.slow_period = slow_period
    
    def calculate_bias(self, h4_df: pd.DataFrame, h1_df: pd.DataFrame) -> BiasState:
        """Calculate directional bias from H4 and H1 (Section 11.3).
        
        Rules from spec:
        - bullish if H1 fast > H1 slow AND H4 fast >= H4 slow
        - bearish if H1 fast < H1 slow AND H4 fast <= H4 slow
        - otherwise neutral
        
        Args:
            h4_df: H4 OHLC dataframe
            h1_df: H1 OHLC dataframe
            
        Returns:
            BiasState (BULLISH, BEARISH, or NEUTRAL)
        """
        if len(h4_df) < self.slow_period or len(h1_df) < self.slow_period:
            return BiasState.NEUTRAL
        
        # Calculate H4 EMAs
        h4_fast = self._calculate_ema(h4_df['close'], self.fast_period)
        h4_slow = self._calculate_ema(h4_df['close'], self.slow_period)
        
        # Calculate H1 EMAs
        h1_fast = self._calculate_ema(h1_df['close'], self.fast_period)
        h1_slow = self._calculate_ema(h1_df['close'], self.slow_period)
        
        # Current values
        h4_fast_now = h4_fast.iloc[-1]
        h4_slow_now = h4_slow.iloc[-1]
        h1_fast_now = h1_fast.iloc[-1]
        h1_slow_now = h1_slow.iloc[-1]
        
        # Apply bias rules (Section 11.3)
        if h1_fast_now > h1_slow_now and h4_fast_now >= h4_slow_now:
            return BiasState.BULLISH
        elif h1_fast_now < h1_slow_now and h4_fast_now <= h4_slow_now:
            return BiasState.BEARISH
        else:
            return BiasState.NEUTRAL
    
    def _calculate_ema(self, series: pd.Series, period: int) -> pd.Series:
        """Calculate Exponential Moving Average."""
        return series.ewm(span=period, adjust=False).mean()
    
    def get_ema_values(self, df: pd.DataFrame, timeframe: str = "H1") -> dict:
        """Get current EMA values for analysis.
        
        Args:
            df: OHLC dataframe
            timeframe: Timeframe label for output
            
        Returns:
            Dictionary with EMA values
        """
        if len(df) < self.slow_period:
            return {
                'timeframe': timeframe,
                'fast': None,
                'slow': None,
                'aligned': False
            }
        
        fast_ema = self._calculate_ema(df['close'], self.fast_period)
        slow_ema = self._calculate_ema(df['close'], self.slow_period)
        
        return {
            'timeframe': timeframe,
            'fast': fast_ema.iloc[-1],
            'slow': slow_ema.iloc[-1],
            'aligned': fast_ema.iloc[-1] > slow_ema.iloc[-1]
        }
    
    def calculate_bias_strength(self, h4_df: pd.DataFrame, h1_df: pd.DataFrame) -> float:
        """Calculate bias strength score (0 to 1).
        
        Stronger bias when:
        - EMAs are well-separated
        - Both timeframes agree
        - Slope is consistent
        
        Args:
            h4_df: H4 OHLC dataframe
            h1_df: H1 OHLC dataframe
            
        Returns:
            Strength score from 0 (weak) to 1 (strong)
        """
        bias = self.calculate_bias(h4_df, h1_df)
        
        if bias == BiasState.NEUTRAL:
            return 0.0
        
        # Calculate separation on both timeframes
        h4_fast = self._calculate_ema(h4_df['close'], self.fast_period).iloc[-1]
        h4_slow = self._calculate_ema(h4_df['close'], self.slow_period).iloc[-1]
        h1_fast = self._calculate_ema(h1_df['close'], self.fast_period).iloc[-1]
        h1_slow = self._calculate_ema(h1_df['close'], self.slow_period).iloc[-1]
        
        # Percentage separation
        h4_sep = abs(h4_fast - h4_slow) / h4_slow
        h1_sep = abs(h1_fast - h1_slow) / h1_slow
        
        # Average separation (capped at 2%)
        avg_sep = (h4_sep + h1_sep) / 2
        strength = min(avg_sep / 0.02, 1.0)
        
        return strength
    
    def prefers_longs(self, bias: BiasState) -> bool:
        """Check if bias prefers long trades (Section 11.4)."""
        return bias == BiasState.BULLISH
    
    def prefers_shorts(self, bias: BiasState) -> bool:
        """Check if bias prefers short trades (Section 11.4)."""
        return bias == BiasState.BEARISH
    
    def is_neutral(self, bias: BiasState) -> bool:
        """Check if bias is neutral (Section 11.4)."""
        return bias == BiasState.NEUTRAL

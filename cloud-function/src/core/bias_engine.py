"""
Bias Detection Engine for Zone-Based Intraday Trading Strategy

Determines directional bias from H4 and H1 timeframes using EMA crossovers
and optional market structure confirmation.

Reference: strategy.md Section 11 (Directional Bias Model)
"""

import pandas as pd
import numpy as np
from typing import Optional, Dict
from enum import Enum
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


class BiasState(Enum):
    """Directional bias state"""
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


@dataclass
class BiasContext:
    """
    Complete bias context from H4 and H1
    
    Includes EMA positions, slopes, and market structure information
    """
    bias: BiasState
    h4_fast_ema: float
    h4_slow_ema: float
    h4_bias: BiasState
    h1_fast_ema: float
    h1_slow_ema: float
    h1_bias: BiasState
    confidence: float  # 0.0 to 1.0
    
    # Market structure (optional)
    making_higher_highs: Optional[bool] = None
    making_higher_lows: Optional[bool] = None
    making_lower_highs: Optional[bool] = None
    making_lower_lows: Optional[bool] = None
    
    def to_dict(self) -> Dict:
        """Convert to dictionary"""
        return {
            'bias': self.bias.value,
            'h4_fast_ema': self.h4_fast_ema,
            'h4_slow_ema': self.h4_slow_ema,
            'h4_bias': self.h4_bias.value,
            'h1_fast_ema': self.h1_fast_ema,
            'h1_slow_ema': self.h1_slow_ema,
            'h1_bias': self.h1_bias.value,
            'confidence': self.confidence,
            'making_higher_highs': self.making_higher_highs,
            'making_higher_lows': self.making_higher_lows,
            'making_lower_highs': self.making_lower_highs,
            'making_lower_lows': self.making_lower_lows
        }


class BiasEngine:
    """
    Detects directional bias from H4 and H1 timeframes
    
    Uses EMA crossovers and optional market structure confirmation.
    
    Bias logic from strategy.md Section 11:
    - Bullish: H1 fast > H1 slow AND H4 fast >= H4 slow
    - Bearish: H1 fast < H1 slow AND H4 fast <= H4 slow
    - Neutral: Otherwise
    
    Trade preferences:
    - Bullish bias: prefer longs
    - Bearish bias: prefer shorts
    - Neutral bias: require higher trade score
    """
    
    def __init__(
        self,
        fast_period: int = 20,
        slow_period: int = 50,
        # Per-timeframe overrides (used by ZoneBasedIntradayStrategy)
        h4_fast_ema: Optional[int] = None,
        h4_slow_ema: Optional[int] = None,
        h1_fast_ema: Optional[int] = None,
        h1_slow_ema: Optional[int] = None,
        use_market_structure: bool = False,
        structure_lookback: int = 20
    ):
        """
        Initialize bias engine
        
        Args:
            fast_period: Shared fast EMA period, used when per-timeframe value is not given
            slow_period: Shared slow EMA period, used when per-timeframe value is not given
            h4_fast_ema: Fast EMA period for H4 (overrides fast_period)
            h4_slow_ema: Slow EMA period for H4 (overrides slow_period)
            h1_fast_ema: Fast EMA period for H1 (overrides fast_period)
            h1_slow_ema: Slow EMA period for H1 (overrides slow_period)
            use_market_structure: Enable market structure confirmation
            structure_lookback: Bars to look back for market structure
        """
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.h4_fast_period = h4_fast_ema if h4_fast_ema is not None else fast_period
        self.h4_slow_period = h4_slow_ema if h4_slow_ema is not None else slow_period
        self.h1_fast_period = h1_fast_ema if h1_fast_ema is not None else fast_period
        self.h1_slow_period = h1_slow_ema if h1_slow_ema is not None else slow_period
        self.use_market_structure = use_market_structure
        self.structure_lookback = structure_lookback
    
    def calculate_ema(self, series: pd.Series, period: int) -> pd.Series:
        """Calculate Exponential Moving Average"""
        return series.ewm(span=period, adjust=False).mean()
    
    def detect_bias_for_timeframe(
        self,
        df: pd.DataFrame,
        timeframe: str
    ) -> tuple[BiasState, float, float]:
        """
        Detect bias for a single timeframe
        
        Args:
            df: OHLC dataframe
            timeframe: Timeframe name (for logging)
        
        Returns:
            (bias_state, fast_ema, slow_ema)
        """
        # Use the correct slow period for this timeframe to guard against short data
        if timeframe == 'H4':
            required = self.h4_slow_period
        elif timeframe == 'H1':
            required = self.h1_slow_period
        else:
            required = self.slow_period
        if len(df) < required:
            logger.warning(f"Not enough data for {timeframe} bias detection")
            return BiasState.NEUTRAL, 0.0, 0.0
        
        close = df['close']
        
        # Use per-timeframe EMA periods when available
        if timeframe == 'H4':
            fast_p, slow_p = self.h4_fast_period, self.h4_slow_period
        elif timeframe == 'H1':
            fast_p, slow_p = self.h1_fast_period, self.h1_slow_period
        else:
            fast_p, slow_p = self.fast_period, self.slow_period
        
        # Calculate EMAs
        fast_ema = self.calculate_ema(close, fast_p)
        slow_ema = self.calculate_ema(close, slow_p)
        
        # Get latest values
        current_fast = fast_ema.iloc[-1]
        current_slow = slow_ema.iloc[-1]
        
        # Determine bias
        if current_fast > current_slow:
            bias = BiasState.BULLISH
        elif current_fast < current_slow:
            bias = BiasState.BEARISH
        else:
            bias = BiasState.NEUTRAL
        
        return bias, current_fast, current_slow
    
    def check_market_structure(self, df: pd.DataFrame) -> Dict[str, bool]:
        """
        Check market structure for trend confirmation
        
        Args:
            df: OHLC dataframe
        
        Returns:
            Dict with structure flags
        """
        if len(df) < self.structure_lookback:
            return {
                'higher_highs': None,
                'higher_lows': None,
                'lower_highs': None,
                'lower_lows': None
            }
        
        recent_data = df.tail(self.structure_lookback)
        
        # Simple structure check: compare first half vs second half
        mid_point = len(recent_data) // 2
        first_half = recent_data.iloc[:mid_point]
        second_half = recent_data.iloc[mid_point:]
        
        first_max = first_half['high'].max()
        first_min = first_half['low'].min()
        second_max = second_half['high'].max()
        second_min = second_half['low'].min()
        
        higher_highs = second_max > first_max
        higher_lows = second_min > first_min
        lower_highs = second_max < first_max
        lower_lows = second_min < first_min
        
        return {
            'higher_highs': higher_highs,
            'higher_lows': higher_lows,
            'lower_highs': lower_highs,
            'lower_lows': lower_lows
        }
    
    def calculate_confidence(
        self,
        h4_bias: BiasState,
        h1_bias: BiasState,
        h4_fast: float,
        h4_slow: float,
        h1_fast: float,
        h1_slow: float,
        structure: Optional[Dict] = None
    ) -> float:
        """
        Calculate confidence in the bias
        
        Confidence factors:
        - Both timeframes agree: high confidence
        - Large EMA separation: higher confidence
        - Market structure confirms: higher confidence
        
        Returns:
            Confidence score 0.0 to 1.0
        """
        confidence = 0.5  # Base
        
        # Timeframe agreement
        if h4_bias == h1_bias and h4_bias != BiasState.NEUTRAL:
            confidence += 0.3
        
        # EMA separation (as % of price)
        h4_separation = abs(h4_fast - h4_slow) / h4_slow if h4_slow > 0 else 0
        h1_separation = abs(h1_fast - h1_slow) / h1_slow if h1_slow > 0 else 0
        
        # Strong separation (>1%) adds confidence
        if h4_separation > 0.01:
            confidence += 0.1
        if h1_separation > 0.01:
            confidence += 0.1
        
        # Market structure confirmation
        if structure and self.use_market_structure:
            if h4_bias == BiasState.BULLISH:
                if structure.get('higher_highs') and structure.get('higher_lows'):
                    confidence += 0.1
            elif h4_bias == BiasState.BEARISH:
                if structure.get('lower_highs') and structure.get('lower_lows'):
                    confidence += 0.1
        
        return min(confidence, 1.0)
    
    def detect_bias(
        self,
        df_h4: pd.DataFrame,
        df_h1: pd.DataFrame
    ) -> BiasContext:
        """
        Detect overall directional bias from H4 and H1
        
        Args:
            df_h4: H4 OHLC dataframe
            df_h1: H1 OHLC dataframe
        
        Returns:
            BiasContext with complete bias information
        """
        # Detect bias for each timeframe
        h4_bias, h4_fast, h4_slow = self.detect_bias_for_timeframe(df_h4, 'H4')
        h1_bias, h1_fast, h1_slow = self.detect_bias_for_timeframe(df_h1, 'H1')
        
        # Overall bias logic from strategy.md Section 11.3
        if h1_fast > h1_slow and h4_fast >= h4_slow:
            overall_bias = BiasState.BULLISH
        elif h1_fast < h1_slow and h4_fast <= h4_slow:
            overall_bias = BiasState.BEARISH
        else:
            overall_bias = BiasState.NEUTRAL
        
        # Check market structure (optional)
        structure = None
        if self.use_market_structure:
            structure = self.check_market_structure(df_h1)  # Use H1 for structure
        
        # Calculate confidence
        confidence = self.calculate_confidence(
            h4_bias, h1_bias,
            h4_fast, h4_slow,
            h1_fast, h1_slow,
            structure
        )
        
        bias_context = BiasContext(
            bias=overall_bias,
            h4_fast_ema=h4_fast,
            h4_slow_ema=h4_slow,
            h4_bias=h4_bias,
            h1_fast_ema=h1_fast,
            h1_slow_ema=h1_slow,
            h1_bias=h1_bias,
            confidence=confidence
        )
        
        if structure:
            bias_context.making_higher_highs = structure['higher_highs']
            bias_context.making_higher_lows = structure['higher_lows']
            bias_context.making_lower_highs = structure['lower_highs']
            bias_context.making_lower_lows = structure['lower_lows']
        
        logger.info(
            f"Bias detected: {overall_bias.value} "
            f"(H4: {h4_bias.value}, H1: {h1_bias.value}, "
            f"confidence: {confidence:.2f})"
        )
        
        return bias_context
    
    def should_prefer_longs(self, bias_context: BiasContext) -> bool:
        """
        Check if conditions favor long trades
        
        Returns:
            True if longs are preferred
        """
        return bias_context.bias == BiasState.BULLISH
    
    def should_prefer_shorts(self, bias_context: BiasContext) -> bool:
        """
        Check if conditions favor short trades
        
        Returns:
            True if shorts are preferred
        """
        return bias_context.bias == BiasState.BEARISH
    
    def get_bias_score_adjustment(
        self,
        bias_context: BiasContext,
        direction: str
    ) -> int:
        """
        Get trade score adjustment based on bias alignment
        
        From strategy.md Section 17.2:
        - Directional bias alignment: ±20 points
        
        Args:
            bias_context: Current bias
            direction: 'long' or 'short'
        
        Returns:
            Score adjustment (-20 to +20)
        """
        if direction == 'long':
            if bias_context.bias == BiasState.BULLISH:
                return 20
            elif bias_context.bias == BiasState.BEARISH:
                return -10  # Counter-trend
            else:
                return 0  # Neutral
        
        elif direction == 'short':
            if bias_context.bias == BiasState.BEARISH:
                return 20
            elif bias_context.bias == BiasState.BULLISH:
                return -10  # Counter-trend
            else:
                return 0  # Neutral
        
        return 0

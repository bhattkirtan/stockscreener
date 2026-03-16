"""
Trigger Detection Engine for Zone-Based Intraday Trading Strategy

Detects M5 execution triggers: reclaim, rejection, breakout, and retest patterns.

Reference: strategy.md Section 12 (Trigger Model)
"""

import pandas as pd
import numpy as np
from typing import Optional, Dict, List
from enum import Enum
from dataclasses import dataclass
import logging

from . import indicators as _ind

logger = logging.getLogger(__name__)


class TriggerType(Enum):
    """Type of M5 trigger"""
    BULLISH_RECLAIM = "bullish_reclaim"
    BEARISH_REJECTION = "bearish_rejection"
    BREAKDOWN_FAILED_RETEST = "breakdown_failed_retest"
    BREAKOUT_SUCCESSFUL_RETEST = "breakout_successful_retest"
    NO_TRIGGER = "no_trigger"


@dataclass
class TriggerContext:
    """
    Complete trigger context from M5
    
    Describes the trigger type, quality, and confirmation strength
    """
    trigger_type: TriggerType
    quality_score: float  # 0 to 15 points
    timestamp: pd.Timestamp
    trigger_price: float
    
    # Candle details - M5 trigger candle
    open: float
    high: float
    low: float
    close: float
    prev_high: float
    prev_low: float
    
    # Confirmation flags
    closes_strong: bool = False  # Close near high (bullish) or low (bearish)
    volume_surge: bool = False  # Higher than average volume
    impulsive_move: bool = False  # Large candle body
    
    def to_dict(self) -> Dict:
        """Convert to dictionary"""
        return {
            'trigger_type': self.trigger_type.value,
            'quality_score': self.quality_score,
            'timestamp': self.timestamp.isoformat(),
            'trigger_price': self.trigger_price,
            'open': self.open,
            'high': self.high,
            'low': self.low,
            'close': self.close,
            'prev_high': self.prev_high,
            'prev_low': self.prev_low,
            'closes_strong': self.closes_strong,
            'volume_surge': self.volume_surge,
            'impulsive_move': self.impulsive_move
        }


class TriggerEngine:
    """
    Detects M5 execution triggers
    
    Trigger types from strategy.md Section 12.1:
    1. Bullish reclaim: Close above previous bar high, bullish candle
    2. Bearish rejection: Close below previous bar low, bearish candle
    3. Breakdown + failed retest: Break support, retest from below, reject
    4. Breakout + successful retest: Break resistance, retest from above, hold
    
    Trigger quality scoring (0 to 15 points):
    - Strong close: +5
    - Volume surge: +3
    - Impulsive move: +4
    - Clean candlestick pattern: +3
    """
    
    def __init__(
        self,
        strong_close_threshold: float = 0.7,  # Close in top/bottom 70% of candle
        volume_surge_multiplier: float = 1.5,  # 1.5x average volume
        impulsive_move_atr_fraction: float = 0.5  # Candle body > 50% ATR
    ):
        """
        Initialize trigger engine
        
        Args:
            strong_close_threshold: Fraction of candle for "strong close"
            volume_surge_multiplier: Multiple of avg volume for "surge"
            impulsive_move_atr_fraction: ATR fraction for "impulsive"
        """
        self.strong_close_threshold = strong_close_threshold
        self.volume_surge_multiplier = volume_surge_multiplier
        self.impulsive_move_atr_fraction = impulsive_move_atr_fraction
    
    def calculate_atr(self, df: pd.DataFrame, period: int = 14) -> float:
        """Calculate Average True Range (delegates to indicators module)."""
        series = _ind.calculate_atr(df, period)
        return series.iloc[-1] if not series.empty else 0.0
    
    def check_bullish_reclaim(
        self,
        current: pd.Series,
        previous: pd.Series
    ) -> bool:
        """
        Check for bullish reclaim trigger
        
        From strategy.md Section 12.2:
        - Current M5 bar closes above previous bar high
        - Current bar closes bullish (close > open)
        
        Args:
            current: Current M5 bar
            previous: Previous M5 bar
        
        Returns:
            True if bullish reclaim detected
        """
        closes_above_prev_high = current['close'] > previous['high']
        closes_bullish = current['close'] > current['open']
        
        return closes_above_prev_high and closes_bullish
    
    def check_bearish_rejection(
        self,
        current: pd.Series,
        previous: pd.Series
    ) -> bool:
        """
        Check for bearish rejection trigger
        
        From strategy.md Section 12.2:
        - Current M5 bar closes below previous bar low
        - Current bar closes bearish (close < open)
        
        Args:
            current: Current M5 bar
            previous: Previous M5 bar
        
        Returns:
            True if bearish rejection detected
        """
        closes_below_prev_low = current['close'] < previous['low']
        closes_bearish = current['close'] < current['open']
        
        return closes_below_prev_low and closes_bearish
    
    def check_closes_strong(
        self,
        open_price: float,
        high: float,
        low: float,
        close: float,
        direction: str
    ) -> bool:
        """
        Check if candle closes strongly in direction of move
        
        Args:
            open_price: Open price
            high: High price
            low: Low price
            close: Close price
            direction: 'bullish' or 'bearish'
        
        Returns:
            True if closes in top/bottom 70% of range
        """
        candle_range = high - low
        if candle_range == 0:
            return False
        
        if direction == 'bullish':
            # Close should be in top 70% of candle range
            close_position = (close - low) / candle_range
            return close_position >= self.strong_close_threshold
        
        elif direction == 'bearish':
            # Close should be in bottom 30% of candle range
            close_position = (close - low) / candle_range
            return close_position <= (1 - self.strong_close_threshold)
        
        return False
    
    def check_volume_surge(
        self,
        df: pd.DataFrame,
        lookback: int = 20
    ) -> bool:
        """
        Check if current volume is significantly higher than average
        
        Args:
            df: Recent M5 data
            lookback: Bars for average calculation
        
        Returns:
            True if volume surge detected
        """
        if 'volume' not in df.columns or df['volume'].iloc[-1] == 0:
            return False  # No volume data
        
        if len(df) < lookback + 1:
            return False
        
        current_volume = df['volume'].iloc[-1]
        avg_volume = df['volume'].iloc[-(lookback+1):-1].mean()
        
        if avg_volume == 0:
            return False
        
        return current_volume >= (self.volume_surge_multiplier * avg_volume)
    
    def check_impulsive_move(
        self,
        open_price: float,
        close: float,
        atr: float
    ) -> bool:
        """
        Check if candle body is impulsive (large relative to ATR)
        
        Args:
            open_price: Open price
            close: Close price
            atr: Current ATR
        
        Returns:
            True if move is impulsive
        """
        if atr == 0:
            return False
        
        body_size = abs(close - open_price)
        return body_size >= (self.impulsive_move_atr_fraction * atr)
    
    def calculate_trigger_quality(
        self,
        trigger_context: TriggerContext
    ) -> float:
        """
        Calculate trigger quality score (0 to 15 points)
        
        Scoring:
        - Strong close: +5
        - Volume surge: +3
        - Impulsive move: +4
        - Clean pattern: +3 (base for any valid trigger)
        
        Args:
            trigger_context: Trigger context with confirmation flags
        
        Returns:
            Quality score (0 to 15)
        """
        score = 3  # Base score for having a valid trigger
        
        if trigger_context.closes_strong:
            score += 5
        
        if trigger_context.volume_surge:
            score += 3
        
        if trigger_context.impulsive_move:
            score += 4
        
        return min(score, 15)  # Cap at 15
    
    def detect_trigger(
        self,
        df_m5: pd.DataFrame,
        min_bars: int = 30
    ) -> TriggerContext:
        """
        Detect M5 trigger from recent data
        
        Args:
            df_m5: M5 OHLC dataframe (recent bars)
            min_bars: Minimum bars needed for detection
        
        Returns:
            TriggerContext with trigger information
        """
        if len(df_m5) < min_bars:
            logger.warning(f"Not enough M5 data for trigger detection")
            return TriggerContext(
                trigger_type=TriggerType.NO_TRIGGER,
                quality_score=0.0,
                timestamp=df_m5.index[-1] if len(df_m5) > 0 else pd.Timestamp.now(),
                trigger_price=0.0,
                open=0.0, high=0.0, low=0.0, close=0.0,
                prev_high=0.0, prev_low=0.0
            )
        
        # Get current and previous bars
        current = df_m5.iloc[-1]
        previous = df_m5.iloc[-2]
        
        # Calculate ATR for quality checks
        atr = self.calculate_atr(df_m5)
        
        # Detect trigger type
        trigger_type = TriggerType.NO_TRIGGER
        direction = None
        
        if self.check_bullish_reclaim(current, previous):
            trigger_type = TriggerType.BULLISH_RECLAIM
            direction = 'bullish'
        elif self.check_bearish_rejection(current, previous):
            trigger_type = TriggerType.BEARISH_REJECTION
            direction = 'bearish'
        
        # Create trigger context
        trigger_context = TriggerContext(
            trigger_type=trigger_type,
            quality_score=0.0,  # Will be calculated below
            timestamp=df_m5.index[-1],
            trigger_price=current['close'],
            open=current['open'],
            high=current['high'],
            low=current['low'],
            close=current['close'],
            prev_high=previous['high'],
            prev_low=previous['low']
        )
        
        # Calculate confirmation flags
        if direction:
            trigger_context.closes_strong = self.check_closes_strong(
                current['open'], current['high'], current['low'],
                current['close'], direction
            )
            
            trigger_context.volume_surge = self.check_volume_surge(df_m5)
            
            trigger_context.impulsive_move = self.check_impulsive_move(
                current['open'], current['close'], atr
            )
            
            # Calculate quality score
            trigger_context.quality_score = self.calculate_trigger_quality(
                trigger_context
            )
        
        if trigger_type != TriggerType.NO_TRIGGER:
            logger.info(
                f"Trigger detected: {trigger_type.value} "
                f"(quality: {trigger_context.quality_score:.1f}/15, "
                f"price: {current['close']:.2f})"
            )
        
        return trigger_context
    
    def is_valid_long_trigger(self, trigger_context: TriggerContext) -> bool:
        """
        Check if trigger is valid for long entry
        
        Returns:
            True if valid long trigger
        """
        return trigger_context.trigger_type in [
            TriggerType.BULLISH_RECLAIM,
            TriggerType.BREAKOUT_SUCCESSFUL_RETEST
        ]
    
    def is_valid_short_trigger(self, trigger_context: TriggerContext) -> bool:
        """
        Check if trigger is valid for short entry
        
        Returns:
            True if valid short trigger
        """
        return trigger_context.trigger_type in [
            TriggerType.BEARISH_REJECTION,
            TriggerType.BREAKDOWN_FAILED_RETEST
        ]
    
    def get_trigger_score_adjustment(
        self,
        trigger_context: TriggerContext,
        direction: str
    ) -> int:
        """
        Get trade score adjustment based on trigger quality
        
        From strategy.md Section 17.2:
        - Trigger quality: 0 to 15 points
        
        Args:
            trigger_context: Current trigger
            direction: 'long' or 'short'
        
        Returns:
            Score adjustment (0 to 15)
        """
        if direction == 'long' and self.is_valid_long_trigger(trigger_context):
            return int(trigger_context.quality_score)
        elif direction == 'short' and self.is_valid_short_trigger(trigger_context):
            return int(trigger_context.quality_score)
        else:
            return -10  # Wrong trigger direction

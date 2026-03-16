"""M5 trigger detection for trade entries."""

from enum import Enum
from typing import Optional
import pandas as pd


class TriggerType(Enum):
    """Allowed trigger types (Section 12.1)."""
    BULLISH_RECLAIM = "bullish_reclaim"
    BEARISH_REJECTION = "bearish_rejection"
    BREAKDOWN_FAILED_RETEST = "breakdown_failed_retest"
    BREAKOUT_SUCCESSFUL_RETEST = "breakout_successful_retest"
    NONE = "none"


class TriggerDetector:
    """M5 trigger detection following Section 12."""
    
    def __init__(self):
        """Initialize trigger detector."""
        pass
    
    def detect_trigger(self, m5_df: pd.DataFrame, 
                      support_zone: Optional[float] = None,
                      resistance_zone: Optional[float] = None) -> TriggerType:
        """Detect M5 trigger for entry (Section 12).
        
        Args:
            m5_df: M5 OHLC dataframe (recent bars)
            support_zone: Support zone midpoint (optional)
            resistance_zone: Resistance zone midpoint (optional)
            
        Returns:
            Detected trigger type
        """
        if len(m5_df) < 3:
            return TriggerType.NONE
        
        current_bar = m5_df.iloc[-1]
        prev_bar = m5_df.iloc[-2]
        
        # Bullish reclaim (Section 12.2)
        if self._is_bullish_reclaim(current_bar, prev_bar):
            return TriggerType.BULLISH_RECLAIM
        
        # Bearish rejection (Section 12.2)
        if self._is_bearish_rejection(current_bar, prev_bar):
            return TriggerType.BEARISH_REJECTION
        
        # Breakdown + failed retest (Section 12.2)
        if support_zone and self._is_breakdown_failed_retest(m5_df, support_zone):
            return TriggerType.BREAKDOWN_FAILED_RETEST
        
        # Breakout + successful retest (Section 12.2)
        if resistance_zone and self._is_breakout_successful_retest(m5_df, resistance_zone):
            return TriggerType.BREAKOUT_SUCCESSFUL_RETEST
        
        return TriggerType.NONE
    
    def _is_bullish_reclaim(self, current: pd.Series, prev: pd.Series) -> bool:
        """Bullish reclaim: Current M5 bar closes above prev bar high and closes bullish.
        
        Section 12.2: Current M5 bar closes above previous bar high and closes bullish.
        """
        closes_above_prev_high = current['close'] > prev['high']
        closes_bullish = current['close'] > current['open']
        
        return closes_above_prev_high and closes_bullish
    
    def _is_bearish_rejection(self, current: pd.Series, prev: pd.Series) -> bool:
        """Bearish rejection: Current M5 bar closes below prev bar low and closes bearish.
        
        Section 12.2: Current M5 bar closes below previous bar low and closes bearish.
        """
        closes_below_prev_low = current['close'] < prev['low']
        closes_bearish = current['close'] < current['open']
        
        return closes_below_prev_low and closes_bearish
    
    def _is_breakdown_failed_retest(self, df: pd.DataFrame, support_level: float) -> bool:
        """Breakdown + failed retest.
        
        Section 12.2: Price breaks support, retests it from below, and M5 confirms rejection.
        """
        if len(df) < 10:
            return False
        
        recent = df.iloc[-10:]
        
        # Look for breakdown pattern
        for i in range(len(recent) - 3):
            bar = recent.iloc[i]
            
            # Did price break below support?
            if bar['close'] < support_level:
                # Look for retest in next few bars
                next_bars = recent.iloc[i+1:i+4]
                
                for j, retest_bar in enumerate(next_bars.iterrows()):
                    _, retest = retest_bar
                    
                    # Did price retest support from below?
                    if retest['high'] >= support_level * 0.998:  # Allow small tolerance
                        # Did it reject back down?
                        if j + 1 < len(next_bars):
                            confirm_bar = next_bars.iloc[j + 1]
                            if confirm_bar['close'] < support_level:
                                return True
        
        return False
    
    def _is_breakout_successful_retest(self, df: pd.DataFrame, resistance_level: float) -> bool:
        """Breakout + successful retest.
        
        Section 12.2: Price breaks resistance, retests it from above, and M5 confirms hold.
        """
        if len(df) < 10:
            return False
        
        recent = df.iloc[-10:]
        
        # Look for breakout pattern
        for i in range(len(recent) - 3):
            bar = recent.iloc[i]
            
            # Did price break above resistance?
            if bar['close'] > resistance_level:
                # Look for retest in next few bars
                next_bars = recent.iloc[i+1:i+4]
                
                for j, retest_bar in enumerate(next_bars.iterrows()):
                    _, retest = retest_bar
                    
                    # Did price retest resistance from above?
                    if retest['low'] <= resistance_level * 1.002:  # Allow small tolerance
                        # Did it hold and bounce up?
                        if j + 1 < len(next_bars):
                            confirm_bar = next_bars.iloc[j + 1]
                            if confirm_bar['close'] > resistance_level:
                                return True
        
        return False
    
    def is_bullish_trigger(self, trigger: TriggerType) -> bool:
        """Check if trigger is bullish."""
        return trigger in [TriggerType.BULLISH_RECLAIM, TriggerType.BREAKOUT_SUCCESSFUL_RETEST]
    
    def is_bearish_trigger(self, trigger: TriggerType) -> bool:
        """Check if trigger is bearish."""
        return trigger in [TriggerType.BEARISH_REJECTION, TriggerType.BREAKDOWN_FAILED_RETEST]
    
    def get_trigger_quality_score(self, trigger: TriggerType, m5_df: pd.DataFrame) -> float:
        """Calculate trigger quality score for trade scoring (0-15 points).
        
        Section 17.2: Trigger quality contributes 15 points to total trade score.
        
        Args:
            trigger: Detected trigger type
            m5_df: Recent M5 data
            
        Returns:
            Quality score from 0 to 15
        """
        if trigger == TriggerType.NONE:
            return 0.0
        
        base_score = 10.0  # Base score for valid trigger
        
        # Bonus for stronger triggers
        if len(m5_df) >= 2:
            current = m5_df.iloc[-1]
            bar_size = abs(current['close'] - current['open'])
            avg_bar_size = (m5_df.iloc[-10:]['high'] - m5_df.iloc[-10:]['low']).mean()
            
            # Larger confirmation bar = stronger trigger
            if bar_size > avg_bar_size * 1.5:
                base_score += 3.0
            elif bar_size > avg_bar_size:
                base_score += 1.5
        
        # Bonus for breakout/breakdown triggers (more significant)
        if trigger in [TriggerType.BREAKDOWN_FAILED_RETEST, TriggerType.BREAKOUT_SUCCESSFUL_RETEST]:
            base_score += 2.0
        
        return min(base_score, 15.0)

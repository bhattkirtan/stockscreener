"""Zone strength scoring system."""

from typing import List
import pandas as pd
from .zone_engine import Zone, ZoneType, ZoneState, OriginType


class ZoneScorer:
    """Zone strength scoring following production spec Section 10."""
    
    def __init__(self, symbol: str = "GOLD"):
        """Initialize zone scorer.
        
        Args:
            symbol: Trading symbol (GOLD or US100)
        """
        self.symbol = symbol
        self.timeframe_weights = {
            'H4': 3,
            'H1': 2,
            'M15': 1
        }
        
        # Strong zone thresholds from spec
        self.strong_thresholds = {
            'GOLD': 4.0,
            'US100': 3.5
        }
    
    def score_zone(self, zone: Zone, df: pd.DataFrame, 
                   round_numbers: List[float] = None) -> float:
        """Calculate zone strength score.
        
        Args:
            zone: Zone to score
            df: Recent OHLC data for the timeframe
            round_numbers: List of psychologically significant levels
            
        Returns:
            Zone strength score
        """
        score = 0.0
        
        # Base timeframe weight (Section 10.1)
        score += self.timeframe_weights.get(zone.timeframe, 1)
        
        # Fresh zone bonus (Section 10.2)
        if zone.state == ZoneState.FRESH:
            score += 1.0
        
        # Touch count modifier (Section 10.2)
        if 2 <= zone.touch_count <= 3:
            score += min(zone.touch_count * 0.25, 2.0)
        elif zone.touch_count > 5:
            # Too many messy touches (Section 10.2)
            score -= 1.0
        
        # Zone respect/rejection analysis
        rejection_score = self._analyze_rejections(zone, df)
        score += rejection_score
        
        # Check for impulsive move away (Section 10.2)
        if self._has_impulsive_move_away(zone, df):
            score += 1.0
        
        # Breakout-retest bonus (Section 10.2)
        if zone.origin_type == OriginType.BREAKOUT_RETEST:
            score += 2.0
        
        # Round number alignment (Section 10.2)
        if round_numbers and self._aligns_with_round_number(zone, round_numbers):
            score += 0.5
        
        # Session high/low alignment (Section 10.2)
        if zone.origin_type == OriginType.SESSION_HIGH_LOW:
            score += 1.0
        
        # Previous day extreme alignment (Section 10.2)
        if zone.origin_type == OriginType.PREVIOUS_DAY_EXTREME:
            score += 1.0
        
        # Stale zone penalty (Section 10.2)
        if self._is_stale(zone, df):
            score -= 1.0
        
        # Repeated intrazone chopping penalty (Section 10.2)
        if self._has_intrazone_chopping(zone, df):
            score -= 1.0
        
        # State-based adjustments
        if zone.state == ZoneState.RESPECTED:
            score += 0.5
        elif zone.state == ZoneState.WEAKENED:
            score -= 0.5
        elif zone.state == ZoneState.BROKEN:
            score -= 2.0
        
        return max(score, 0.0)
    
    def _analyze_rejections(self, zone: Zone, df: pd.DataFrame) -> float:
        """Analyze how strongly price rejected from the zone."""
        score = 0.0
        
        if len(df) < 10:
            return score
        
        recent_bars = df.iloc[-20:]
        
        for i in range(len(recent_bars)):
            bar = recent_bars.iloc[i]
            
            # Check if bar touched the zone
            if not zone.contains_price(bar['low']) and not zone.contains_price(bar['high']):
                continue
            
            # Look at next few bars for rejection
            if i + 3 < len(recent_bars):
                next_bars = recent_bars.iloc[i+1:i+4]
                
                if zone.type == ZoneType.SUPPORT:
                    # Strong rejection if price moves significantly up
                    bounce_size = next_bars['high'].max() - bar['low']
                    zone_width = zone.width
                    
                    if bounce_size > zone_width * 2:
                        score += 1.0  # Strong rejection bonus
                
                elif zone.type == ZoneType.RESISTANCE:
                    # Strong rejection if price moves significantly down
                    drop_size = bar['high'] - next_bars['low'].min()
                    zone_width = zone.width
                    
                    if drop_size > zone_width * 2:
                        score += 1.0  # Strong rejection bonus
        
        return min(score, 2.0)  # Cap at +2
    
    def _has_impulsive_move_away(self, zone: Zone, df: pd.DataFrame) -> bool:
        """Check if price moved impulsively away from zone."""
        if len(df) < 5:
            return False
        
        # Find bars that touched the zone
        recent_bars = df.iloc[-20:]
        
        for i in range(len(recent_bars) - 3):
            bar = recent_bars.iloc[i]
            
            if not zone.contains_price(bar['low']) and not zone.contains_price(bar['high']):
                continue
            
            # Check next 3 bars for impulse
            next_bars = recent_bars.iloc[i+1:i+4]
            
            if zone.type == ZoneType.SUPPORT:
                # Impulsive move up
                move_size = next_bars['high'].max() - bar['low']
                avg_bar_size = (next_bars['high'] - next_bars['low']).mean()
                
                if move_size > avg_bar_size * 3:
                    return True
            
            elif zone.type == ZoneType.RESISTANCE:
                # Impulsive move down
                move_size = bar['high'] - next_bars['low'].min()
                avg_bar_size = (next_bars['high'] - next_bars['low']).mean()
                
                if move_size > avg_bar_size * 3:
                    return True
        
        return False
    
    def _aligns_with_round_number(self, zone: Zone, round_numbers: List[float]) -> bool:
        """Check if zone aligns with a round number."""
        threshold = zone.width * 0.5
        
        for rn in round_numbers:
            if zone.lower_bound - threshold <= rn <= zone.upper_bound + threshold:
                return True
        
        return False
    
    def _is_stale(self, zone: Zone, df: pd.DataFrame) -> bool:
        """Check if zone is stale (hasn't been touched recently)."""
        if zone.last_tested_at is None:
            return True
        
        if len(df) < 50:
            return False
        
        # Check how many bars ago the zone was last tested
        recent_bars = df.iloc[-100:]
        
        if zone.last_tested_at < recent_bars.iloc[0]['timestamp']:
            return True
        
        return False
    
    def _has_intrazone_chopping(self, zone: Zone, df: pd.DataFrame) -> bool:
        """Check for repeated messy price action within the zone."""
        if len(df) < 20:
            return False
        
        recent_bars = df.iloc[-20:]
        
        # Count bars that stayed entirely within the zone
        bars_in_zone = 0
        for _, bar in recent_bars.iterrows():
            if (zone.lower_bound <= bar['low'] <= zone.upper_bound and 
                zone.lower_bound <= bar['high'] <= zone.upper_bound):
                bars_in_zone += 1
        
        # If more than 30% of bars chopped inside, it's messy
        if bars_in_zone / len(recent_bars) > 0.3:
            return True
        
        return False
    
    def score_cluster(self, cluster: List[Zone], df_dict: dict[str, pd.DataFrame]) -> float:
        """Score a zone cluster (Section 9.6).
        
        Args:
            cluster: List of overlapping zones from multiple timeframes
            df_dict: Dictionary mapping timeframe to dataframe
            
        Returns:
            Cluster strength score
        """
        if not cluster:
            return 0.0
        
        # Sum of component scores
        total_score = 0.0
        for zone in cluster:
            df = df_dict.get(zone.timeframe)
            if df is not None:
                total_score += self.score_zone(zone, df)
        
        # Overlap bonus (Section 9.6)
        overlap_bonus = 0
        if len(cluster) == 2:
            overlap_bonus = 1
        elif len(cluster) >= 3:
            overlap_bonus = 2
        
        return total_score + overlap_bonus
    
    def is_strong_zone(self, zone: Zone, df: pd.DataFrame) -> bool:
        """Check if zone is considered strong (Section 10.3).
        
        Args:
            zone: Zone to check
            df: Recent OHLC data
            
        Returns:
            True if zone score exceeds strong threshold
        """
        score = self.score_zone(zone, df)
        threshold = self.strong_thresholds.get(self.symbol, 4.0)
        
        return score >= threshold
    
    def rank_zones(self, zones: List[Zone], df_dict: dict[str, pd.DataFrame]) -> List[tuple[Zone, float]]:
        """Rank zones by strength score.
        
        Args:
            zones: List of zones to rank
            df_dict: Dictionary mapping timeframe to dataframe
            
        Returns:
            List of (zone, score) tuples sorted by score descending
        """
        scored_zones = []
        
        for zone in zones:
            df = df_dict.get(zone.timeframe)
            if df is not None:
                score = self.score_zone(zone, df)
                scored_zones.append((zone, score))
        
        # Sort by score descending
        scored_zones.sort(key=lambda x: x[1], reverse=True)
        
        return scored_zones

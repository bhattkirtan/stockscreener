"""
Zone Engine for Zone-Based Intraday Trading Strategy

Constructs, scores, and manages support/resistance zones from H4/H1/M15 timeframes.
Implements zone width, merge logic, cluster detection, and strength scoring.

Reference: strategy.md Section 9 (Zone Model)
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import logging

from . import indicators as _ind
from . import fibonacci as _fib

logger = logging.getLogger(__name__)


class ZoneType(Enum):
    """Type of zone"""
    SUPPORT = "support"
    RESISTANCE = "resistance"
    FLIP = "flip"


class ZoneState(Enum):
    """State of zone"""
    FRESH = "fresh"
    TESTED = "tested"
    RESPECTED = "respected"
    WEAKENED = "weakened"
    BROKEN = "broken"
    FLIPPED = "flipped"
    INVALID = "invalid"


class ZoneOriginType(Enum):
    """How the zone was created"""
    SWING = "swing"
    RANGE_EDGE = "range_edge"
    BREAKOUT_RETEST = "breakout_retest"
    IMPULSE_BASE = "impulse_base"
    SESSION_HIGH_LOW = "session_high_low"
    PREVIOUS_DAY_EXTREME = "previous_day_extreme"


@dataclass
class Zone:
    """
    A support or resistance zone with width and strength
    
    Zone schema from strategy.md Section 9.1
    """
    id: str
    symbol: str
    timeframe: str
    type: ZoneType
    lower_bound: float
    upper_bound: float
    midpoint: float
    origin_type: ZoneOriginType
    created_at: datetime
    last_tested_at: Optional[datetime] = None
    touch_count: int = 0
    freshness_score: float = 1.0
    strength_score: float = 0.0
    state: ZoneState = ZoneState.FRESH
    
    # Additional metadata
    atr_at_creation: float = 0.0
    component_zones: List[str] = field(default_factory=list)  # For clusters
    
    def __post_init__(self):
        """Calculate midpoint if not provided"""
        if self.midpoint == 0:
            self.midpoint = (self.lower_bound + self.upper_bound) / 2
    
    @property
    def width(self) -> float:
        """Zone width"""
        return self.upper_bound - self.lower_bound
    
    def contains(self, price: float) -> bool:
        """Check if price is inside zone"""
        return self.lower_bound <= price <= self.upper_bound
    
    def distance_to(self, price: float) -> float:
        """Distance from price to closest zone boundary"""
        if self.contains(price):
            return 0.0
        elif price < self.lower_bound:
            return self.lower_bound - price
        else:
            return price - self.upper_bound
    
    def overlaps_with(self, other: 'Zone') -> bool:
        """Check if this zone overlaps with another"""
        return not (self.upper_bound < other.lower_bound or 
                    self.lower_bound > other.upper_bound)
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for storage/logging"""
        return {
            'id': self.id,
            'symbol': self.symbol,
            'timeframe': self.timeframe,
            'type': self.type.value,
            'lower_bound': self.lower_bound,
            'upper_bound': self.upper_bound,
            'midpoint': self.midpoint,
            'width': self.width,
            'origin_type': self.origin_type.value,
            'created_at': self.created_at.isoformat(),
            'last_tested_at': self.last_tested_at.isoformat() if self.last_tested_at else None,
            'touch_count': self.touch_count,
            'freshness_score': self.freshness_score,
            'strength_score': self.strength_score,
            'state': self.state.value
        }


@dataclass
class ZoneCluster:
    """
    Cluster of overlapping zones from multiple timeframes
    
    Reference: strategy.md Section 9.6
    """
    id: str
    zones: List[Zone]
    lower_bound: float
    upper_bound: float
    midpoint: float
    cluster_score: float
    timeframes: List[str]
    
    def __post_init__(self):
        """Calculate cluster properties"""
        if not self.lower_bound and self.zones:
            self.lower_bound = min(z.lower_bound for z in self.zones)
        if not self.upper_bound and self.zones:
            self.upper_bound = max(z.upper_bound for z in self.zones)
        if not self.midpoint:
            self.midpoint = (self.lower_bound + self.upper_bound) / 2
        if not self.timeframes and self.zones:
            self.timeframes = [z.timeframe for z in self.zones]


class ZoneEngine:
    """
    Constructs and manages support/resistance zones
    
    Creates zones from swing points, calculates strength scores,
    handles merging and clustering across timeframes.
    
    Reference: strategy.md Sections 9-10
    """
    
    def __init__(
        self,
        symbol: str = "XAUUSD",
        # Zone width multipliers (ATR-based) — pass as dict OR as individual kwargs
        zone_width_multipliers: Optional[Dict[str, float]] = None,
        h4_width_multiplier: float = 0.35,
        h1_width_multiplier: float = 0.25,
        m15_width_multiplier: float = 0.18,
        # Strength thresholds
        strong_zone_threshold: float = 4.0,
        # Merge threshold
        merge_threshold_multiplier: float = 0.10
    ):
        """
        Initialize zone engine
        
        Args:
            symbol: Trading instrument
            zone_width_multipliers: Dict mapping timeframe to ATR multiplier, e.g.
                {'H4': 0.35, 'H1': 0.25, 'M15': 0.18}.  Takes precedence over the
                individual h4/h1/m15 kwargs when provided.
            h4_width_multiplier: ATR fraction for H4 zone width (default 0.35)
            h1_width_multiplier: ATR fraction for H1 zone width (default 0.25)
            m15_width_multiplier: ATR fraction for M15 zone width (default 0.18)
            strong_zone_threshold: Minimum score for strong zone (default 4.0)
            merge_threshold_multiplier: ATR fraction for merge distance (default 0.10)
        """
        self.symbol = symbol
        if zone_width_multipliers is not None:
            self.width_multipliers = zone_width_multipliers
        else:
            self.width_multipliers = {
                'H4': h4_width_multiplier,
                'H1': h1_width_multiplier,
                'M15': m15_width_multiplier
            }
        self.strong_zone_threshold = strong_zone_threshold
        self.merge_threshold_multiplier = merge_threshold_multiplier
        
        # Zone storage
        self.zones: Dict[str, List[Zone]] = {
            'H4': [],
            'H1': [],
            'M15': []
        }
        
        self.clusters: List[ZoneCluster] = []
    
    def calculate_atr(self, df: pd.DataFrame, period: int = 14) -> float:
        """Calculate Average True Range (delegates to indicators module)."""
        series = _ind.calculate_atr(df, period)
        return series.iloc[-1] if not series.empty else 0.0

    def find_swing_points(
        self,
        df: pd.DataFrame,
        lookback: int = 5
    ) -> Tuple[pd.Series, pd.Series]:
        """
        Find swing highs and swing lows (delegates to fibonacci module).

        Returns:
            (swing_highs, swing_lows) as boolean Series
        """
        return _fib.find_swing_points(df, lookback)
    
    def create_zone_from_swing(
        self,
        price: float,
        timeframe: str,
        zone_type: ZoneType,
        atr: float,
        timestamp: datetime,
        origin: ZoneOriginType = ZoneOriginType.SWING
    ) -> Zone:
        """
        Create a zone around a swing point
        
        Args:
            price: Center price of zone
            timeframe: H4, H1, or M15
            zone_type: SUPPORT or RESISTANCE
            atr: ATR value for width calculation
            timestamp: When zone was created
            origin: How zone was identified
        
        Returns:
            Zone object
        """
        width_multiplier = self.width_multipliers.get(timeframe, 0.20)
        half_width = width_multiplier * atr
        
        lower = price - half_width
        upper = price + half_width
        midpoint = price
        
        zone_id = f"{self.symbol}_{timeframe}_{zone_type.value}_{timestamp.isoformat()}"
        
        return Zone(
            id=zone_id,
            symbol=self.symbol,
            timeframe=timeframe,
            type=zone_type,
            lower_bound=lower,
            upper_bound=upper,
            midpoint=midpoint,
            origin_type=origin,
            created_at=timestamp,
            atr_at_creation=atr,
            state=ZoneState.FRESH
        )
    
    def build_zones_for_timeframe(
        self,
        df: pd.DataFrame,
        timeframe: str,
        lookback: int = 5,
        max_zones: int = 10
    ) -> List[Zone]:
        """
        Build zones from a single timeframe
        
        Args:
            df: OHLC dataframe
            timeframe: H4, H1, or M15
            lookback: Swing detection lookback
            max_zones: Maximum zones to keep (most recent)
        
        Returns:
            List of zones
        """
        if len(df) < lookback * 2:
            logger.warning(f"Not enough data for {timeframe} zone construction")
            return []
        
        # Calculate ATR
        atr = self.calculate_atr(df)
        if atr == 0:
            logger.warning(f"ATR is 0 for {timeframe}")
            return []
        
        # Find swing points
        swing_highs, swing_lows = self.find_swing_points(df, lookback)
        
        zones = []
        
        # Create resistance zones from swing highs
        swing_high_indices = df[swing_highs].index
        for idx in swing_high_indices[-max_zones:]:
            price = df.loc[idx, 'high']
            zone = self.create_zone_from_swing(
                price=price,
                timeframe=timeframe,
                zone_type=ZoneType.RESISTANCE,
                atr=atr,
                timestamp=idx,
                origin=ZoneOriginType.SWING
            )
            zones.append(zone)
        
        # Create support zones from swing lows
        swing_low_indices = df[swing_lows].index
        for idx in swing_low_indices[-max_zones:]:
            price = df.loc[idx, 'low']
            zone = self.create_zone_from_swing(
                price=price,
                timeframe=timeframe,
                zone_type=ZoneType.SUPPORT,
                atr=atr,
                timestamp=idx,
                origin=ZoneOriginType.SWING
            )
            zones.append(zone)
        
        logger.info(f"Built {len(zones)} zones for {timeframe}")
        return zones
    
    def merge_overlapping_zones(
        self,
        zones: List[Zone],
        timeframe: str,
        atr: float
    ) -> List[Zone]:
        """
        Merge zones that overlap or are too close
        
        Reference: strategy.md Section 9.5
        
        Args:
            zones: List of zones to merge
            timeframe: Timeframe for these zones
            atr: Current ATR for merge threshold
        
        Returns:
            List of merged zones
        """
        if len(zones) <= 1:
            return zones
        
        merge_threshold = self.merge_threshold_multiplier * atr
        
        # Separate by type
        support_zones = [z for z in zones if z.type == ZoneType.SUPPORT]
        resistance_zones = [z for z in zones if z.type == ZoneType.RESISTANCE]
        
        merged = []
        
        for zone_list in [support_zones, resistance_zones]:
            if not zone_list:
                continue
            
            # Sort by lower bound
            sorted_zones = sorted(zone_list, key=lambda z: z.lower_bound)
            
            current_merged = sorted_zones[0]
            
            for next_zone in sorted_zones[1:]:
                # Check if zones overlap or gap is below merge threshold
                gap = next_zone.lower_bound - current_merged.upper_bound
                
                if gap <= merge_threshold:
                    # Merge zones
                    new_lower = min(current_merged.lower_bound, next_zone.lower_bound)
                    new_upper = max(current_merged.upper_bound, next_zone.upper_bound)
                    new_midpoint = (new_lower + new_upper) / 2
                    
                    # Sum scores and touch counts
                    new_strength = current_merged.strength_score + next_zone.strength_score + 1
                    new_touches = current_merged.touch_count + next_zone.touch_count
                    
                    # Keep most recent timestamp
                    new_timestamp = max(current_merged.created_at, next_zone.created_at)
                    
                    current_merged = Zone(
                        id=f"{current_merged.id}_merged",
                        symbol=self.symbol,
                        timeframe=timeframe,
                        type=current_merged.type,
                        lower_bound=new_lower,
                        upper_bound=new_upper,
                        midpoint=new_midpoint,
                        origin_type=ZoneOriginType.RANGE_EDGE,
                        created_at=new_timestamp,
                        touch_count=new_touches,
                        strength_score=new_strength,
                        state=ZoneState.TESTED,
                        component_zones=[current_merged.id, next_zone.id]
                    )
                else:
                    # No merge, save current and move to next
                    merged.append(current_merged)
                    current_merged = next_zone
            
            # Add last zone
            merged.append(current_merged)
        
        logger.info(f"Merged {len(zones)} → {len(merged)} zones for {timeframe}")
        return merged
    
    def score_zone(self, zone: Zone, df: pd.DataFrame) -> float:
        """
        Calculate zone strength score
        
        Reference: strategy.md Section 10 (Zone Strength Scoring)
        
        Scoring components:
        - Base timeframe weight: H4=3, H1=2, M15=1
        - Strong rejection: +1
        - Breakout + retest: +2
        - Round number alignment: +0.5
        - Fresh zone: +1
        - Valid touches (2-3): +0.25 each
        - Too many touches: -1
        - Stale zone: -1
        
        Args:
            zone: Zone to score
            df: Recent price data for context
        
        Returns:
            Strength score (float)
        """
        score = 0.0
        
        # Base timeframe weight
        timeframe_weights = {'H4': 3, 'H1': 2, 'M15': 1}
        score += timeframe_weights.get(zone.timeframe, 1)
        
        # Fresh zone bonus
        if zone.state == ZoneState.FRESH:
            score += 1
        
        # Touch count scoring
        if 2 <= zone.touch_count <= 3:
            score += zone.touch_count * 0.25
        elif zone.touch_count > 5:
            score -= 1  # Too messy
        
        # Check for round number alignment (for gold: multiples of 10 or 100)
        midpoint = zone.midpoint
        if abs(midpoint % 100) < 5 or abs(midpoint % 100) > 95:
            score += 0.5  # Near 100s place
        elif abs(midpoint % 10) < 1 or abs(midpoint % 10) > 9:
            score += 0.25  # Near 10s place
        
        # Check for strong rejection (price wicked through zone but closed outside)
        if len(df) > 0:
            recent_bars = df.tail(20)
            for idx, row in recent_bars.iterrows():
                if zone.type == ZoneType.SUPPORT:
                    # Look for bullish rejection
                    if row['low'] <= zone.lower_bound and row['close'] > zone.upper_bound:
                        score += 1
                        break
                elif zone.type == ZoneType.RESISTANCE:
                    # Look for bearish rejection
                    if row['high'] >= zone.upper_bound and row['close'] < zone.lower_bound:
                        score += 1
                        break
        
        # Staleness penalty: penalise if last test is old relative to the data range
        if zone.last_tested_at and len(df) > 0 and hasattr(df.index, 'max'):
            latest_bar = df.index.max()
            if hasattr(latest_bar, 'floor'):  # DatetimeIndex
                from pandas import Timedelta
                age = latest_bar - zone.last_tested_at
                if age > Timedelta(days=7):
                    score -= 1
        
        return score
    
    def build_all_zones(
        self,
        df_h4: pd.DataFrame,
        df_h1: pd.DataFrame,
        df_m15: pd.DataFrame
    ) -> Dict[str, List[Zone]]:
        """
        Build zones from all three timeframes
        
        Args:
            df_h4: H4 OHLC data
            df_h1: H1 OHLC data
            df_m15: M15 OHLC data
        
        Returns:
            Dict mapping timeframe to list of zones
        """
        all_zones = {}
        
        # Build zones for each timeframe
        for timeframe, df in [('H4', df_h4), ('H1', df_h1), ('M15', df_m15)]:
            zones = self.build_zones_for_timeframe(df, timeframe)
            
            # Merge overlapping zones
            atr = self.calculate_atr(df)
            zones = self.merge_overlapping_zones(zones, timeframe, atr)
            
            # Score zones
            for zone in zones:
                zone.strength_score = self.score_zone(zone, df)
            
            all_zones[timeframe] = zones
            self.zones[timeframe] = zones
        
        # Build clusters
        self.clusters = self.build_clusters()
        
        return all_zones
    
    def build_zones(
        self,
        df: pd.DataFrame,
        timeframe: str,
        lookback: int = 5,
        max_zones: int = 10
    ) -> List[Zone]:
        """
        Build, merge, and score zones for a single timeframe, then store them.

        Runs the full pipeline (build → merge overlapping → score) so that
        zones returned by this method are equivalent to those produced by
        build_all_zones() for the same timeframe.
        """
        zones = self.build_zones_for_timeframe(df, timeframe, lookback, max_zones)
        atr = self.calculate_atr(df)
        zones = self.merge_overlapping_zones(zones, timeframe, atr)
        for zone in zones:
            zone.strength_score = self.score_zone(zone, df)
        self.zones[timeframe] = zones
        return zones

    def build_clusters(self, all_zones: Optional[List['Zone']] = None) -> List[ZoneCluster]:
        """
        Build clusters from overlapping zones across timeframes.

        Reference: strategy.md Section 9.6

        Cluster score = sum(component scores) + overlap bonus
        - 2 timeframes: +1
        - 3 timeframes: +2

        Args:
            all_zones: Optional flat list of zones to cluster.  When omitted
                       the engine uses the zones stored in self.zones.

        Returns:
            List of zone clusters
        """
        if all_zones is None:
            all_zones = []
            for timeframe in ['H4', 'H1', 'M15']:
                all_zones.extend(self.zones[timeframe])
        
        if not all_zones:
            return []
        
        # Find overlapping zones
        clusters = []
        used_zones = set()
        
        for i, zone1 in enumerate(all_zones):
            if zone1.id in used_zones:
                continue
            
            cluster_zones = [zone1]
            used_zones.add(zone1.id)
            
            for zone2 in all_zones[i+1:]:
                if zone2.id in used_zones:
                    continue
                
                if zone1.overlaps_with(zone2):
                    cluster_zones.append(zone2)
                    used_zones.add(zone2.id)
            
            # Only create cluster if multiple zones overlap
            if len(cluster_zones) > 1:
                timeframes = list(set(z.timeframe for z in cluster_zones))
                
                # Calculate cluster score
                base_score = sum(z.strength_score for z in cluster_zones)
                overlap_bonus = 1 if len(timeframes) == 2 else 2
                cluster_score = base_score + overlap_bonus
                
                cluster = ZoneCluster(
                    id=f"cluster_{len(clusters)}",
                    zones=cluster_zones,
                    lower_bound=min(z.lower_bound for z in cluster_zones),
                    upper_bound=max(z.upper_bound for z in cluster_zones),
                    midpoint=0,  # Will be calculated in __post_init__
                    cluster_score=cluster_score,
                    timeframes=timeframes
                )
                clusters.append(cluster)
        
        logger.info(f"Built {len(clusters)} zone clusters")
        return clusters
    
    def get_nearest_support(self, price: float) -> Optional[Zone]:
        """Get nearest support zone below price"""
        all_support = []
        for timeframe in ['H4', 'H1', 'M15']:
            support_zones = [z for z in self.zones[timeframe] 
                           if z.type == ZoneType.SUPPORT and z.upper_bound < price]
            all_support.extend(support_zones)
        
        if not all_support:
            return None
        
        # Return closest by distance
        return min(all_support, key=lambda z: price - z.upper_bound)
    
    def get_nearest_resistance(self, price: float) -> Optional[Zone]:
        """Get nearest resistance zone above price"""
        all_resistance = []
        for timeframe in ['H4', 'H1', 'M15']:
            resistance_zones = [z for z in self.zones[timeframe] 
                              if z.type == ZoneType.RESISTANCE and z.lower_bound > price]
            all_resistance.extend(resistance_zones)
        
        if not all_resistance:
            return None
        
        # Return closest by distance
        return min(all_resistance, key=lambda z: z.lower_bound - price)
    
    def get_zone_context(self, price: float, max_distance: float = 100.0) -> Dict:
        """
        Get zone context around current price
        
        Returns support/resistance zones, clusters, and zone quality
        
        Args:
            price: Current price
            max_distance: Maximum distance to consider zones
        
        Returns:
            Dict with zone context
        """
        nearest_support = self.get_nearest_support(price)
        nearest_resistance = self.get_nearest_resistance(price)
        
        # Find nearby clusters
        nearby_clusters = [
            c for c in self.clusters 
            if abs(c.midpoint - price) < max_distance
        ]
        
        # Check if price is inside any zone
        inside_zones = []
        for timeframe in ['H4', 'H1', 'M15']:
            for zone in self.zones[timeframe]:
                if zone.contains(price):
                    inside_zones.append(zone)
        
        return {
            'price': price,
            'nearest_support': nearest_support,
            'nearest_resistance': nearest_resistance,
            'support_distance': nearest_support.distance_to(price) if nearest_support else None,
            'resistance_distance': nearest_resistance.distance_to(price) if nearest_resistance else None,
            'nearby_clusters': nearby_clusters,
            'inside_zones': inside_zones,
            'total_zones': sum(len(self.zones[tf]) for tf in ['H4', 'H1', 'M15']),
            'total_clusters': len(self.clusters)
        }

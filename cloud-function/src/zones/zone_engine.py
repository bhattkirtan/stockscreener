"""Zone detection and management engine."""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import List, Optional, Tuple
import pandas as pd
import numpy as np


class ZoneType(Enum):
    """Zone type classification."""
    SUPPORT = "support"
    RESISTANCE = "resistance"
    FLIP = "flip"


class ZoneState(Enum):
    """Zone lifecycle states."""
    FRESH = "fresh"
    TESTED = "tested"
    RESPECTED = "respected"
    WEAKENED = "weakened"
    BROKEN = "broken"
    FLIPPED = "flipped"
    INVALID = "invalid"


class OriginType(Enum):
    """Zone origin types."""
    SWING = "swing"
    RANGE_EDGE = "range_edge"
    BREAKOUT_RETEST = "breakout_retest"
    IMPULSE_BASE = "impulse_base"
    SESSION_HIGH_LOW = "session_high_low"
    PREVIOUS_DAY_EXTREME = "previous_day_extreme"


@dataclass
class Zone:
    """Zone schema following production spec."""
    id: str
    symbol: str
    timeframe: str
    type: ZoneType
    lower_bound: float
    upper_bound: float
    midpoint: float
    origin_type: OriginType
    created_at: datetime
    last_tested_at: Optional[datetime]
    touch_count: int
    freshness_score: float
    strength_score: float
    state: ZoneState
    
    @property
    def width(self) -> float:
        """Zone width."""
        return self.upper_bound - self.lower_bound
    
    def contains_price(self, price: float) -> bool:
        """Check if price is within zone."""
        return self.lower_bound <= price <= self.upper_bound
    
    def distance_to(self, price: float) -> float:
        """Distance from price to nearest zone boundary."""
        if self.contains_price(price):
            return 0.0
        if price < self.lower_bound:
            return self.lower_bound - price
        return price - self.upper_bound
    
    def overlaps(self, other: 'Zone') -> bool:
        """Check if this zone overlaps with another."""
        return not (self.upper_bound < other.lower_bound or self.lower_bound > other.upper_bound)


class ZoneEngine:
    """Multi-timeframe zone detection engine."""
    
    def __init__(self, symbol: str = "GOLD", config: Optional[dict] = None):
        """Initialize zone engine.
        
        Args:
            symbol: Trading symbol (GOLD or US100)
            config: Configuration dictionary
        """
        self.symbol = symbol
        self.config = config or self._default_config()
        self.zones: dict[str, List[Zone]] = {
            'H4': [],
            'H1': [],
            'M15': []
        }
        
    def _default_config(self) -> dict:
        """Default zone configuration from spec."""
        # Gold default settings
        return {
            'zone_widths': {
                'H4': 0.35,  # 0.35 * ATR(H4, 14)
                'H1': 0.25,  # 0.25 * ATR(H1, 14)
                'M15': 0.18  # 0.18 * ATR(M15, 14)
            },
            'atr_period': 14,
            'merge_threshold': 0.10,  # 0.10 * ATR for merge
            'strong_zone_threshold': 4.0,
            'max_touch_count': 5,
            'stale_bars': 100  # Bars before zone becomes stale
        }
    
    def detect_zones(self, df: pd.DataFrame, timeframe: str) -> List[Zone]:
        """Detect zones on a given timeframe.
        
        Args:
            df: OHLC dataframe with columns: timestamp, open, high, low, close
            timeframe: Timeframe string (H4, H1, M15)
            
        Returns:
            List of detected zones
        """
        if len(df) < 50:
            return []
        
        # Calculate ATR for zone width
        atr = self._calculate_atr(df, self.config['atr_period'])
        zone_half_width = self.config['zone_widths'][timeframe] * atr.iloc[-1]
        
        zones = []
        
        # Detect swing highs/lows
        swing_zones = self._detect_swing_zones(df, zone_half_width, timeframe)
        zones.extend(swing_zones)
        
        # Detect range edges
        range_zones = self._detect_range_zones(df, zone_half_width, timeframe)
        zones.extend(range_zones)
        
        # Detect session highs/lows (for intraday timeframes)
        if timeframe in ['M15', 'M5']:
            session_zones = self._detect_session_zones(df, zone_half_width, timeframe)
            zones.extend(session_zones)
        
        # Merge overlapping zones
        zones = self._merge_zones(zones, atr.iloc[-1])
        
        # Update zone states
        zones = self._update_zone_states(zones, df)
        
        return zones
    
    def _calculate_atr(self, df: pd.DataFrame, period: int = 14) -> pd.Series:
        """Calculate Average True Range."""
        high = df['high']
        low = df['low']
        close = df['close']
        
        tr1 = high - low
        tr2 = np.abs(high - close.shift(1))
        tr3 = np.abs(low - close.shift(1))
        
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(window=period).mean()
        
        return atr.fillna(tr.mean())
    
    def _detect_swing_zones(self, df: pd.DataFrame, half_width: float, timeframe: str) -> List[Zone]:
        """Detect swing high/low zones using optimized vectorized approach."""
        zones = []
        lookback = 10 if timeframe == 'M15' else 20
        
        # Limit processing to recent data for speed (last 500 bars)
        if len(df) > 500:
            df_recent = df.iloc[-500:].copy()
            offset = len(df) - 500
        else:
            df_recent = df.copy()
            offset = 0
        
        # Vectorized swing high detection using rolling max
        # A bar is a swing high if it's the max in a window of lookback*2+1
        high_rolling_max = df_recent['high'].rolling(window=lookback*2+1, center=True).max()
        is_swing_high = (df_recent['high'] == high_rolling_max) & (df_recent['high'] == df_recent['high'].shift(lookback).rolling(lookback).max().shift(-lookback+1))
        
        # Get indices of swing highs (skip first/last lookback bars)
        swing_high_indices = df_recent.index[is_swing_high].tolist()[lookback:-lookback]
        
        # Create resistance zones for swing highs (limit to top 10)
        highs_with_idx = [(idx, df_recent.loc[idx, 'high']) for idx in swing_high_indices]
        highs_with_idx.sort(key=lambda x: x[1], reverse=True)
        
        for idx, pivot in highs_with_idx[:10]:
            zone = Zone(
                id=f"{self.symbol}_{timeframe}_R_{offset+idx}",
                symbol=self.symbol,
                timeframe=timeframe,
                type=ZoneType.RESISTANCE,
                lower_bound=pivot - half_width,
                upper_bound=pivot + half_width,
                midpoint=pivot,
                origin_type=OriginType.SWING,
                created_at=df_recent.loc[idx, 'timestamp'],
                last_tested_at=None,
                touch_count=0,
                freshness_score=1.0,
                strength_score=0.0,
                state=ZoneState.FRESH
            )
            zones.append(zone)
        
        # Vectorized swing low detection
        low_rolling_min = df_recent['low'].rolling(window=lookback*2+1, center=True).min()
        is_swing_low = (df_recent['low'] == low_rolling_min) & (df_recent['low'] == df_recent['low'].shift(lookback).rolling(lookback).min().shift(-lookback+1))
        
        swing_low_indices = df_recent.index[is_swing_low].tolist()[lookback:-lookback]
        
        # Create support zones for swing lows (limit to top 10)
        lows_with_idx = [(idx, df_recent.loc[idx, 'low']) for idx in swing_low_indices]
        lows_with_idx.sort(key=lambda x: x[1])
        
        for idx, pivot in lows_with_idx[:10]:
            zone = Zone(
                id=f"{self.symbol}_{timeframe}_S_{offset+idx}",
                symbol=self.symbol,
                timeframe=timeframe,
                type=ZoneType.SUPPORT,
                lower_bound=pivot - half_width,
                upper_bound=pivot + half_width,
                midpoint=pivot,
                origin_type=OriginType.SWING,
                created_at=df_recent.loc[idx, 'timestamp'],
                last_tested_at=None,
                touch_count=0,
                freshness_score=1.0,
                strength_score=0.0,
                state=ZoneState.FRESH
            )
            zones.append(zone)
        
        return zones
    
    def _detect_range_zones(self, df: pd.DataFrame, half_width: float, timeframe: str) -> List[Zone]:
        """Detect range edge zones."""
        zones = []
        window = 50 if timeframe == 'H4' else 30
        
        if len(df) < window:
            return zones
        
        # Recent high/low as range edges
        recent_high = df['high'].iloc[-window:].max()
        recent_low = df['low'].iloc[-window:].min()
        
        # Create resistance zone at range high
        zones.append(Zone(
            id=f"{self.symbol}_{timeframe}_RangeH",
            symbol=self.symbol,
            timeframe=timeframe,
            type=ZoneType.RESISTANCE,
            lower_bound=recent_high - half_width,
            upper_bound=recent_high + half_width,
            midpoint=recent_high,
            origin_type=OriginType.RANGE_EDGE,
            created_at=df.iloc[-1]['timestamp'],
            last_tested_at=None,
            touch_count=0,
            freshness_score=1.0,
            strength_score=0.0,
            state=ZoneState.FRESH
        ))
        
        # Create support zone at range low
        zones.append(Zone(
            id=f"{self.symbol}_{timeframe}_RangeL",
            symbol=self.symbol,
            timeframe=timeframe,
            type=ZoneType.SUPPORT,
            lower_bound=recent_low - half_width,
            upper_bound=recent_low + half_width,
            midpoint=recent_low,
            origin_type=OriginType.RANGE_EDGE,
            created_at=df.iloc[-1]['timestamp'],
            last_tested_at=None,
            touch_count=0,
            freshness_score=1.0,
            strength_score=0.0,
            state=ZoneState.FRESH
        ))
        
        return zones
    
    def _detect_session_zones(self, df: pd.DataFrame, half_width: float, timeframe: str) -> List[Zone]:
        """Detect session high/low zones."""
        zones = []
        
        # Simple implementation: last 20 bars high/low
        session_window = 20
        if len(df) < session_window:
            return zones
        
        session_high = df['high'].iloc[-session_window:].max()
        session_low = df['low'].iloc[-session_window:].min()
        
        zones.append(Zone(
            id=f"{self.symbol}_{timeframe}_SessionH",
            symbol=self.symbol,
            timeframe=timeframe,
            type=ZoneType.RESISTANCE,
            lower_bound=session_high - half_width,
            upper_bound=session_high + half_width,
            midpoint=session_high,
            origin_type=OriginType.SESSION_HIGH_LOW,
            created_at=df.iloc[-1]['timestamp'],
            last_tested_at=None,
            touch_count=0,
            freshness_score=1.0,
            strength_score=0.0,
            state=ZoneState.FRESH
        ))
        
        zones.append(Zone(
            id=f"{self.symbol}_{timeframe}_SessionL",
            symbol=self.symbol,
            timeframe=timeframe,
            type=ZoneType.SUPPORT,
            lower_bound=session_low - half_width,
            upper_bound=session_low + half_width,
            midpoint=session_low,
            origin_type=OriginType.SESSION_HIGH_LOW,
            created_at=df.iloc[-1]['timestamp'],
            last_tested_at=None,
            touch_count=0,
            freshness_score=1.0,
            strength_score=0.0,
            state=ZoneState.FRESH
        ))
        
        return zones
    
    def _merge_zones(self, zones: List[Zone], atr: float) -> List[Zone]:
        """Merge overlapping zones of the same type."""
        if not zones:
            return zones
        
        merge_threshold = self.config['merge_threshold'] * atr
        merged = []
        
        # Group by type
        supports = [z for z in zones if z.type == ZoneType.SUPPORT]
        resistances = [z for z in zones if z.type == ZoneType.RESISTANCE]
        
        # Merge supports
        merged.extend(self._merge_zone_group(supports, merge_threshold))
        
        # Merge resistances
        merged.extend(self._merge_zone_group(resistances, merge_threshold))
        
        return merged
    
    def _merge_zone_group(self, zones: List[Zone], threshold: float) -> List[Zone]:
        """Merge a group of zones of the same type."""
        if not zones:
            return []
        
        # Sort by midpoint
        zones = sorted(zones, key=lambda z: z.midpoint)
        
        merged = []
        current_group = [zones[0]]
        
        for zone in zones[1:]:
            # Check if zone should merge with current group
            last_zone = current_group[-1]
            gap = zone.lower_bound - last_zone.upper_bound
            
            if gap <= threshold or zone.overlaps(last_zone):
                current_group.append(zone)
            else:
                # Finalize current group
                merged.append(self._create_merged_zone(current_group))
                current_group = [zone]
        
        # Finalize last group
        merged.append(self._create_merged_zone(current_group))
        
        return merged
    
    def _create_merged_zone(self, zones: List[Zone]) -> Zone:
        """Create a merged zone from a group of zones."""
        if len(zones) == 1:
            return zones[0]
        
        # Merge properties
        lower = min(z.lower_bound for z in zones)
        upper = max(z.upper_bound for z in zones)
        midpoint = (lower + upper) / 2
        
        # Sum touch counts
        total_touches = sum(z.touch_count for z in zones)
        
        # Average freshness
        avg_freshness = sum(z.freshness_score for z in zones) / len(zones)
        
        # Overlap bonus for merged zones
        overlap_bonus = len(zones) - 1
        
        return Zone(
            id=f"merged_{zones[0].id}",
            symbol=zones[0].symbol,
            timeframe=zones[0].timeframe,
            type=zones[0].type,
            lower_bound=lower,
            upper_bound=upper,
            midpoint=midpoint,
            origin_type=zones[0].origin_type,
            created_at=min(z.created_at for z in zones),
            last_tested_at=max((z.last_tested_at for z in zones if z.last_tested_at), default=None),
            touch_count=total_touches,
            freshness_score=avg_freshness,
            strength_score=sum(z.strength_score for z in zones) + overlap_bonus,
            state=zones[0].state
        )
    
    def _update_zone_states(self, zones: List[Zone], df: pd.DataFrame) -> List[Zone]:
        """Update zone states based on recent price action."""
        current_price = df.iloc[-1]['close']
        
        for zone in zones:
            # Check if price has tested the zone recently
            recent_bars = df.iloc[-20:]
            
            for _, bar in recent_bars.iterrows():
                if zone.contains_price(bar['low']) or zone.contains_price(bar['high']):
                    zone.touch_count += 1
                    zone.last_tested_at = bar['timestamp']
                    
                    # Update state based on reaction
                    if zone.type == ZoneType.SUPPORT:
                        if bar['close'] > zone.upper_bound:
                            zone.state = ZoneState.RESPECTED
                        elif bar['close'] < zone.lower_bound:
                            zone.state = ZoneState.BROKEN
                    else:  # RESISTANCE
                        if bar['close'] < zone.lower_bound:
                            zone.state = ZoneState.RESPECTED
                        elif bar['close'] > zone.upper_bound:
                            zone.state = ZoneState.BROKEN
            
            # Update freshness based on touch count
            if zone.touch_count > self.config['max_touch_count']:
                zone.state = ZoneState.WEAKENED
                zone.freshness_score *= 0.5
        
        return zones
    
    def find_nearest_zones(self, price: float, zone_type: Optional[ZoneType] = None, 
                          timeframes: Optional[List[str]] = None) -> List[Tuple[Zone, float]]:
        """Find nearest zones to a given price.
        
        Args:
            price: Current price
            zone_type: Filter by zone type (optional)
            timeframes: Filter by timeframes (optional)
            
        Returns:
            List of (zone, distance) tuples sorted by distance
        """
        candidates = []
        
        timeframes = timeframes or ['H4', 'H1', 'M15']
        
        for tf in timeframes:
            for zone in self.zones.get(tf, []):
                if zone_type and zone.type != zone_type:
                    continue
                
                distance = zone.distance_to(price)
                candidates.append((zone, distance))
        
        # Sort by distance
        candidates.sort(key=lambda x: x[1])
        
        return candidates
    
    def get_zone_clusters(self, price: float, max_distance: float) -> List[List[Zone]]:
        """Find clusters of overlapping zones from multiple timeframes.
        
        Args:
            price: Current price
            max_distance: Maximum distance to consider
            
        Returns:
            List of zone clusters
        """
        nearby_zones = [z for z, d in self.find_nearest_zones(price) if d <= max_distance]
        
        if not nearby_zones:
            return []
        
        # Group overlapping zones
        clusters = []
        used = set()
        
        for zone in nearby_zones:
            if zone.id in used:
                continue
            
            cluster = [zone]
            used.add(zone.id)
            
            # Find all zones that overlap with this one
            for other in nearby_zones:
                if other.id in used:
                    continue
                if zone.overlaps(other):
                    cluster.append(other)
                    used.add(other.id)
            
            if len(cluster) > 1:  # Only include actual clusters
                clusters.append(cluster)
        
        return clusters
    
    def update_zones(self, df_dict: dict[str, pd.DataFrame]):
        """Update all zones from multi-timeframe data.
        
        Args:
            df_dict: Dictionary mapping timeframe to dataframe
        """
        for tf in ['H4', 'H1', 'M15']:
            if tf in df_dict:
                self.zones[tf] = self.detect_zones(df_dict[tf], tf)

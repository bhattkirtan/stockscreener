"""Hybrid strategy combining SuperTrend trend-following with zone awareness.

This strategy:
1. Uses SuperTrend for trend direction (proven logic)
2. Uses ATR-based TP/SL (proven 0.7x2.5 winner)
3. Adds zone detection to block poor structural setups
4. Blocks longs into strong overhead resistance
5. Blocks shorts into strong support below
6. Optionally adjusts stops to zone boundaries for better placement

Key benefits:
- Keeps proven trend-following core
- Adds structural awareness
- Reduces false entries into opposing zones
- Better stop placement outside noise zones
"""

from typing import Optional, Dict, List
import pandas as pd
import numpy as np
from datetime import datetime

from ..core.strategy import SupertrendVWAPStrategy
from ..zones.zone_engine import Zone, ZoneEngine, ZoneType
from ..zones.zone_scoring import ZoneScorer


class HybridZoneSuperTrendStrategy(SupertrendVWAPStrategy):
    """Hybrid strategy: SuperTrend + Zone filtering.
    
    Inherits from SupertrendVWAPStrategy and adds zone awareness.
    """
    
    _ZONE_ONLY_KEYS = frozenset({
        'enable_zone_filter', 'enable_zone_stops', 'zone_block_distance',
        'zone_config', 'symbol', 'strategy_type',
    })

    def __init__(self, **params):
        """Initialize hybrid strategy.
        
        Args:
            **params: Strategy parameters including zone config
        """
        # Strip keys unknown to the base class before delegating
        base_params = {k: v for k, v in params.items() if k not in self._ZONE_ONLY_KEYS}
        super().__init__(**base_params)
        
        # Zone-related parameters
        self.enable_zone_filter = params.get('enable_zone_filter', True)
        self.enable_zone_stops = params.get('enable_zone_stops', False)
        self.zone_block_distance = params.get('zone_block_distance', 1.0)  # Zone widths
        
        # Initialize zone components if enabled
        if self.enable_zone_filter:
            symbol = params.get('symbol', 'GOLD')
            zone_config = params.get('zone_config', self._default_zone_config(symbol))
            
            self.zone_engine = ZoneEngine(symbol, zone_config)
            self.zone_scorer = ZoneScorer(symbol)
            
            # Cache for multi-timeframe data
            self.cached_zones: Dict[str, List[Zone]] = {}
            self.last_zone_update_bar: int = -1
    
    def _default_zone_config(self, symbol: str) -> dict:
        """Default zone configuration."""
        is_gold = symbol in ['GOLD', 'XAUUSD']
        
        return {
            'zone_widths': {
                'H4': 0.35 if is_gold else 0.30,
                'H1': 0.25 if is_gold else 0.22,
                'M15': 0.18 if is_gold else 0.16
            },
            'atr_period': 14,
            'merge_threshold': 0.10,
            'strong_zone_threshold': 4.0 if is_gold else 3.5,
            'max_touch_count': 5,
            'stale_bars': 100
        }
    
    def _resample_to_timeframe(self, df: pd.DataFrame, timeframe: str) -> pd.DataFrame:
        """Resample M5 data to higher timeframe.
        
        Args:
            df: M5 OHLC dataframe
            timeframe: Target timeframe (H4, H1, M15)
            
        Returns:
            Resampled dataframe
        """
        freq_map = {
            'H4': '4h',  # Updated from deprecated 'H'
            'H1': '1h',
            'M15': '15min'  # Updated from deprecated 'T'
        }
        
        freq = freq_map.get(timeframe, '1h')
        
        # Temporarily set timestamp as index
        df_copy = df.copy()
        df_copy.set_index('timestamp', inplace=True)
        
        # Resample OHLC
        resampled = df_copy.resample(freq).agg({
            'open': 'first',
            'high': 'max',
            'low': 'min',
            'close': 'last'
        }).dropna()
        
        # Reset index
        resampled.reset_index(inplace=True)
        
        return resampled
    
    def _update_zones(self, df: pd.DataFrame, current_bar: int):
        """Update zone cache if needed.
        
        Args:
            df: Full M5 dataframe
            current_bar: Current bar index
        """
        # Update every 15 bars (75 minutes) to avoid overhead
        if current_bar - self.last_zone_update_bar < 15:
            return
        
        self.last_zone_update_bar = current_bar
        
        # Build historical df up to current bar (no future leakage)
        df_view = df.iloc[:current_bar+1].copy()
        
        # Resample to higher timeframes
        df_h4  = self._resample_to_timeframe(df_view, 'H4')
        df_h1  = self._resample_to_timeframe(df_view, 'H1')
        df_m15 = self._resample_to_timeframe(df_view, 'M15')
        
        threshold = self.zone_scorer.strong_thresholds.get(
            self.zone_scorer.symbol, 4.0
        )

        self.cached_zones = {}

        for tf, df_tf in [('H4', df_h4), ('H1', df_h1), ('M15', df_m15)]:
            if len(df_tf) < 50:
                continue
            raw_zones = self.zone_engine.detect_zones(df_tf, tf)
            # Score each zone and keep only those that meet the strong threshold
            scored = sorted(
                [(z, self.zone_scorer.score_zone(z, df_tf)) for z in raw_zones],
                key=lambda x: x[1],
                reverse=True,
            )
            # Store only Zone objects (filter out weak zones, cap at 10)
            self.cached_zones[tf] = [z for z, s in scored[:10] if s >= threshold]
    
    def _find_nearest_resistance(self, price: float) -> Optional[Zone]:
        """Find nearest resistance zone above price.
        
        Args:
            price: Current price
            
        Returns:
            Nearest resistance zone or None
        """
        nearest = None
        min_distance = float('inf')
        
        for timeframe in ['H4', 'H1', 'M15']:
            zones = self.cached_zones.get(timeframe, [])
            
            for zone in zones:
                # Check if zone is resistance above price
                if zone.type in [ZoneType.RESISTANCE, ZoneType.FLIP]:
                    if zone.lower_bound > price:
                        distance = zone.lower_bound - price
                        if distance < min_distance:
                            min_distance = distance
                            nearest = zone
        
        return nearest
    
    def _find_nearest_support(self, price: float) -> Optional[Zone]:
        """Find nearest support zone below price.
        
        Args:
            price: Current price
            
        Returns:
            Nearest support zone or None
        """
        nearest = None
        min_distance = float('inf')
        
        for timeframe in ['H4', 'H1', 'M15']:
            zones = self.cached_zones.get(timeframe, [])
            
            for zone in zones:
                # Check if zone is support below price
                if zone.type in [ZoneType.SUPPORT, ZoneType.FLIP]:
                    if zone.upper_bound < price:
                        distance = price - zone.upper_bound
                        if distance < min_distance:
                            min_distance = distance
                            nearest = zone
        
        return nearest
    
    def _should_block_long(self, price: float, atr: float) -> tuple[bool, str]:
        """Check if long should be blocked due to zone structure.
        
        Args:
            price: Current price
            atr: Current ATR value
            
        Returns:
            (should_block, reason)
        """
        if not self.enable_zone_filter or not self.cached_zones:
            return False, ""
        
        # Find nearest resistance
        resistance = self._find_nearest_resistance(price)
        
        if resistance is None:
            return False, ""
        
        # Calculate distance to resistance
        distance = resistance.lower_bound - price
        zone_width = resistance.upper_bound - resistance.lower_bound
        
        # Check if resistance is too close (all zones in cache are already strong)
        if distance < self.zone_block_distance * zone_width:
            return True, f"strong {resistance.timeframe} resistance {distance:.1f} pips overhead"
        
        return False, ""
    
    def _should_block_short(self, price: float, atr: float) -> tuple[bool, str]:
        """Check if short should be blocked due to zone structure.
        
        Args:
            price: Current price
            atr: Current ATR value
            
        Returns:
            (should_block, reason)
        """
        if not self.enable_zone_filter or not self.cached_zones:
            return False, ""
        
        # Find nearest support
        support = self._find_nearest_support(price)
        
        if support is None:
            return False, ""
        
        # Calculate distance to support
        distance = price - support.upper_bound
        zone_width = support.upper_bound - support.lower_bound
        
        # Check if support is too close (all zones in cache are already strong)
        if distance < self.zone_block_distance * zone_width:
            return True, f"strong {support.timeframe} support {distance:.1f} pips below"
        
        return False, ""
    
    def _adjust_long_stop_to_zone(self, price: float, initial_stop: float, 
                                   atr: float) -> tuple[float, str]:
        """Adjust long stop to zone boundary if beneficial.
        
        Args:
            price: Entry price
            initial_stop: ATR-based stop
            atr: Current ATR
            
        Returns:
            (adjusted_stop, reason)
        """
        if not self.enable_zone_stops or not self.cached_zones:
            return initial_stop, ""
        
        # Find support zones near initial stop
        for timeframe in ['M15', 'H1', 'H4']:
            zones = self.cached_zones.get(timeframe, [])
            
            for zone in zones:
                if zone.type not in [ZoneType.SUPPORT, ZoneType.FLIP]:
                    continue
                
                # Check if zone is near initial stop
                if abs(zone.lower_bound - initial_stop) < 0.5 * atr:
                    # Place stop below zone with buffer
                    adjusted_stop = zone.lower_bound - 0.20 * atr
                    
                    # Only use if it doesn't widen stop too much
                    if adjusted_stop > initial_stop - 0.3 * atr:
                        return adjusted_stop, f"adjusted to {timeframe} zone boundary"
        
        return initial_stop, ""
    
    def _adjust_short_stop_to_zone(self, price: float, initial_stop: float, 
                                    atr: float) -> tuple[float, str]:
        """Adjust short stop to zone boundary if beneficial.
        
        Args:
            price: Entry price
            initial_stop: ATR-based stop
            atr: Current ATR
            
        Returns:
            (adjusted_stop, reason)
        """
        if not self.enable_zone_stops or not self.cached_zones:
            return initial_stop, ""
        
        # Find resistance zones near initial stop
        for timeframe in ['M15', 'H1', 'H4']:
            zones = self.cached_zones.get(timeframe, [])
            
            for zone in zones:
                if zone.type not in [ZoneType.RESISTANCE, ZoneType.FLIP]:
                    continue
                
                # Check if zone is near initial stop
                if abs(zone.upper_bound - initial_stop) < 0.5 * atr:
                    # Place stop above zone with buffer
                    adjusted_stop = zone.upper_bound + 0.20 * atr
                    
                    # Only use if it doesn't widen stop too much
                    if adjusted_stop < initial_stop + 0.3 * atr:
                        return adjusted_stop, f"adjusted to {timeframe} zone boundary"
        
        return initial_stop, ""
    
    def _on_data(self, df: pd.DataFrame, i: int) -> Optional[Dict]:
        """Override parent _on_data to add zone filtering.
        
        Args:
            df: Full dataframe
            i: Current bar index
            
        Returns:
            Signal dict or None
        """
        # Update zones periodically
        if self.enable_zone_filter and i >= 500:
            self._update_zones(df, i)
        
        # Get SuperTrend signal
        signal = super()._on_data(df, i)
        
        if signal is None:
            return None
        
        # Apply zone filter
        if self.enable_zone_filter and self.cached_zones:
            current_bar = df.iloc[i]
            price = current_bar['close']
            atr = self._calculate_atr(df.iloc[max(0, i-14):i+1])
            
            if signal['direction'] == 'long':
                should_block, reason = self._should_block_long(price, atr)
                if should_block:
                    self.log(f"BLOCKED LONG: {reason}")
                    return None
                
                # Optionally adjust stop to zone
                adjusted_stop, stop_reason = self._adjust_long_stop_to_zone(
                    price, signal['stop_loss'], atr
                )
                if stop_reason:
                    self.log(f"STOP ADJUSTED: {stop_reason}")
                    signal['stop_loss'] = adjusted_stop
            
            elif signal['direction'] == 'short':
                should_block, reason = self._should_block_short(price, atr)
                if should_block:
                    self.log(f"BLOCKED SHORT: {reason}")
                    return None
                
                # Optionally adjust stop to zone
                adjusted_stop, stop_reason = self._adjust_short_stop_to_zone(
                    price, signal['stop_loss'], atr
                )
                if stop_reason:
                    self.log(f"STOP ADJUSTED: {stop_reason}")
                    signal['stop_loss'] = adjusted_stop
        
        return signal
    
    def _calculate_atr(self, df: pd.DataFrame, period: int = 14) -> float:
        """Calculate ATR for zone calculations.
        
        Args:
            df: OHLC dataframe
            period: ATR period
            
        Returns:
            ATR value
        """
        high = df['high']
        low = df['low']
        close = df['close']
        
        tr1 = high - low
        tr2 = abs(high - close.shift())
        tr3 = abs(low - close.shift())
        
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(window=period).mean()
        
        return atr.iloc[-1] if len(atr) > 0 else 0.0

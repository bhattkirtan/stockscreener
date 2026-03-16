"""
Zone-Based Intraday Trading Strategy

Integrates zone engine, bias engine, trigger engine, and trade scorer
into a unified strategy for Gold/US100 intraday trading.

Reference: strategy.md Sections 9-17
"""

import pandas as pd
import numpy as np
from typing import Optional, Dict, List, Tuple
from dataclasses import dataclass
from datetime import datetime, time
import logging

from .zone_engine import Zone, ZoneCluster, ZoneEngine
from .bias_engine import BiasEngine, BiasContext, BiasState
from .trigger_engine import TriggerEngine, TriggerContext, TriggerType
from .trade_scorer import TradeScorer, TradeScore

logger = logging.getLogger(__name__)


@dataclass
class TradingSignal:
    """
    Complete trading signal with all context
    """
    timestamp: pd.Timestamp
    direction: str  # 'long' or 'short'
    entry_price: float
    stop_price: float
    target_price: float
    
    # Score breakdown
    trade_score: TradeScore
    
    # Context
    zone: Zone
    bias_context: BiasContext
    trigger_context: TriggerContext
    cluster: Optional[ZoneCluster] = None
    
    # Metadata
    instrument: str = "GOLD"
    timeframe: str = "M5"
    
    def to_dict(self) -> Dict:
        """Convert to dictionary"""
        return {
            'timestamp': self.timestamp.isoformat(),
            'direction': self.direction,
            'entry_price': self.entry_price,
            'stop_price': self.stop_price,
            'target_price': self.target_price,
            'trade_score': self.trade_score.to_dict(),
            'zone': {
                'upper_bound': self.zone.upper_bound,
                'lower_bound': self.zone.lower_bound,
                'strength_score': self.zone.strength_score,
                'timeframe': self.zone.timeframe,
                'state': self.zone.state.value
            },
            'bias_context': self.bias_context.to_dict(),
            'trigger_context': self.trigger_context.to_dict(),
            'instrument': self.instrument,
            'timeframe': self.timeframe
        }


class ZoneBasedIntradayStrategy:
    """
    Zone-based intraday trading strategy for Gold/US100
    
    Strategy flow from strategy.md Section 8:
    1. Build zones from H4/H1/M15 swing points
    2. Detect bias from H4/H1 EMA crossovers
    3. Wait for M5 trigger at zone boundary
    4. Score trade setup (0-100)
    5. Execute if score >= 70
    
    Position sizing from strategy.md Section 16:
    - Risk 1% of capital per trade
    - Stop loss at zone boundary
    - Target at next zone or 2:1 R:R minimum
    """
    
    def __init__(
        self,
        # Zone parameters (strategy.md Section 9)
        zone_width_multipliers: Dict[str, float] = None,
        strong_zone_threshold: float = 4.0,
        
        # Bias parameters (strategy.md Section 11)
        h4_fast_ema: int = 20,
        h4_slow_ema: int = 50,
        h1_fast_ema: int = 20,
        h1_slow_ema: int = 50,
        
        # Trigger parameters (strategy.md Section 12)
        trigger_strong_close: float = 0.7,
        trigger_volume_surge: float = 1.5,
        
        # Scoring parameters (strategy.md Section 17)
        min_passing_score: int = 70,
        min_risk_reward: float = 2.0,
        
        # Risk parameters (strategy.md Section 16)
        risk_per_trade_pct: float = 0.01,
        max_spread_pct: float = 0.02
    ):
        """
        Initialize zone-based intraday strategy
        
        Args:
            zone_width_multipliers: ATR multipliers for each timeframe
            strong_zone_threshold: Min strength for "strong" zone
            h4_fast_ema: H4 fast EMA period
            h4_slow_ema: H4 slow EMA period
            h1_fast_ema: H1 fast EMA period
            h1_slow_ema: H1 slow EMA period
            trigger_strong_close: Close position threshold for triggers
            trigger_volume_surge: Volume multiplier for surge
            min_passing_score: Minimum score to execute (70)
            min_risk_reward: Minimum R:R ratio (2.0)
            risk_per_trade_pct: Risk per trade (0.01 = 1%)
            max_spread_pct: Max spread as % of ATR
        """
        # Default zone widths for Gold (strategy.md Table 9.1)
        if zone_width_multipliers is None:
            zone_width_multipliers = {
                'H4': 0.35,
                'H1': 0.25,
                'M15': 0.18
            }
        
        # Initialize engines
        self.zone_engine = ZoneEngine(
            zone_width_multipliers=zone_width_multipliers,
            strong_zone_threshold=strong_zone_threshold
        )
        
        self.bias_engine = BiasEngine(
            h4_fast_ema=h4_fast_ema,
            h4_slow_ema=h4_slow_ema,
            h1_fast_ema=h1_fast_ema,
            h1_slow_ema=h1_slow_ema
        )
        
        self.trigger_engine = TriggerEngine(
            strong_close_threshold=trigger_strong_close,
            volume_surge_multiplier=trigger_volume_surge,
            impulsive_move_atr_fraction=0.5
        )
        
        self.trade_scorer = TradeScorer(
            bias_engine=self.bias_engine,
            trigger_engine=self.trigger_engine,
            min_passing_score=min_passing_score,
            min_risk_reward=min_risk_reward,
            max_spread_pct=max_spread_pct
        )
        
        # Strategy parameters
        self.risk_per_trade_pct = risk_per_trade_pct
        self.min_passing_score = min_passing_score
        
        # State
        self.zones: Dict[str, List[Zone]] = {}  # zones by timeframe
        self.clusters: List[ZoneCluster] = []
        self.last_bias_context: Optional[BiasContext] = None
        self.last_trigger_context: Optional[TriggerContext] = None
    
    def update_zones(
        self,
        df_h4: pd.DataFrame,
        df_h1: pd.DataFrame,
        df_m15: pd.DataFrame
    ):
        """
        Update all zones from H4/H1/M15 data
        
        Args:
            df_h4: H4 OHLC data
            df_h1: H1 OHLC data
            df_m15: M15 OHLC data
        """
        logger.debug("Updating zones from H4/H1/M15 data")
        
        # Build zones for each timeframe
        self.zones = {
            'H4': self.zone_engine.build_zones(df_h4, 'H4'),
            'H1': self.zone_engine.build_zones(df_h1, 'H1'),
            'M15': self.zone_engine.build_zones(df_m15, 'M15')
        }
        
        # Build clusters
        all_zones = []
        for zones in self.zones.values():
            all_zones.extend(zones)
        
        self.clusters = self.zone_engine.build_clusters(all_zones)
        
        logger.info(
            f"Updated zones: "
            f"H4={len(self.zones.get('H4', []))}, "
            f"H1={len(self.zones.get('H1', []))}, "
            f"M15={len(self.zones.get('M15', []))}, "
            f"Clusters={len(self.clusters)}"
        )
    
    def update_bias(
        self,
        df_h4: pd.DataFrame,
        df_h1: pd.DataFrame
    ):
        """
        Update directional bias from H4/H1
        
        Args:
            df_h4: H4 OHLC data
            df_h1: H1 OHLC data
        """
        self.last_bias_context = self.bias_engine.detect_bias(df_h4, df_h1)
        
        logger.info(
            f"Updated bias: {self.last_bias_context.bias.value} "
            f"(confidence: {self.last_bias_context.confidence:.2f})"
        )
    
    def update_trigger(self, df_m5: pd.DataFrame):
        """
        Update M5 trigger detection
        
        Args:
            df_m5: M5 OHLC data
        """
        self.last_trigger_context = self.trigger_engine.detect_trigger(df_m5)
        
        if self.last_trigger_context.trigger_type != TriggerType.NO_TRIGGER:
            logger.info(
                f"Updated trigger: {self.last_trigger_context.trigger_type.value} "
                f"(quality: {self.last_trigger_context.quality_score:.1f}/15)"
            )
    
    def find_nearest_zone(
        self,
        price: float,
        direction: str,
        max_distance_atr: float = 2.0,
        current_atr: float = 1.0
    ) -> Optional[Tuple[Zone, Optional[ZoneCluster]]]:
        """
        Find nearest zone in direction of trade
        
        Args:
            price: Current price
            direction: 'long' or 'short'
            max_distance_atr: Max distance to zone (in ATR)
            current_atr: Current ATR
        
        Returns:
            Tuple of (zone, cluster) if found, else None
        """
        max_distance = max_distance_atr * current_atr
        
        # Combine all zones
        all_zones = []
        for zones in self.zones.values():
            all_zones.extend(zones)
        
        # Filter by direction and zone type
        from .zone_engine import ZoneType
        if direction == 'long':
            # Support zones at or just below current price
            candidates = [
                z for z in all_zones
                if z.type == ZoneType.SUPPORT
                and z.upper_bound >= price - max_distance
                and z.lower_bound <= price
            ]
        else:
            # Resistance zones at or just above current price
            candidates = [
                z for z in all_zones
                if z.type == ZoneType.RESISTANCE
                and z.lower_bound <= price + max_distance
                and z.upper_bound >= price
            ]
        
        if not candidates:
            return None
        
        # Sort by strength score
        candidates.sort(key=lambda z: z.strength_score, reverse=True)
        best_zone = candidates[0]
        
        # Find cluster containing this zone
        cluster = None
        for c in self.clusters:
            if best_zone in c.zones:
                cluster = c
                break
        
        return best_zone, cluster
    
    def calculate_stop_and_target(
        self,
        entry_price: float,
        zone: Zone,
        direction: str,
        min_rr: float = 2.0
    ) -> Tuple[float, float]:
        """
        Calculate stop loss and take profit levels
        
        From strategy.md Section 15:
        - Stop: Just beyond zone boundary
        - Target: Next zone or min 2:1 R:R
        
        Args:
            entry_price: Entry price
            zone: Entry zone
            direction: 'long' or 'short'
            min_rr: Minimum R:R ratio
        
        Returns:
            Tuple of (stop_price, target_price)
        """
        if direction == 'long':
            # Stop below zone
            stop_price = zone.lower_bound - (zone.upper_bound - zone.lower_bound) * 0.1
            
            # Target above entry
            min_target = entry_price + (entry_price - stop_price) * min_rr
            target_price = min_target
            
        else:  # short
            # Stop above zone
            stop_price = zone.upper_bound + (zone.upper_bound - zone.lower_bound) * 0.1
            
            # Target below entry
            min_target = entry_price - (stop_price - entry_price) * min_rr
            target_price = min_target
        
        return stop_price, target_price
    
    def generate_signal(
        self,
        df_h4: pd.DataFrame,
        df_h1: pd.DataFrame,
        df_m15: pd.DataFrame,
        df_m5: pd.DataFrame,
        current_atr: float,
        avg_atr: float,
        spread: float,
        account_balance: float = 10000.0,
        minutes_to_event: Optional[int] = None
    ) -> Optional[TradingSignal]:
        """
        Generate trading signal from complete context
        
        Strategy flow:
        1. Update zones, bias, and trigger
        2. Check if trigger is valid
        3. Find nearest zone in trigger direction
        4. Calculate stop/target
        5. Score the trade
        6. Return signal if score >= 70
        
        Args:
            df_h4: H4 OHLC data
            df_h1: H1 OHLC data
            df_m15: M15 OHLC data
            df_m5: M5 OHLC data
            current_atr: Current ATR
            avg_atr: Average ATR
            spread: Current bid-ask spread
            account_balance: Account balance for position sizing
            minutes_to_event: Minutes to next high-impact event
        
        Returns:
            TradingSignal if valid setup, else None
        """
        # Update all components
        self.update_zones(df_h4, df_h1, df_m15)
        self.update_bias(df_h4, df_h1)
        self.update_trigger(df_m5)
        
        # Check if we have a valid trigger
        if self.last_trigger_context.trigger_type == TriggerType.NO_TRIGGER:
            return None
        
        # Determine direction from trigger
        if self.trigger_engine.is_valid_long_trigger(self.last_trigger_context):
            direction = 'long'
        elif self.trigger_engine.is_valid_short_trigger(self.last_trigger_context):
            direction = 'short'
        else:
            return None
        
        # Find nearest zone
        current_price = df_m5['close'].iloc[-1]
        zone_result = self.find_nearest_zone(
            current_price, direction, max_distance_atr=2.0, current_atr=current_atr
        )
        
        if zone_result is None:
            logger.debug(f"No suitable zone found for {direction} at {current_price:.2f}")
            return None
        
        zone, cluster = zone_result
        
        # Calculate stop and target
        entry_price = self.last_trigger_context.trigger_price
        stop_price, target_price = self.calculate_stop_and_target(
            entry_price, zone, direction, min_rr=2.0
        )
        
        # Score the trade
        trade_score = self.trade_scorer.calculate_trade_score(
            bias_context=self.last_bias_context,
            zone=zone,
            trigger_context=self.last_trigger_context,
            direction=direction,
            entry_price=entry_price,
            stop_price=stop_price,
            target_price=target_price,
            timestamp=df_m5.index[-1],
            current_atr=current_atr,
            avg_atr=avg_atr,
            spread=spread,
            cluster=cluster,
            minutes_to_event=minutes_to_event
        )
        
        # Check if trade passes threshold
        if trade_score.rejected:
            logger.info(
                f"Trade rejected: {trade_score.rejection_reason}"
            )
            return None
        
        if not trade_score.passes_threshold(self.min_passing_score):
            logger.info(
                f"Trade filtered: score {trade_score.total_score} < {self.min_passing_score}"
            )
            return None
        
        # Create signal
        signal = TradingSignal(
            timestamp=df_m5.index[-1],
            direction=direction,
            entry_price=entry_price,
            stop_price=stop_price,
            target_price=target_price,
            trade_score=trade_score,
            zone=zone,
            bias_context=self.last_bias_context,
            trigger_context=self.last_trigger_context,
            cluster=cluster
        )
        
        logger.info(
            f"SIGNAL GENERATED: {direction.upper()} at {entry_price:.2f} "
            f"(score: {trade_score.total_score}/100, "
            f"stop: {stop_price:.2f}, target: {target_price:.2f})"
        )
        
        return signal
    
    def calculate_position_size(
        self,
        signal: TradingSignal,
        account_balance: float
    ) -> float:
        """
        Calculate position size based on risk
        
        From strategy.md Section 16:
        - Risk 1% of capital per trade
        - Position size = (Account * Risk%) / Stop distance
        
        Args:
            signal: Trading signal
            account_balance: Account balance
        
        Returns:
            Position size (units)
        """
        risk_amount = account_balance * self.risk_per_trade_pct
        stop_distance = abs(signal.entry_price - signal.stop_price)
        
        if stop_distance == 0:
            return 0.0
        
        position_size = risk_amount / stop_distance
        
        return position_size

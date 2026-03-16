"""
Trade Scoring System for Zone-Based Intraday Trading Strategy

Combines all signal components into a unified 0-100 score.

Reference: strategy.md Section 17 (Trade Scoring Model)
"""

import pandas as pd
import numpy as np
from typing import Optional, Dict, List, Tuple
from dataclasses import dataclass
from datetime import time
import logging

from .zone_engine import Zone, ZoneCluster
from .bias_engine import BiasEngine, BiasContext
from .trigger_engine import TriggerEngine, TriggerContext

logger = logging.getLogger(__name__)


@dataclass
class TradeScore:
    """
    Complete trade score breakdown
    
    Total: 0-100 points
    Components from strategy.md Section 17.2:
    1. Bias alignment: 20 points
    2. Zone quality: 20 points
    3. Trigger quality: 15 points
    4. Room to target: 15 points
    5. Volatility regime: 10 points
    6. Session timing: 10 points
    7. Spread/conditions: 5 points
    8. News-safety buffer: 5 points
    """
    total_score: int
    
    # Component scores
    bias_score: int = 0  # 0 to 20
    zone_score: int = 0  # 0 to 20
    trigger_score: int = 0  # 0 to 15
    room_score: int = 0  # 0 to 15
    volatility_score: int = 0  # 0 to 10
    session_score: int = 0  # 0 to 10
    spread_score: int = 0  # 0 to 5
    news_safety_score: int = 0  # 0 to 5
    
    # Context
    timestamp: pd.Timestamp = None
    direction: str = None  # 'long' or 'short'
    entry_price: float = 0.0
    stop_price: float = 0.0
    target_price: float = 0.0
    
    # Rejection reasons
    rejected: bool = False
    rejection_reason: str = None
    
    def __post_init__(self):
        """Validate score components"""
        if self.total_score < 0 or self.total_score > 100:
            logger.warning(f"Invalid total score: {self.total_score}")
    
    def passes_threshold(self, min_score: int = 70) -> bool:
        """
        Check if trade passes minimum score threshold
        
        From strategy.md Section 17.3:
        - Capital preservation tier (0-50): No trade
        - Risk assessment tier (51-69): No trade
        - Execution tier (70-100): Trade eligible
        
        Args:
            min_score: Minimum score to pass (default 70)
        
        Returns:
            True if score >= min_score
        """
        return self.total_score >= min_score
    
    def to_dict(self) -> Dict:
        """Convert to dictionary"""
        return {
            'total_score': self.total_score,
            'bias_score': self.bias_score,
            'zone_score': self.zone_score,
            'trigger_score': self.trigger_score,
            'room_score': self.room_score,
            'volatility_score': self.volatility_score,
            'session_score': self.session_score,
            'spread_score': self.spread_score,
            'news_safety_score': self.news_safety_score,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
            'direction': self.direction,
            'entry_price': self.entry_price,
            'stop_price': self.stop_price,
            'target_price': self.target_price,
            'rejected': self.rejected,
            'rejection_reason': self.rejection_reason
        }


class TradeScorer:
    """
    Scores trade setups by combining all signal components
    
    Implements strategy.md Section 17 scoring model:
    - Component 1: Bias alignment (20 pts)
    - Component 2: Zone quality (20 pts)
    - Component 3: Trigger quality (15 pts)
    - Component 4: Room to target (15 pts)
    - Component 5: Volatility regime (10 pts)
    - Component 6: Session timing (10 pts)
    - Component 7: Spread/conditions (5 pts)
    - Component 8: News-safety buffer (5 pts)
    
    Minimum passing score: 70/100
    """
    
    def __init__(
        self,
        bias_engine: BiasEngine,
        trigger_engine: TriggerEngine,
        min_passing_score: int = 70,
        min_risk_reward: float = 2.0,
        max_spread_pct: float = 0.02  # 2% of ATR
    ):
        """
        Initialize trade scorer
        
        Args:
            bias_engine: Bias detection engine
            trigger_engine: Trigger detection engine
            min_passing_score: Minimum score to execute (70)
            min_risk_reward: Minimum R:R ratio (2.0)
            max_spread_pct: Max spread as % of ATR (0.02)
        """
        self.bias_engine = bias_engine
        self.trigger_engine = trigger_engine
        self.min_passing_score = min_passing_score
        self.min_risk_reward = min_risk_reward
        self.max_spread_pct = max_spread_pct
        
        # London/NY session times (UTC)
        self.london_open = time(8, 0)
        self.london_close = time(16, 0)
        self.ny_open = time(13, 0)
        self.ny_close = time(21, 0)
    
    def score_bias_alignment(
        self,
        bias_context: BiasContext,
        direction: str
    ) -> int:
        """
        Score bias alignment (0 to 20 points)
        
        From strategy.md Section 17.2:
        - Aligned with bias: +20
        - Counter-trend: -10 (rejection)
        - Neutral bias: 0 (no trade)
        
        Args:
            bias_context: Current bias state
            direction: 'long' or 'short'
        
        Returns:
            Bias score (0 to 20)
        """
        return self.bias_engine.get_bias_score_adjustment(
            bias_context, direction
        )
    
    def score_zone_quality(
        self,
        zone: Zone,
        cluster: Optional[ZoneCluster] = None
    ) -> int:
        """
        Score zone quality (0 to 20 points)
        
        From strategy.md Section 17.2:
        - Zone strength score (4.0+ for Gold = strong)
        - Timeframe overlap (H4+H1+M15 cluster)
        - Fresh zone (no recent touches)
        - Round number alignment
        
        Mapping zone.strength_score to 0-20:
        - 6.0+: 20 points
        - 5.0-5.9: 17 points
        - 4.0-4.9: 14 points (strong threshold)
        - 3.0-3.9: 10 points
        - 2.0-2.9: 6 points
        - <2.0: 3 points
        
        Args:
            zone: Target zone
            cluster: Zone cluster (if zone is in cluster)
        
        Returns:
            Zone quality score (0 to 20)
        """
        strength = zone.strength_score
        
        # Base score from strength
        if strength >= 6.0:
            score = 20
        elif strength >= 5.0:
            score = 17
        elif strength >= 4.0:
            score = 14  # Strong zone threshold
        elif strength >= 3.0:
            score = 10
        elif strength >= 2.0:
            score = 6
        else:
            score = 3
        
        # Bonus for cluster membership
        if cluster and len(cluster.zones) >= 3:
            score = min(score + 2, 20)  # +2 for 3+ timeframe overlap
        
        # Penalty for stale zones (many touches)
        if zone.touch_count > 5:
            score -= 2
        
        return max(0, min(score, 20))
    
    def score_trigger_quality(
        self,
        trigger_context: TriggerContext,
        direction: str
    ) -> int:
        """
        Score trigger quality (0 to 15 points)
        
        From strategy.md Section 17.2:
        - Trigger quality directly from trigger_engine
        
        Args:
            trigger_context: Current trigger
            direction: 'long' or 'short'
        
        Returns:
            Trigger score (0 to 15)
        """
        return self.trigger_engine.get_trigger_score_adjustment(
            trigger_context, direction
        )
    
    def score_room_to_target(
        self,
        entry_price: float,
        stop_price: float,
        target_price: float
    ) -> Tuple[int, bool]:
        """
        Score room to target (0 to 15 points)
        
        From strategy.md Section 17.2:
        - Check R:R ratio (target distance / stop distance)
        - Minimum 2:1 R:R required
        - Better R:R = higher score
        
        Scoring:
        - 3.0+ R:R: 15 points
        - 2.5-2.9 R:R: 12 points
        - 2.0-2.4 R:R: 9 points
        - <2.0 R:R: 0 points (reject trade)
        
        Args:
            entry_price: Entry price
            stop_price: Stop loss price
            target_price: Target price
        
        Returns:
            Tuple of (score, valid)
        """
        stop_distance = abs(entry_price - stop_price)
        target_distance = abs(entry_price - target_price)
        
        if stop_distance == 0:
            return 0, False
        
        risk_reward = target_distance / stop_distance
        
        if risk_reward >= 3.0:
            return 15, True
        elif risk_reward >= 2.5:
            return 12, True
        elif risk_reward >= 2.0:
            return 9, True
        else:
            return 0, False  # Reject
    
    def score_volatility_regime(
        self,
        current_atr: float,
        avg_atr: float
    ) -> int:
        """
        Score volatility regime (0 to 10 points)
        
        From strategy.md Section 17.2:
        - Normal volatility (0.9-1.2x avg): +10
        - Elevated volatility (1.2-1.5x avg): +7
        - High volatility (>1.5x avg): +3 (wider stops)
        - Low volatility (<0.9x avg): +5 (compressed ranges)
        
        Args:
            current_atr: Current ATR
            avg_atr: Average ATR
        
        Returns:
            Volatility score (0 to 10)
        """
        if avg_atr == 0:
            return 5  # Neutral if no ATR data
        
        ratio = current_atr / avg_atr
        
        if 0.9 <= ratio <= 1.2:
            return 10  # Normal regime
        elif 1.2 < ratio <= 1.5:
            return 7  # Elevated
        elif ratio > 1.5:
            return 3  # High volatility
        else:
            return 5  # Low volatility
    
    def score_session_timing(
        self,
        timestamp: pd.Timestamp
    ) -> int:
        """
        Score session timing (0 to 10 points)
        
        From strategy.md Section 17.2:
        - London/NY overlap (13:00-16:00 UTC): +10
        - London session (08:00-16:00 UTC): +7
        - NY session (13:00-21:00 UTC): +7
        - Asian session: +3
        
        Args:
            timestamp: Entry timestamp
        
        Returns:
            Session score (0 to 10)
        """
        entry_time = timestamp.time()
        
        # London/NY overlap
        if self.ny_open <= entry_time < self.london_close:
            return 10
        
        # London session
        elif self.london_open <= entry_time < self.london_close:
            return 7
        
        # NY session
        elif self.ny_open <= entry_time < self.ny_close:
            return 7
        
        # Asian session
        else:
            return 3
    
    def score_spread_conditions(
        self,
        spread: float,
        atr: float
    ) -> int:
        """
        Score spread/market conditions (0 to 5 points)
        
        From strategy.md Section 17.2:
        - Normal spread (<2% ATR): +5
        - Elevated spread (2-4% ATR): +2
        - Wide spread (>4% ATR): 0 (reject)
        
        Args:
            spread: Current bid-ask spread
            atr: Current ATR
        
        Returns:
            Spread score (0 to 5)
        """
        if atr == 0:
            return 3  # Neutral if no ATR
        
        spread_pct = spread / atr
        
        if spread_pct < 0.02:
            return 5  # Normal
        elif spread_pct < 0.04:
            return 2  # Elevated
        else:
            return 0  # Too wide
    
    def score_news_safety(
        self,
        minutes_to_event: Optional[int] = None
    ) -> int:
        """
        Score news safety buffer (0 to 5 points)
        
        From strategy.md Section 17.2:
        - No high-impact event within 60 min: +5
        - Event 30-60 min away: +2
        - Event <30 min away: 0 (reject)
        
        Args:
            minutes_to_event: Minutes until next high-impact event
        
        Returns:
            News safety score (0 to 5)
        """
        if minutes_to_event is None or minutes_to_event > 60:
            return 5  # Safe
        elif minutes_to_event >= 30:
            return 2  # Marginal
        else:
            return 0  # Too close
    
    def calculate_trade_score(
        self,
        # Required inputs
        bias_context: BiasContext,
        zone: Zone,
        trigger_context: TriggerContext,
        direction: str,
        entry_price: float,
        stop_price: float,
        target_price: float,
        timestamp: pd.Timestamp,
        
        # Market conditions
        current_atr: float,
        avg_atr: float,
        spread: float,
        
        # Optional
        cluster: Optional[ZoneCluster] = None,
        minutes_to_event: Optional[int] = None
    ) -> TradeScore:
        """
        Calculate complete trade score
        
        Args:
            bias_context: Current bias state
            zone: Target zone
            trigger_context: Current trigger
            direction: 'long' or 'short'
            entry_price: Entry price
            stop_price: Stop loss price
            target_price: Target price
            timestamp: Entry timestamp
            current_atr: Current ATR
            avg_atr: Average ATR
            spread: Current bid-ask spread
            cluster: Zone cluster (optional)
            minutes_to_event: Minutes to next event (optional)
        
        Returns:
            TradeScore with breakdown
        """
        # Score each component
        bias_score = self.score_bias_alignment(bias_context, direction)
        zone_score = self.score_zone_quality(zone, cluster)
        trigger_score = self.score_trigger_quality(trigger_context, direction)
        room_score, room_valid = self.score_room_to_target(
            entry_price, stop_price, target_price
        )
        volatility_score = self.score_volatility_regime(current_atr, avg_atr)
        session_score = self.score_session_timing(timestamp)
        spread_score = self.score_spread_conditions(spread, current_atr)
        news_safety_score = self.score_news_safety(minutes_to_event)
        
        # Check hard rejections
        rejected = False
        rejection_reason = None
        
        if bias_score < 0:
            rejected = True
            rejection_reason = "Counter-trend trade (bias)"
        elif not room_valid:
            rejected = True
            rejection_reason = f"Insufficient R:R ratio (<{self.min_risk_reward})"
        elif spread_score == 0:
            rejected = True
            rejection_reason = "Spread too wide"
        elif news_safety_score == 0:
            rejected = True
            rejection_reason = "High-impact event too close"
        
        # Calculate total score
        total_score = (
            max(bias_score, 0) +
            zone_score +
            trigger_score +
            room_score +
            volatility_score +
            session_score +
            spread_score +
            news_safety_score
        )
        
        # Create trade score
        trade_score = TradeScore(
            total_score=total_score,
            bias_score=max(bias_score, 0),
            zone_score=zone_score,
            trigger_score=trigger_score,
            room_score=room_score,
            volatility_score=volatility_score,
            session_score=session_score,
            spread_score=spread_score,
            news_safety_score=news_safety_score,
            timestamp=timestamp,
            direction=direction,
            entry_price=entry_price,
            stop_price=stop_price,
            target_price=target_price,
            rejected=rejected,
            rejection_reason=rejection_reason
        )
        
        # Log score
        if rejected:
            logger.info(
                f"Trade REJECTED: {rejection_reason} "
                f"(score: {total_score}/100)"
            )
        elif trade_score.passes_threshold(self.min_passing_score):
            logger.info(
                f"Trade APPROVED: {direction} at {entry_price:.2f} "
                f"(score: {total_score}/100)"
            )
        else:
            logger.info(
                f"Trade FILTERED: {direction} at {entry_price:.2f} "
                f"(score: {total_score}/100, need {self.min_passing_score})"
            )
        
        return trade_score

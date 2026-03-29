"""
Signal Engine — Thin data-contract shim.

ARCHITECTURE NOTE:
  Signal *evaluation logic* lives entirely in AnalysisSkill.
  This module only provides shared types and backward-compat helpers so that
  the production orchestrator import (check_reverse_signal / create_market_state)
  continues to work unchanged.

  Do NOT add indicator logic here.  All indicator & signal evaluation belongs in:
    skills/analysis/analysis_skill.py

Pure math utilities:
    core/indicators.py   — RSI, MACD, BB, ATR, VWAP, Stochastic, Volume, Fibonacci …
    core/sl_tp_engine.py — Fixed / ATR / Fibonacci / Supertrend SL-TP calculation
"""
from typing import Optional
from enum import Enum
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


class SignalType(Enum):
    """Shared signal type enum — used as event payload contract."""
    NONE = 0
    BUY = 1
    SELL = -1


@dataclass(frozen=True)
class MarketState:
    """
    Minimal market-state container kept for orchestrator back-compat.
    AnalysisSkill builds its own richer indicator dict internally.
    """
    close: float = 0.0
    supertrend_direction: int = 0
    ema: float = 0.0
    sma_fast: float = 0.0
    sma_slow: float = 0.0
    timestamp: Optional[str] = None


# ── Backward-compat helpers used by production_orchestrator ──────────────────

def check_reverse_signal(current_position_side: str, market: MarketState) -> bool:
    """
    Returns True when the market state implies a signal opposite to the open position.
    Used by orchestrator to check if a position should be reversed.
    Signal evaluation is intentionally simple here — full logic lives in AnalysisSkill.
    """
    st_up = market.supertrend_direction == 1
    st_down = market.supertrend_direction == -1
    above_ema = market.close > market.ema
    below_ema = market.close < market.ema
    sma_bull = market.sma_fast > market.sma_slow
    sma_bear = market.sma_fast < market.sma_slow

    sell_signal = st_down and below_ema and sma_bear
    buy_signal = st_up and above_ema and sma_bull

    if current_position_side == 'BUY' and sell_signal:
        return True
    if current_position_side == 'SELL' and buy_signal:
        return True
    return False


def create_market_state(close: float,
                        supertrend_direction: int,
                        ema: float,
                        sma_fast: float,
                        sma_slow: float,
                        timestamp: Optional[str] = None) -> MarketState:
    """
    Factory kept for orchestrator back-compat.
    New code should NOT call this — build indicator dicts inside AnalysisSkill.

    Args:
        close: Current close price
        supertrend_direction: Supertrend direction (1 or -1)
        ema: EMA value
        sma_fast: Fast SMA value
        sma_slow: Slow SMA value
        timestamp: Optional timestamp for debugging
        
    Returns:
        MarketState: Immutable market state
    """
    return MarketState(
        close=close,
        supertrend_direction=supertrend_direction,
        ema=ema,
        sma_fast=sma_fast,
        sma_slow=sma_slow,
        timestamp=timestamp
    )

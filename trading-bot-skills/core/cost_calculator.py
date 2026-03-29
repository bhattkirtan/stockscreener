"""
Cost Calculator - Pure Functional Module
Calculates transaction costs (spread, slippage) for trades.

All functions are pure (stateless) and match backtester logic exactly.
"""
from dataclasses import dataclass
from typing import Tuple


@dataclass(frozen=True)
class CostConfig:
    """Immutable cost configuration"""
    spread_pips: float = 0.5  # GOLD on Capital.com (0.5 typical, matches Sell-Buy gap)
    slippage_pips: float = 0.05
    pip_value: float = 1.0  # For GOLD: 1.0 (full dollar), Forex: 0.0001


@dataclass(frozen=True)
class TransactionCosts:
    """Immutable transaction costs for a trade"""
    spread_cost: float
    slippage_cost: float
    total_cost: float
    
    def to_dict(self):
        return {
            'spread_cost': self.spread_cost,
            'slippage_cost': self.slippage_cost,
            'total_cost': self.total_cost
        }


def calculate_costs(price: float, config: CostConfig, apply_slippage: bool = True) -> TransactionCosts:
    """
    Pure function: Calculate transaction costs for a trade.
    
    Logic matches backtester exactly:
    - Spread is ALWAYS applied (cost of crossing bid-ask)
    - Slippage only applies to market closes (not SL/TP exits)
    - Costs are FLAT per trade (not scaled by position size)
    
    Args:
        price: Trade price
        config: Cost configuration
        apply_slippage: Whether to include slippage (False for SL/TP exits)
        
    Returns:
        TransactionCosts: Immutable cost breakdown
    """
    spread_cost = config.spread_pips * config.pip_value
    slippage_cost = config.slippage_pips * config.pip_value if apply_slippage else 0.0
    
    return TransactionCosts(
        spread_cost=spread_cost,
        slippage_cost=slippage_cost,
        total_cost=spread_cost + slippage_cost
    )


def calculate_entry_slippage(price: float, direction: str, config: CostConfig) -> float:
    """
    Pure function: Calculate adjusted entry price with spread and slippage.
    
    Matches backtester logic:
    - BUY: Pay spread + slippage (worse price)
    - SELL: Pay spread + slippage (worse price)
    
    Args:
        price: Market price
        direction: 'BUY' or 'SELL'
        config: Cost configuration
        
    Returns:
        float: Adjusted entry price after costs
    """
    costs = calculate_costs(price, config, apply_slippage=True)
    
    if direction == 'BUY':
        return price + costs.total_cost
    else:  # SELL
        return price - costs.total_cost


def calculate_exit_slippage(price: float, direction: str, config: CostConfig, 
                           exit_reason: str) -> float:
    """
    Pure function: Calculate adjusted exit price with costs.
    
    Matches backtester logic:
    - SL/TP exits: No slippage (fill at exact level)
    - Market closes: Apply slippage (EOD, reverse signal, time exit)
    
    Args:
        price: Market price
        direction: 'BUY' or 'SELL'
        config: Cost configuration
        exit_reason: Reason for exit ('Stop Loss', 'Take Profit', etc.)
        
    Returns:
        float: Adjusted exit price after costs
    """
    # SL/TP exits fill at exact level (no slippage)
    sl_tp_exits = {'Stop Loss', 'Take Profit', 'SL_HIT', 'TP_HIT'}
    apply_slippage = exit_reason not in sl_tp_exits
    
    costs = calculate_costs(price, config, apply_slippage=apply_slippage)
    
    if direction == 'BUY':
        # Selling to close: lose spread (and maybe slippage)
        return price - costs.total_cost
    else:  # SELL
        # Buying to close: lose spread (and maybe slippage)
        return price + costs.total_cost


def calculate_position_costs(entry_price: float, size: float, config: CostConfig) -> TransactionCosts:
    """
    Pure function: Calculate total costs for opening a position.
    
    NOTE: Costs are FLAT per trade in backtester (not scaled by size).
    This matches Capital.com's pricing model where spread is per order, not per contract.
    
    Args:
        entry_price: Entry price
        size: Position size in contracts (not used in calculation)
        config: Cost configuration
        
    Returns:
        TransactionCosts: Flat costs per trade (matches backtester)
    """
    # Costs are flat per trade (not scaled by size)
    return calculate_costs(entry_price, config, apply_slippage=True)


# ============================================================================
# DEFAULTS (match backtester)
# ============================================================================

GOLD_COST_CONFIG = CostConfig(
    spread_pips=0.5,  # Capital.com GOLD spread (matches Sell-Buy gap of 0.50)
    slippage_pips=0.05,
    pip_value=1.0  # For GOLD: 1.0 (full dollar)
)

# ============================================================================
# EXAMPLE USAGE
# ============================================================================

if __name__ == "__main__":
    # Example: Opening a BUY position
    entry_price = 2650.50
    direction = 'BUY'
    size = 10.0
    
    print(f"Entry Price: ${entry_price}")
    print(f"Direction: {direction}")
    print(f"Size: {size} contracts\n")
    
    # Calculate adjusted entry price
    adjusted_entry = calculate_entry_slippage(entry_price, direction, GOLD_COST_CONFIG)
    print(f"Adjusted Entry: ${adjusted_entry:.2f}")
    print(f"Entry Slippage: ${adjusted_entry - entry_price:.2f}\n")
    
    # Calculate total position costs (flat per trade, NOT scaled by size)
    position_costs = calculate_position_costs(entry_price, size, GOLD_COST_CONFIG)
    print(f"Position Costs (flat per trade):")
    print(f"  Spread: ${position_costs.spread_cost:.2f}")
    print(f"  Slippage: ${position_costs.slippage_cost:.2f}")
    print(f"  Total: ${position_costs.total_cost:.2f}")
    print(f"  Note: Costs are flat per trade, not scaled by size\n")
    
    # Calculate exit price (TP - no slippage)
    exit_price = 2690.50
    adjusted_exit_tp = calculate_exit_slippage(exit_price, direction, GOLD_COST_CONFIG, 'Take Profit')
    print(f"Exit Price (TP): ${exit_price}")
    print(f"Adjusted Exit (TP): ${adjusted_exit_tp:.2f}")
    print(f"Exit Slippage (TP): ${exit_price - adjusted_exit_tp:.2f}\n")
    
    # Calculate exit price (Reverse Signal - with slippage)
    adjusted_exit_reverse = calculate_exit_slippage(exit_price, direction, GOLD_COST_CONFIG, 'Reverse Signal')
    print(f"Adjusted Exit (Reverse): ${adjusted_exit_reverse:.2f}")
    print(f"Exit Slippage (Reverse): ${exit_price - adjusted_exit_reverse:.2f}\n")
    
    # Total P&L calculation
    gross_pnl = (exit_price - entry_price) * size
    entry_cost = position_costs.total_cost
    exit_cost = calculate_costs(exit_price, GOLD_COST_CONFIG, apply_slippage=True).total_cost
    net_pnl = gross_pnl - entry_cost - exit_cost
    print(f"P&L Analysis for {size} contracts:")
    print(f"  Gross P&L: ${gross_pnl:.2f}")
    print(f"  Entry Cost: ${entry_cost:.2f}")
    print(f"  Exit Cost: ${exit_cost:.2f}")
    print(f"  Net P&L: ${net_pnl:.2f}")

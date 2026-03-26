"""
Position State Manager
Canonical source of truth for all open positions and pending orders.
Handles reconciliation between broker, runtime, and storage.
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional
from enum import Enum
import asyncio


class PositionStatus(Enum):
    """Position lifecycle states"""
    PENDING = "PENDING"  # Order submitted, not yet filled
    OPEN = "OPEN"        # Position active
    CLOSING = "CLOSING"  # Close requested, not yet confirmed
    CLOSED = "CLOSED"    # Position closed


class OrderStatus(Enum):
    """Order states"""
    SUBMITTED = "SUBMITTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    FILLED = "FILLED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


@dataclass
class Position:
    """
    Canonical position model - single source of truth.
    """
    # Identity
    deal_id: str
    instrument: str
    
    # Trade details
    direction: str  # 'BUY' or 'SELL'
    entry_price: float
    size: float
    
    # Risk management
    stop_loss: float
    take_profit: float
    
    # Lifecycle
    status: PositionStatus
    opened_at: datetime
    closed_at: Optional[datetime] = None
    
    # P&L (calculated)
    current_price: Optional[float] = None
    unrealized_pnl: float = 0.0
    realized_pnl: Optional[float] = None
    
    # Metadata
    signal_timestamp: Optional[datetime] = None
    close_reason: Optional[str] = None  # 'TP_HIT', 'SL_HIT', 'MANUAL', 'EXIT_SIGNAL'
    
    def calculate_unrealized_pnl(self, current_price: float) -> float:
        """Calculate current unrealized P&L"""
        self.current_price = current_price
        
        if self.direction == 'BUY':
            pnl = (current_price - self.entry_price) * self.size
        else:  # SELL
            pnl = (self.entry_price - current_price) * self.size
        
        self.unrealized_pnl = pnl
        return pnl
    
    def calculate_realized_pnl(self, close_price: float) -> float:
        """Calculate realized P&L at close"""
        if self.direction == 'BUY':
            pnl = (close_price - self.entry_price) * self.size
        else:  # SELL
            pnl = (self.entry_price - close_price) * self.size
        
        self.realized_pnl = pnl
        return pnl
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for storage"""
        return {
            'deal_id': self.deal_id,
            'instrument': self.instrument,
            'direction': self.direction,
            'entry_price': self.entry_price,
            'size': self.size,
            'stop_loss': self.stop_loss,
            'take_profit': self.take_profit,
            'status': self.status.value,
            'opened_at': self.opened_at.isoformat(),
            'closed_at': self.closed_at.isoformat() if self.closed_at else None,
            'current_price': self.current_price,
            'unrealized_pnl': self.unrealized_pnl,
            'realized_pnl': self.realized_pnl,
            'signal_timestamp': self.signal_timestamp.isoformat() if self.signal_timestamp else None,
            'close_reason': self.close_reason
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'Position':
        """Reconstruct from dictionary"""
        return cls(
            deal_id=data['deal_id'],
            instrument=data['instrument'],
            direction=data['direction'],
            entry_price=data['entry_price'],
            size=data['size'],
            stop_loss=data['stop_loss'],
            take_profit=data['take_profit'],
            status=PositionStatus(data['status']),
            opened_at=datetime.fromisoformat(data['opened_at']),
            closed_at=datetime.fromisoformat(data['closed_at']) if data.get('closed_at') else None,
            current_price=data.get('current_price'),
            unrealized_pnl=data.get('unrealized_pnl', 0.0),
            realized_pnl=data.get('realized_pnl'),
            signal_timestamp=datetime.fromisoformat(data['signal_timestamp']) if data.get('signal_timestamp') else None,
            close_reason=data.get('close_reason')
        )


@dataclass
class ReconciliationResult:
    """Result of broker reconciliation"""
    matched: List[str] = field(default_factory=list)  # deal_ids that match
    missing_local: List[Dict] = field(default_factory=list)  # Positions in broker but not local
    missing_broker: List[str] = field(default_factory=list)  # deal_ids in local but not broker
    mismatched: List[Dict] = field(default_factory=list)  # Positions with differences
    
    def has_issues(self) -> bool:
        """Check if reconciliation found problems"""
        return bool(self.missing_local or self.missing_broker or self.mismatched)
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for logging"""
        return {
            'matched': self.matched,
            'missing_local': self.missing_local,
            'missing_broker': self.missing_broker,
            'mismatched': self.mismatched,
            'has_issues': self.has_issues()
        }


class PositionStateManager:
    """
    Manages canonical position state with reconciliation.
    
    This is the single source of truth for:
    - All open positions
    - Pending orders
    - Position history
    - Exposure tracking
    
    Responsibilities:
    - Track position lifecycle
    - Reconcile with broker on startup/periodically
    - Calculate exposure and risk metrics
    - Persist state snapshots
    """
    
    def __init__(self, storage_skill=None, capital_api=None):
        """
        Initialize position state manager.
        
        Args:
            storage_skill: Storage skill for persistence
            capital_api: Capital.com API client for reconciliation
        """
        self.storage = storage_skill
        self.capital_api = capital_api
        
        # Runtime state (in-memory)
        self.positions: Dict[str, Position] = {}  # deal_id -> Position
        self.closed_positions: List[Position] = []
        
        # Reconciliation tracking
        self.last_reconciliation: Optional[datetime] = None
        self.reconciliation_interval_minutes = 5
        
    # ========== Position Management ==========
    
    def add_position(self, position: Position) -> None:
        """Add new position to state"""
        self.positions[position.deal_id] = position
        print(f"✅ Added position to state: {position.deal_id} ({position.direction} {position.instrument})")
    
    def get_position(self, deal_id: str) -> Optional[Position]:
        """Get position by deal_id"""
        return self.positions.get(deal_id)
    
    def get_open_positions(self) -> List[Position]:
        """Get all open positions"""
        return [p for p in self.positions.values() if p.status == PositionStatus.OPEN]
    
    def close_position(self, deal_id: str, close_price: float, close_reason: str) -> Optional[Position]:
        """
        Close a position and move to history.
        
        Args:
            deal_id: Position identifier
            close_price: Price at close
            close_reason: Reason for close (TP_HIT, SL_HIT, MANUAL, EXIT_SIGNAL)
        
        Returns:
            Closed position object
        """
        position = self.positions.get(deal_id)
        if not position:
            print(f"⚠️ Position {deal_id} not found in state")
            return None
        
        # Update position
        position.status = PositionStatus.CLOSED
        position.closed_at = datetime.now()
        position.close_reason = close_reason
        position.calculate_realized_pnl(close_price)
        
        # Move to history
        self.closed_positions.append(position)
        del self.positions[deal_id]
        
        print(f"✅ Closed position: {deal_id}, P&L: ${position.realized_pnl:.2f}, Reason: {close_reason}")
        return position
    
    def update_position_price(self, deal_id: str, current_price: float) -> Optional[Position]:
        """Update position with current price and recalculate P&L"""
        position = self.positions.get(deal_id)
        if position:
            position.calculate_unrealized_pnl(current_price)
        return position
    
    # ========== Exposure & Risk Metrics ==========
    
    def get_total_exposure(self) -> float:
        """Calculate total position exposure (sum of position sizes)"""
        return sum(p.size * p.entry_price for p in self.get_open_positions())
    
    def get_exposure_by_instrument(self) -> Dict[str, float]:
        """Get exposure breakdown by instrument"""
        exposure = {}
        for position in self.get_open_positions():
            instrument = position.instrument
            position_value = position.size * position.entry_price
            exposure[instrument] = exposure.get(instrument, 0) + position_value
        return exposure
    
    def get_total_unrealized_pnl(self) -> float:
        """Calculate total unrealized P&L across all open positions"""
        return sum(p.unrealized_pnl for p in self.get_open_positions())
    
    def get_position_count(self, instrument: Optional[str] = None) -> int:
        """
        Get count of open positions.
        
        Args:
            instrument: Optional filter by instrument
        
        Returns:
            Count of positions
        """
        positions = self.get_open_positions()
        if instrument:
            positions = [p for p in positions if p.instrument == instrument]
        return len(positions)
    
    # ========== Reconciliation ==========
    
    async def reconcile_with_broker(self) -> ReconciliationResult:
        """
        Reconcile local state with broker positions.
        
        This is CRITICAL for restart safety and preventing ghost positions.
        
        Returns:
            ReconciliationResult with any mismatches
        """
        if not self.capital_api:
            print("⚠️ No Capital.com API client configured - skipping reconciliation")
            return ReconciliationResult()
        
        result = ReconciliationResult()
        
        try:
            # Fetch broker positions
            broker_positions = await self.capital_api.get_open_positions()
            
            # Build lookup maps
            local_deal_ids = set(self.positions.keys())
            broker_deal_ids = {bp.get('deal_id') for bp in broker_positions if bp.get('deal_id')}
            
            # Check for matches
            result.matched = list(local_deal_ids & broker_deal_ids)
            
            # Find missing positions
            result.missing_local = [
                bp for bp in broker_positions 
                if bp.get('deal_id') not in local_deal_ids
            ]
            
            result.missing_broker = list(local_deal_ids - broker_deal_ids)
            
            # Check for mismatches in matched positions
            for deal_id in result.matched:
                local_pos = self.positions[deal_id]
                broker_pos = next(bp for bp in broker_positions if bp.get('deal_id') == deal_id)
                
                # Compare key fields
                if (local_pos.direction != broker_pos.get('direction') or
                    abs(local_pos.size - broker_pos.get('size', 0)) > 0.01):
                    result.mismatched.append({
                        'deal_id': deal_id,
                        'local': local_pos.to_dict(),
                        'broker': broker_pos
                    })
            
            self.last_reconciliation = datetime.now()
            
            if result.has_issues():
                print(f"⚠️ Reconciliation found issues:")
                print(f"  - Matched: {len(result.matched)}")
                print(f"  - Missing local: {len(result.missing_local)}")
                print(f"  - Missing broker: {len(result.missing_broker)}")
                print(f"  - Mismatched: {len(result.mismatched)}")
            else:
                print(f"✅ Reconciliation successful: {len(result.matched)} positions matched")
            
            return result
        
        except Exception as e:
            print(f"❌ Reconciliation failed: {e}")
            return result
    
    async def auto_heal_from_reconciliation(self, result: ReconciliationResult) -> None:
        """
        Automatically fix reconciliation issues where possible.
        
        Strategy:
        - Missing local: Add positions from broker
        - Missing broker: Mark local positions as closed (assume stopped out)
        - Mismatched: Update local with broker values (broker is truth)
        """
        # Add missing local positions
        for broker_pos in result.missing_local:
            position = Position(
                deal_id=broker_pos['deal_id'],
                instrument=broker_pos['instrument'],
                direction=broker_pos['direction'],
                entry_price=broker_pos['entry_price'],
                size=broker_pos['size'],
                stop_loss=broker_pos.get('stop_loss', 0),
                take_profit=broker_pos.get('take_profit', 0),
                status=PositionStatus.OPEN,
                opened_at=datetime.now()  # Approximate
            )
            self.add_position(position)
            print(f"🔧 Auto-healed: Added missing position {position.deal_id}")
        
        # Close positions missing from broker
        for deal_id in result.missing_broker:
            position = self.close_position(
                deal_id=deal_id,
                close_price=self.positions[deal_id].entry_price,  # Unknown close price
                close_reason='RECONCILIATION_CLOSED'
            )
            print(f"🔧 Auto-healed: Closed orphaned position {deal_id}")
        
        # Update mismatched positions
        for mismatch in result.mismatched:
            deal_id = mismatch['deal_id']
            broker_data = mismatch['broker']
            
            position = self.positions[deal_id]
            position.direction = broker_data['direction']
            position.size = broker_data['size']
            position.entry_price = broker_data['entry_price']
            
            print(f"🔧 Auto-healed: Updated position {deal_id} from broker values")
    
    # ========== Persistence ==========
    
    async def save_snapshot(self) -> bool:
        """
        Save current state snapshot to storage.
        
        This enables restart recovery.
        """
        if not self.storage:
            return False
        
        snapshot = {
            'timestamp': datetime.now().isoformat(),
            'open_positions': [p.to_dict() for p in self.get_open_positions()],
            'last_reconciliation': self.last_reconciliation.isoformat() if self.last_reconciliation else None
        }
        
        try:
            # Use storage skill to persist
            await self.storage.save_state_snapshot(snapshot)
            print(f"✅ Saved state snapshot: {len(snapshot['open_positions'])} positions")
            return True
        except Exception as e:
            print(f"❌ Failed to save snapshot: {e}")
            return False
    
    async def load_snapshot(self) -> bool:
        """
        Load state snapshot from storage.
        
        Called on startup for recovery.
        """
        if not self.storage:
            return False
        
        try:
            snapshot = await self.storage.load_state_snapshot()
            if not snapshot:
                print("ℹ️ No previous state snapshot found")
                return False
            
            # Restore positions
            for pos_data in snapshot.get('open_positions', []):
                position = Position.from_dict(pos_data)
                self.add_position(position)
            
            self.last_reconciliation = (
                datetime.fromisoformat(snapshot['last_reconciliation'])
                if snapshot.get('last_reconciliation') else None
            )
            
            print(f"✅ Loaded state snapshot: {len(snapshot['open_positions'])} positions restored")
            return True
        
        except Exception as e:
            print(f"❌ Failed to load snapshot: {e}")
            return False

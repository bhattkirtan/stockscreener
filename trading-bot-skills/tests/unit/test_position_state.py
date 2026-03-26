"""
Unit tests for Position State Manager
Tests position tracking, reconciliation, auto-healing, and snapshot persistence
"""
import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock, AsyncMock

from core.position_state import (
    Position, PositionStatus, OrderStatus,
    ReconciliationResult, PositionStateManager
)


# ========== Position Model Tests ==========

def test_position_creation():
    """Test creating a position"""
    position = Position(
        deal_id='DEAL123',
        instrument='GOLD',
        direction='BUY',
        entry_price=1950.00,
        size=0.1,
        stop_loss=1940.00,
        take_profit=1980.00,
        status=PositionStatus.OPEN,
        opened_at=datetime.now(),
        signal_timestamp=datetime.now()
    )
    
    assert position.deal_id == 'DEAL123'
    assert position.instrument == 'GOLD'
    assert position.direction == 'BUY'
    assert position.status == PositionStatus.OPEN


def test_position_unrealized_pnl_calculation_buy():
    """Test unrealized P&L calculation for BUY position"""
    position = Position(
        deal_id='DEAL123',
        instrument='GOLD',
        direction='BUY',
        entry_price=1950.00,
        size=0.1,
        stop_loss=1940.00,
        take_profit=1980.00,
        status=PositionStatus.OPEN,
        opened_at=datetime.now(),
        signal_timestamp=datetime.now()
    )
    
    # Price moves up by $10 (profit)
    position.calculate_unrealized_pnl(current_price=1960.00)
    
    # For GOLD, 0.1 lots = 0.1 * 10 = $1 per point
    # $10 move * $1 per point = $10 profit
    assert position.unrealized_pnl == 10.0


def test_position_unrealized_pnl_calculation_sell():
    """Test unrealized P&L calculation for SELL position"""
    position = Position(
        deal_id='DEAL123',
        instrument='GOLD',
        direction='SELL',
        entry_price=1950.00,
        size=0.1,
        stop_loss=1960.00,
        take_profit=1920.00,
        status=PositionStatus.OPEN,
        opened_at=datetime.now(),
        signal_timestamp=datetime.now()
    )
    
    # Price moves down by $10 (profit for SELL)
    position.calculate_unrealized_pnl(current_price=1940.00)
    
    # SELL: entry 1950, current 1940 = +$10 profit
    assert position.unrealized_pnl == 10.0


def test_position_realized_pnl_on_close():
    """Test realized P&L calculation when position closed"""
    position = Position(
        deal_id='DEAL123',
        instrument='GOLD',
        direction='BUY',
        entry_price=1950.00,
        size=0.1,
        stop_loss=1940.00,
        take_profit=1980.00,
        status=PositionStatus.OPEN,
        opened_at=datetime.now(),
        signal_timestamp=datetime.now()
    )
    
    # Close at profit target
    position.status = PositionStatus.CLOSED
    position.close_price = 1980.00
    position.closed_at = datetime.now()
    position.close_reason = 'take_profit'
    
    # Calculate realized P&L
    position.realized_pnl = (position.close_price - position.entry_price) * position.size * 10
    
    assert position.realized_pnl == 30.0  # $30 profit
    assert position.status == PositionStatus.CLOSED


# ========== Position State Manager Tests ==========

@pytest.fixture
def mock_storage():
    """Mock storage skill"""
    storage = Mock()
    storage.save_data = AsyncMock(return_value=True)
    storage.load_data = AsyncMock(return_value=None)
    return storage


@pytest.fixture
def mock_capital_api():
    """Mock Capital.com API"""
    api = Mock()
    api.get_open_positions = AsyncMock(return_value=[])
    return api


@pytest.fixture
def position_manager(mock_storage, mock_capital_api):
    """Create position state manager"""
    return PositionStateManager(
        storage_skill=mock_storage,
        capital_api=mock_capital_api
    )


def test_add_position(position_manager):
    """Test adding a position"""
    position = Position(
        deal_id='DEAL123',
        instrument='GOLD',
        direction='BUY',
        entry_price=1950.00,
        size=0.1,
        stop_loss=1940.00,
        take_profit=1980.00,
        status=PositionStatus.OPEN,
        opened_at=datetime.now(),
        signal_timestamp=datetime.now()
    )
    
    position_manager.add_position(position)
    
    assert position_manager.get_position_count() == 1
    assert position_manager.get_position('DEAL123') == position


def test_get_open_positions(position_manager):
    """Test getting only open positions"""
    # Add open position
    pos1 = Position(
        deal_id='DEAL1',
        instrument='GOLD',
        direction='BUY',
        entry_price=1950.00,
        size=0.1,
        stop_loss=1940.00,
        take_profit=1980.00,
        status=PositionStatus.OPEN,
        opened_at=datetime.now(),
        signal_timestamp=datetime.now()
    )
    
    # Add closed position
    pos2 = Position(
        deal_id='DEAL2',
        instrument='GOLD',
        direction='SELL',
        entry_price=1960.00,
        size=0.1,
        stop_loss=1970.00,
        take_profit=1930.00,
        status=PositionStatus.CLOSED,
        opened_at=datetime.now() - timedelta(hours=2),
        signal_timestamp=datetime.now() - timedelta(hours=2),
        closed_at=datetime.now(),
        close_price=1930.00,
        close_reason='take_profit'
    )
    
    position_manager.add_position(pos1)
    position_manager.add_position(pos2)
    
    open_positions = position_manager.get_open_positions()
    
    assert len(open_positions) == 1
    assert open_positions[0].deal_id == 'DEAL1'


def test_close_position(position_manager):
    """Test closing a position"""
    # Add open position
    position = Position(
        deal_id='DEAL123',
        instrument='GOLD',
        direction='BUY',
        entry_price=1950.00,
        size=0.1,
        stop_loss=1940.00,
        take_profit=1980.00,
        status=PositionStatus.OPEN,
        opened_at=datetime.now(),
        signal_timestamp=datetime.now()
    )
    position_manager.add_position(position)
    
    # Close position
    closed = position_manager.close_position(
        deal_id='DEAL123',
        close_price=1980.00,
        close_reason='take_profit'
    )
    
    assert closed is not None
    assert closed.status == PositionStatus.CLOSED
    assert closed.close_price == 1980.00
    assert closed.close_reason == 'take_profit'


def test_get_total_exposure(position_manager):
    """Test total exposure calculation"""
    # Add 2 positions
    pos1 = Position(
        deal_id='DEAL1',
        instrument='GOLD',
        direction='BUY',
        entry_price=1950.00,
        size=0.1,
        stop_loss=1940.00,
        take_profit=1980.00,
        status=PositionStatus.OPEN,
        opened_at=datetime.now(),
        signal_timestamp=datetime.now()
    )
    
    pos2 = Position(
        deal_id='DEAL2',
        instrument='EURUSD',
        direction='BUY',
        entry_price=1.1000,
        size=0.2,
        stop_loss=1.0950,
        take_profit=1.1100,
        status=PositionStatus.OPEN,
        opened_at=datetime.now(),
        signal_timestamp=datetime.now()
    )
    
    position_manager.add_position(pos1)
    position_manager.add_position(pos2)
    
    total_exposure = position_manager.get_total_exposure()
    
    assert total_exposure == 0.3  # 0.1 + 0.2


def test_get_exposure_by_instrument(position_manager):
    """Test exposure by instrument"""
    # Add 2 GOLD positions and 1 EURUSD
    pos1 = Position(
        deal_id='DEAL1',
        instrument='GOLD',
        direction='BUY',
        entry_price=1950.00,
        size=0.1,
        stop_loss=1940.00,
        take_profit=1980.00,
        status=PositionStatus.OPEN,
        opened_at=datetime.now(),
        signal_timestamp=datetime.now()
    )
    
    pos2 = Position(
        deal_id='DEAL2',
        instrument='GOLD',
        direction='SELL',
        entry_price=1960.00,
        size=0.2,
        stop_loss=1970.00,
        take_profit=1930.00,
        status=PositionStatus.OPEN,
        opened_at=datetime.now(),
        signal_timestamp=datetime.now()
    )
    
    pos3 = Position(
        deal_id='DEAL3',
        instrument='EURUSD',
        direction='BUY',
        entry_price=1.1000,
        size=0.5,
        stop_loss=1.0950,
        take_profit=1.1100,
        status=PositionStatus.OPEN,
        opened_at=datetime.now(),
        signal_timestamp=datetime.now()
    )
    
    position_manager.add_position(pos1)
    position_manager.add_position(pos2)
    position_manager.add_position(pos3)
    
    gold_exposure = position_manager.get_exposure_by_instrument('GOLD')
    eurusd_exposure = position_manager.get_exposure_by_instrument('EURUSD')
    
    assert gold_exposure == 0.3  # 0.1 + 0.2
    assert eurusd_exposure == 0.5


@pytest.mark.asyncio
async def test_reconciliation_with_no_issues(position_manager, mock_capital_api):
    """Test reconciliation when broker and local match"""
    # Add local position
    local_position = Position(
        deal_id='DEAL123',
        instrument='GOLD',
        direction='BUY',
        entry_price=1950.00,
        size=0.1,
        stop_loss=1940.00,
        take_profit=1980.00,
        status=PositionStatus.OPEN,
        opened_at=datetime.now(),
        signal_timestamp=datetime.now()
    )
    position_manager.add_position(local_position)
    
    # Mock broker returns same position
    mock_capital_api.get_open_positions.return_value = [{
        'deal_id': 'DEAL123',
        'instrument': 'GOLD',
        'direction': 'BUY',
        'size': 0.1,
        'open_level': 1950.00,
        'stop_level': 1940.00,
        'profit_level': 1980.00
    }]
    
    # Reconcile
    result = await position_manager.reconcile_with_broker()
    
    assert len(result.matched) == 1
    assert len(result.missing_local) == 0
    assert len(result.missing_broker) == 0
    assert result.has_issues() is False


@pytest.mark.asyncio
async def test_reconciliation_detects_missing_local(position_manager, mock_capital_api):
    """Test reconciliation detects positions in broker but not local"""
    # No local positions
    
    # Mock broker has 1 position
    mock_capital_api.get_open_positions.return_value = [{
        'deal_id': 'BROKER123',
        'instrument': 'GOLD',
        'direction': 'BUY',
        'size': 0.1,
        'open_level': 1950.00,
        'stop_level': 1940.00,
        'profit_level': 1980.00
    }]
    
    # Reconcile
    result = await position_manager.reconcile_with_broker()
    
    assert len(result.missing_local) == 1
    assert result.missing_local[0]['deal_id'] == 'BROKER123'
    assert result.has_issues() is True


@pytest.mark.asyncio
async def test_reconciliation_detects_orphaned_local(position_manager, mock_capital_api):
    """Test reconciliation detects orphaned local positions"""
    # Add local position
    local_position = Position(
        deal_id='ORPHAN123',
        instrument='GOLD',
        direction='BUY',
        entry_price=1950.00,
        size=0.1,
        stop_loss=1940.00,
        take_profit=1980.00,
        status=PositionStatus.OPEN,
        opened_at=datetime.now(),
        signal_timestamp=datetime.now()
    )
    position_manager.add_position(local_position)
    
    # Mock broker has no positions
    mock_capital_api.get_open_positions.return_value = []
    
    # Reconcile
    result = await position_manager.reconcile_with_broker()
    
    assert len(result.missing_broker) == 1
    assert result.missing_broker[0].deal_id == 'ORPHAN123'
    assert result.has_issues() is True


@pytest.mark.asyncio
async def test_auto_heal_adds_missing_local(position_manager, mock_capital_api):
    """Test auto-healing adds missing local positions"""
    # No local positions
    
    # Create reconciliation result with missing local
    result = ReconciliationResult()
    result.missing_local = [{
        'deal_id': 'BROKER123',
        'instrument': 'GOLD',
        'direction': 'BUY',
        'size': 0.1,
        'open_level': 1950.00,
        'stop_level': 1940.00,
        'profit_level': 1980.00
    }]
    
    # Auto-heal
    await position_manager.auto_heal_from_reconciliation(result)
    
    # Position should be added locally
    assert position_manager.get_position_count() == 1
    added = position_manager.get_position('BROKER123')
    assert added is not None
    assert added.instrument == 'GOLD'


@pytest.mark.asyncio
async def test_auto_heal_closes_orphaned_local(position_manager):
    """Test auto-healing closes orphaned local positions"""
    # Add local position
    local_position = Position(
        deal_id='ORPHAN123',
        instrument='GOLD',
        direction='BUY',
        entry_price=1950.00,
        size=0.1,
        stop_loss=1940.00,
        take_profit=1980.00,
        status=PositionStatus.OPEN,
        opened_at=datetime.now(),
        signal_timestamp=datetime.now()
    )
    position_manager.add_position(local_position)
    
    # Create reconciliation result with orphaned position
    result = ReconciliationResult()
    result.missing_broker = [local_position]
    
    # Auto-heal
    await position_manager.auto_heal_from_reconciliation(result)
    
    # Position should be closed
    orphan = position_manager.get_position('ORPHAN123')
    assert orphan.status == PositionStatus.CLOSED
    assert orphan.close_reason == 'orphaned'


@pytest.mark.asyncio
async def test_snapshot_save_and_load(position_manager, mock_storage):
    """Test snapshot persistence"""
    # Add position
    position = Position(
        deal_id='DEAL123',
        instrument='GOLD',
        direction='BUY',
        entry_price=1950.00,
        size=0.1,
        stop_loss=1940.00,
        take_profit=1980.00,
        status=PositionStatus.OPEN,
        opened_at=datetime.now(),
        signal_timestamp=datetime.now()
    )
    position_manager.add_position(position)
    
    # Save snapshot
    await position_manager.save_snapshot()
    
    # Verify storage was called
    assert mock_storage.save_data.called


if __name__ == '__main__':
    pytest.main([__file__, '-v'])

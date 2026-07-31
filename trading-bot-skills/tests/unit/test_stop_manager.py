"""
Unit Tests — StopManager (broker-side breakeven + trailing stop)

Covers the ratchet invariants that keep this safe to run against live money:
stops only ever tighten, never widen, and are never placed through the market.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from core.stop_manager import StopManager


class FakeCapital:
    """Records update_position calls instead of hitting Capital.com."""

    def __init__(self):
        self.calls = []

    def update_position(self, deal_id, stop_level=None, profit_level=None):
        self.calls.append((deal_id, stop_level))
        return {'dealReference': 'ref'}


CFG = {
    'stop_management': {
        'enabled': True,
        'check_interval_sec': 0,   # no rate limiting in tests
        'min_step_pips': 1.0,
        'breakeven': {'enabled': True, 'trigger_pips': 20, 'offset_pips': 2},
        'trailing':  {'enabled': True, 'start_pips': 25, 'distance_pips': 15},
    }
}


def make(positions, cfg=CFG, pip_size=1.0):
    capital = FakeCapital()
    sm = StopManager(capital, cfg, pip_size=pip_size)
    sm.sync_positions(positions)
    return capital, sm


BUY_POS = {'D1': {'direction': 'BUY', 'level': 4000.0, 'stopLevel': 3985.0}}
SELL_POS = {'D1': {'direction': 'SELL', 'level': 4000.0, 'stopLevel': 4015.0}}


class TestBreakeven:

    @pytest.mark.asyncio
    async def test_no_amend_before_trigger(self):
        capital, sm = make(BUY_POS)
        for price in (4005, 4010, 4015, 4019):
            await sm.on_price(price)
        assert capital.calls == []

    @pytest.mark.asyncio
    async def test_arms_at_trigger_with_offset(self):
        capital, sm = make(BUY_POS)
        await sm.on_price(4020)          # +20 pips
        assert capital.calls == [('D1', 4002.0)]   # entry + offset

    @pytest.mark.asyncio
    async def test_sell_side_mirrors(self):
        capital, sm = make(SELL_POS)
        await sm.on_price(3981)
        assert capital.calls == []
        await sm.on_price(3980)          # +20 pips
        assert capital.calls == [('D1', 3998.0)]   # entry - offset


class TestTrailing:

    @pytest.mark.asyncio
    async def test_arms_at_start_and_follows(self):
        capital, sm = make(BUY_POS)
        await sm.on_price(4020)
        await sm.on_price(4025)          # +25 -> 4025 - 15
        assert capital.calls[-1] == ('D1', 4010.0)
        await sm.on_price(4040)          # -> 4040 - 15
        assert capital.calls[-1] == ('D1', 4025.0)

    @pytest.mark.asyncio
    async def test_never_widens_on_pullback(self):
        capital, sm = make(BUY_POS)
        await sm.on_price(4040)
        n = len(capital.calls)
        for price in (4030, 4020, 4012):
            await sm.on_price(price)
        assert len(capital.calls) == n
        assert sm._positions['D1']['stop'] == 4025.0

    @pytest.mark.asyncio
    async def test_sell_never_widens_on_retrace(self):
        capital, sm = make(SELL_POS)
        await sm.on_price(3975)
        assert capital.calls[-1] == ('D1', 3990.0)
        n = len(capital.calls)
        await sm.on_price(3995)
        assert len(capital.calls) == n

    @pytest.mark.asyncio
    async def test_min_step_suppresses_tiny_improvements(self):
        capital, sm = make(BUY_POS)
        await sm.on_price(4040)          # stop 4025
        n = len(capital.calls)
        await sm.on_price(4040.5)        # would be 4025.5 — only 0.5 pip better
        assert len(capital.calls) == n


class TestSafety:

    @pytest.mark.asyncio
    async def test_stop_through_market_rejected(self):
        """A stop at/through the current price would be a market close."""
        capital, sm = make(BUY_POS)
        await sm.on_price(4100)          # stop -> 4085
        capital.calls.clear()
        await sm.on_price(4080)          # candidate 4085 >= price
        assert capital.calls == []

    @pytest.mark.asyncio
    async def test_broker_error_leaves_state_unchanged(self):
        capital, sm = make(BUY_POS)

        def boom(**kwargs):
            raise RuntimeError("429 rate limited")

        capital.update_position = boom
        await sm.on_price(4020)
        assert sm._positions['D1']['stop'] == 3985.0

    @pytest.mark.asyncio
    async def test_broker_stop_wins_on_resync(self):
        """Stop may be changed outside this process — broker is source of truth."""
        capital, sm = make(BUY_POS)
        await sm.on_price(4030)
        sm.sync_positions({'D1': {'direction': 'BUY', 'level': 4000.0, 'stopLevel': 3990.0}})
        assert sm._positions['D1']['stop'] == 3990.0

    @pytest.mark.asyncio
    async def test_disabled_makes_no_calls(self):
        capital, sm = make(BUY_POS, cfg={'stop_management': {'enabled': False}})
        for price in range(4000, 4100, 5):
            await sm.on_price(price)
        assert capital.calls == []
        assert sm._positions == {}

    @pytest.mark.asyncio
    async def test_forget_halts_amends(self):
        capital, sm = make(BUY_POS)
        sm.forget('D1')
        await sm.on_price(4050)
        assert capital.calls == []

    @pytest.mark.asyncio
    async def test_closed_position_dropped_on_sync(self):
        capital, sm = make(BUY_POS)
        sm.sync_positions({})
        await sm.on_price(4050)
        assert capital.calls == []


class TestPipSizing:

    @pytest.mark.asyncio
    async def test_forex_pip_size(self):
        capital, sm = make(
            {'E1': {'direction': 'BUY', 'level': 1.1000, 'stopLevel': 1.0980}},
            pip_size=0.0001,
        )
        await sm.on_price(1.1020)        # +20 pips
        assert capital.calls[-1] == ('E1', 1.1002)

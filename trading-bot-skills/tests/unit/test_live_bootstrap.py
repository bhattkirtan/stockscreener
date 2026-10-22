"""
Unit tests — orchestrator/main.py `run_live_mode` and `main`.

`run_live_mode` is the live bootstrap: authenticate, restore any position left
open by the previous process, compute warm-up bar counts from the configured
indicator periods, replay history into the buffer, then connect the WebSocket
and re-connect forever. It is ~300 statements that never run in backtest and
had no tests, yet it decides how much history the indicators see and whether
the startup-flip gate is armed on restart.

Everything external is faked: CapitalAPIClient, CapitalWebSocketClient and
StopManager are all imported INSIDE the function, so monkeypatching the client
modules is enough and no network is touched. `asyncio.sleep` is replaced so the
reconnect backoff and the 120s watchdog grace period cost nothing.
"""
import asyncio
import logging
import os
import sys
from datetime import datetime

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

import clients.capital_api as capital_api_mod
import clients.capital_websocket as capital_ws_mod
import core.stop_manager as stop_manager_mod
import orchestrator.main as main_mod
from orchestrator.main import main as main_entry
from orchestrator.main import run_live_mode


# ──────────────────────────────────────────────────────────────────────────
# Fakes
# ──────────────────────────────────────────────────────────────────────────

def candle(i=0, close=4100.0):
    return {'snapshotTime': f'2026-10-21T10:{i:02d}:00', 'open': close,
            'high': close + 1, 'low': close - 1, 'close': close, 'volume': 10}


class FakeCapital:
    instances = []

    def __init__(self, **kw):
        self.init_kwargs = kw
        self.token_calls = 0
        self.price_calls = []
        self.positions = []
        self.positions_raises = False
        self.history = {}
        self.history_raises = set()
        FakeCapital.instances.append(self)

    def get_tokens(self):
        self.token_calls += 1
        return {'CST': 'cst-tok', 'X-SECURITY-TOKEN': 'sec-tok'}

    def get_open_positions(self):
        if self.positions_raises:
            raise RuntimeError('500 /positions')
        return self.positions

    def get_historical_prices(self, epic=None, resolution=None, max_bars=None):
        self.price_calls.append({'epic': epic, 'resolution': resolution,
                                 'max_bars': max_bars})
        if resolution in self.history_raises:
            raise RuntimeError(f'{resolution} fetch 400')
        return self.history.get(resolution, [])

    def get_activity(self, **kw):
        return []

    def get_realised_pnl(self, deal_id, **kw):
        return None


class FakeWS:
    instances = []

    def __init__(self, cst=None, security_token=None):
        self.cst = cst
        self.security_token = security_token
        self.connected = False
        self.ohlc_subs = []
        self.quote_subs = []
        self.closed = 0
        self.on_candle = None
        self.on_h1_candle = None
        self.on_quote = None
        # run() behaviour: 'return' | 'raise' | 'hang'
        self.run_mode = 'return'
        FakeWS.instances.append(self)

    async def connect(self):
        self.connected = True

    async def subscribe_ohlc(self, epics, resolution=None):
        self.ohlc_subs.append((tuple(epics), resolution))

    async def subscribe_quotes(self, epics):
        self.quote_subs.append(tuple(epics))

    async def run(self):
        if self.run_mode == 'raise':
            raise RuntimeError('ws dropped')
        if self.run_mode == 'hang':
            await asyncio.Event().wait()

    async def close(self):
        self.closed += 1


class FakeStopManager:
    instances = []

    def __init__(self, capital_client=None, config=None, pip_size=None):
        self.capital_client = capital_client
        self.config = config
        self.pip_size = pip_size
        self.prices = []
        FakeStopManager.instances.append(self)

    def sync_positions(self, known):
        pass

    def forget(self, deal_id):
        pass

    async def on_price(self, mid):
        self.prices.append(mid)


class FakeAnalysis:
    """Only the attributes run_live_mode actually reads."""

    def __init__(self, require_h1_bb=False, require_daily_bias=False):
        self.sma_slow_period = 30
        self.bb_period = 20
        self.st_period = 14
        self.macd_slow = 26
        self.macd_signal_period = 9
        self.rsi_period = 14
        self.stoch_k_period = 14
        self.require_h1_bb = require_h1_bb
        self.require_daily_bias = require_daily_bias
        self.mtf_h1_bb_period = 20
        self.mtf_daily_sma = 20
        self.h1_loaded = None
        self.daily_loaded = None
        self.ticks = []

    def load_h1_history(self, candles):
        self.h1_loaded = candles

    def load_daily_history(self, candles):
        self.daily_loaded = candles

    async def on_price_tick(self, mid, ts=None):
        self.ticks.append((mid, ts))


class FakeExecution:
    def __init__(self, rest_client=None):
        self.rest_client = rest_client
        self.mock_mode = True
        self.epic = None


class FakeMarketData:
    def __init__(self):
        self.buffer_size = 50


class FakeRisk:
    def __init__(self):
        self.has_open_position = False
        self.open_position_deal_id = None
        self.open_position_direction = None
        self._startup_flip_seen = False


class FakeOrchestrator:
    def __init__(self, skills=None, running=True):
        self.skills = skills if skills is not None else {}
        self.running = running
        self.warming_up = False
        self.candles = []
        self.warming_flags = []
        self.started = 0
        self.stopped = 0

    async def on_candle(self, candle):
        self.candles.append(candle)
        self.warming_flags.append(self.warming_up)

    async def on_position_closed(self, **kw):
        pass

    async def start(self):
        self.started += 1

    async def stop(self):
        self.stopped += 1


def base_config(**over):
    cfg = {
        'execution': {'epic': 'US100', 'identifier': 'u', 'password': 'p',
                      'api_key': 'k'},
        'market_data': {'timeframe': 'M5'},
        'risk': {'pip_size': 1.0},
        'analysis': {'sl_tp': {'pip_size': 1.0}},
    }
    cfg.update(over)
    return cfg


@pytest.fixture
def broker(monkeypatch):
    """
    Patch the three classes run_live_mode imports, and make asyncio.sleep free
    so the reconnect backoff (up to 60s) and the watchdog's 120s grace period
    cost no wall clock.
    """
    FakeCapital.instances.clear()
    FakeWS.instances.clear()
    FakeStopManager.instances.clear()
    monkeypatch.setattr(capital_api_mod, 'CapitalAPIClient', FakeCapital)
    monkeypatch.setattr(capital_ws_mod, 'CapitalWebSocketClient', FakeWS)
    monkeypatch.setattr(stop_manager_mod, 'StopManager', FakeStopManager)

    real = asyncio.sleep

    async def instant(_delay=0):
        await real(0)

    monkeypatch.setattr(asyncio, 'sleep', instant)
    return real


# ──────────────────────────────────────────────────────────────────────────
# Epic resolution and authentication
# ──────────────────────────────────────────────────────────────────────────

class TestEpicResolution:

    @pytest.mark.asyncio
    async def test_missing_epic_raises(self, broker):
        cfg = base_config(execution={}, market_data={'timeframe': 'M5'})
        with pytest.raises(ValueError, match='No epic/instrument configured'):
            await run_live_mode(cfg, FakeOrchestrator(running=False), 'demo')

    @pytest.mark.asyncio
    async def test_execution_epic_wins(self, broker):
        cfg = base_config(execution={'epic': 'GOLD'},
                          market_data={'timeframe': 'M5', 'epic': 'US100'})
        orch = FakeOrchestrator({'execution': FakeExecution()}, running=False)
        await run_live_mode(cfg, orch, 'demo')
        assert orch.skills['execution'].epic == 'GOLD'

    @pytest.mark.asyncio
    async def test_market_data_epic_is_the_fallback(self, broker):
        cfg = base_config(execution={}, market_data={'timeframe': 'M5',
                                                     'epic': 'ETHUSD'})
        orch = FakeOrchestrator({'execution': FakeExecution()}, running=False)
        await run_live_mode(cfg, orch, 'demo')
        assert orch.skills['execution'].epic == 'ETHUSD'

    @pytest.mark.asyncio
    async def test_market_data_instrument_is_the_last_fallback(self, broker):
        cfg = base_config(execution={},
                          market_data={'timeframe': 'M5', 'instrument': 'SILVER'})
        orch = FakeOrchestrator({'execution': FakeExecution()}, running=False)
        await run_live_mode(cfg, orch, 'demo')
        assert orch.skills['execution'].epic == 'SILVER'


class TestAuthenticationAndWiring:

    @pytest.mark.asyncio
    async def test_credentials_come_from_the_execution_section(self, broker):
        """The YAML key is `identifier`, not `username`."""
        cfg = base_config(execution={'epic': 'US100', 'identifier': 'me@x.com',
                                     'password': 'pw', 'api_key': 'ak'})
        await run_live_mode(cfg, FakeOrchestrator(running=False), 'demo')
        kw = FakeCapital.instances[0].init_kwargs
        assert kw['username'] == 'me@x.com'
        assert kw['password'] == 'pw'
        assert kw['api_key'] == 'ak'

    @pytest.mark.asyncio
    async def test_environment_is_passed_through(self, broker):
        await run_live_mode(base_config(), FakeOrchestrator(running=False), 'live')
        assert FakeCapital.instances[0].init_kwargs['environment'] == 'live'

    @pytest.mark.asyncio
    async def test_the_rest_client_is_wired_into_execution(self, broker):
        ex = FakeExecution()
        orch = FakeOrchestrator({'execution': ex}, running=False)
        await run_live_mode(base_config(), orch, 'demo')
        assert ex.rest_client is FakeCapital.instances[0]
        assert ex.mock_mode is False

    @pytest.mark.asyncio
    async def test_an_existing_rest_client_is_not_replaced(self, broker):
        sentinel = object()
        ex = FakeExecution(rest_client=sentinel)
        orch = FakeOrchestrator({'execution': ex}, running=False)
        await run_live_mode(base_config(), orch, 'demo')
        assert ex.rest_client is sentinel
        assert ex.mock_mode is True
        assert ex.epic == 'US100', "the epic is still synced"

    @pytest.mark.asyncio
    async def test_the_stop_manager_gets_the_risk_config_and_pip_size(self, broker):
        cfg = base_config(risk={'pip_size': 0.0001})
        await run_live_mode(cfg, FakeOrchestrator(running=False), 'demo')
        sm = FakeStopManager.instances[0]
        assert sm.pip_size == 0.0001
        assert sm.capital_client is FakeCapital.instances[0]

    @pytest.mark.asyncio
    async def test_pip_size_falls_back_to_analysis_sl_tp(self, broker):
        cfg = base_config(risk={}, analysis={'sl_tp': {'pip_size': 0.1}})
        await run_live_mode(cfg, FakeOrchestrator(running=False), 'demo')
        assert FakeStopManager.instances[0].pip_size == 0.1


# ──────────────────────────────────────────────────────────────────────────
# Restoring a position left open by the previous process
# ──────────────────────────────────────────────────────────────────────────

class TestPositionRestore:

    @staticmethod
    def pos(deal_id='D1', epic='US100', direction='BUY'):
        return {'market': {'epic': epic},
                'position': {'dealId': deal_id, 'direction': direction}}

    @pytest.mark.asyncio
    async def test_an_open_position_blocks_new_entries(self, broker):
        risk = FakeRisk()
        orch = FakeOrchestrator({'risk': risk}, running=False)
        FakeCapital.instances.clear()

        class Seeded(FakeCapital):
            def __init__(self, **kw):
                super().__init__(**kw)
                self.positions = [TestPositionRestore.pos('D1', direction='SELL')]

        import clients.capital_api as m
        m.CapitalAPIClient = Seeded
        try:
            await run_live_mode(base_config(), orch, 'demo')
        finally:
            m.CapitalAPIClient = FakeCapital
        assert risk.has_open_position is True
        assert risk.open_position_deal_id == 'D1'
        assert risk.open_position_direction == 'SELL'

    @pytest.mark.asyncio
    async def test_restoring_a_position_arms_the_startup_flip_gate(self, broker):
        """
        Already in a position means the trend question is settled, so entries
        must resume normally once it closes rather than waiting for a flip.
        """
        risk = FakeRisk()
        orch = FakeOrchestrator({'risk': risk}, running=False)

        class Seeded(FakeCapital):
            def __init__(self, **kw):
                super().__init__(**kw)
                self.positions = [TestPositionRestore.pos('D1')]

        import clients.capital_api as m
        m.CapitalAPIClient = Seeded
        try:
            await run_live_mode(base_config(), orch, 'demo')
        finally:
            m.CapitalAPIClient = FakeCapital
        assert risk._startup_flip_seen is True

    @pytest.mark.asyncio
    async def test_the_last_position_is_the_canonical_one(self, broker):
        risk = FakeRisk()
        orch = FakeOrchestrator({'risk': risk}, running=False)

        class Seeded(FakeCapital):
            def __init__(self, **kw):
                super().__init__(**kw)
                self.positions = [TestPositionRestore.pos('D1'),
                                  TestPositionRestore.pos('D2')]

        import clients.capital_api as m
        m.CapitalAPIClient = Seeded
        try:
            await run_live_mode(base_config(), orch, 'demo')
        finally:
            m.CapitalAPIClient = FakeCapital
        assert risk.open_position_deal_id == 'D2'

    @pytest.mark.asyncio
    async def test_positions_on_other_epics_are_ignored(self, broker):
        risk = FakeRisk()
        orch = FakeOrchestrator({'risk': risk}, running=False)

        class Seeded(FakeCapital):
            def __init__(self, **kw):
                super().__init__(**kw)
                self.positions = [TestPositionRestore.pos('D1', epic='GOLD')]

        import clients.capital_api as m
        m.CapitalAPIClient = Seeded
        try:
            await run_live_mode(base_config(), orch, 'demo')
        finally:
            m.CapitalAPIClient = FakeCapital
        assert risk.has_open_position is False
        assert risk._startup_flip_seen is False

    @pytest.mark.asyncio
    async def test_a_failed_position_check_assumes_none_open(self, broker):
        risk = FakeRisk()
        orch = FakeOrchestrator({'risk': risk}, running=False)

        class Boom(FakeCapital):
            def __init__(self, **kw):
                super().__init__(**kw)
                self.positions_raises = True

        import clients.capital_api as m
        m.CapitalAPIClient = Boom
        try:
            await run_live_mode(base_config(), orch, 'demo')
        finally:
            m.CapitalAPIClient = FakeCapital
        assert risk.has_open_position is False

    @pytest.mark.asyncio
    async def test_no_risk_skill_is_tolerated(self, broker):
        class Seeded(FakeCapital):
            def __init__(self, **kw):
                super().__init__(**kw)
                self.positions = [TestPositionRestore.pos('D1')]

        import clients.capital_api as m
        m.CapitalAPIClient = Seeded
        try:
            await run_live_mode(base_config(), FakeOrchestrator(running=False), 'demo')
        finally:
            m.CapitalAPIClient = FakeCapital


# ──────────────────────────────────────────────────────────────────────────
# Warm-up
# ──────────────────────────────────────────────────────────────────────────

class TestWarmup:

    @pytest.mark.asyncio
    async def test_m5_warmup_is_the_largest_period_times_the_multiplier(self, broker):
        """
        max(sma_slow 30, bb 20, st 14, macd 26+9=35, rsi 14, stoch 14) = 35,
        x WARMUP_MULTIPLIER (3) = 105.
        """
        a = FakeAnalysis()
        orch = FakeOrchestrator({'analysis': a}, running=False)
        await run_live_mode(base_config(), orch, 'demo')
        m5 = [c for c in FakeCapital.instances[0].price_calls
              if c['resolution'] == 'MINUTE_5']
        assert m5[0]['max_bars'] == 105

    @pytest.mark.asyncio
    async def test_m5_warmup_is_capped_at_the_api_maximum(self, broker):
        """Capital.com returns at most 1000 bars per request."""
        a = FakeAnalysis()
        a.sma_slow_period = 5000
        orch = FakeOrchestrator({'analysis': a}, running=False)
        await run_live_mode(base_config(), orch, 'demo')
        m5 = [c for c in FakeCapital.instances[0].price_calls
              if c['resolution'] == 'MINUTE_5']
        assert m5[0]['max_bars'] == 1000

    @pytest.mark.asyncio
    async def test_the_default_warmup_applies_without_an_analysis_skill(self, broker):
        orch = FakeOrchestrator(running=False)
        await run_live_mode(base_config(), orch, 'demo')
        m5 = [c for c in FakeCapital.instances[0].price_calls
              if c['resolution'] == 'MINUTE_5']
        assert m5[0]['max_bars'] == 300

    @pytest.mark.asyncio
    async def test_the_market_data_buffer_is_grown_to_hold_the_warmup(self, broker):
        """CLAUDE.md gotcha 2 — buffer_size is overridden at runtime."""
        md = FakeMarketData()
        orch = FakeOrchestrator({'analysis': FakeAnalysis(), 'market_data': md},
                                running=False)
        await run_live_mode(base_config(), orch, 'demo')
        assert md.buffer_size == 105

    @pytest.mark.asyncio
    async def test_history_is_replayed_with_warming_up_set(self, broker):
        """
        Warm-up must buffer candles WITHOUT generating signals or orders, so
        orchestrator.warming_up has to be True for every replayed candle.
        """
        class Seeded(FakeCapital):
            def __init__(self, **kw):
                super().__init__(**kw)
                self.history = {'MINUTE_5': [candle(i) for i in range(4)]}

        import clients.capital_api as m
        m.CapitalAPIClient = Seeded
        orch = FakeOrchestrator({'analysis': FakeAnalysis()}, running=False)
        try:
            await run_live_mode(base_config(), orch, 'demo')
        finally:
            m.CapitalAPIClient = FakeCapital
        assert len(orch.candles) == 4
        assert all(orch.warming_flags), "signals must stay suppressed during replay"
        assert orch.warming_up is False, "and the flag must be cleared afterwards"

    @pytest.mark.asyncio
    async def test_a_failed_prefetch_still_clears_the_warming_flag(self, broker):
        """
        If `warming_up` stayed True the bot would run forever without trading.
        """
        class Boom(FakeCapital):
            def __init__(self, **kw):
                super().__init__(**kw)
                self.history_raises = {'MINUTE_5'}

        import clients.capital_api as m
        m.CapitalAPIClient = Boom
        orch = FakeOrchestrator({'analysis': FakeAnalysis()}, running=False)
        try:
            await run_live_mode(base_config(), orch, 'demo')
        finally:
            m.CapitalAPIClient = FakeCapital
        assert orch.warming_up is False

    @pytest.mark.asyncio
    async def test_the_timeframe_maps_to_a_capital_resolution(self, broker):
        cfg = base_config(market_data={'timeframe': 'M15'})
        orch = FakeOrchestrator({'analysis': FakeAnalysis()}, running=False)
        await run_live_mode(cfg, orch, 'demo')
        assert any(c['resolution'] == 'MINUTE_15'
                   for c in FakeCapital.instances[0].price_calls)

    @pytest.mark.asyncio
    async def test_an_unknown_timeframe_falls_back_to_m5(self, broker):
        cfg = base_config(market_data={'timeframe': 'W1'})
        orch = FakeOrchestrator({'analysis': FakeAnalysis()}, running=False)
        await run_live_mode(cfg, orch, 'demo')
        assert any(c['resolution'] == 'MINUTE_5'
                   for c in FakeCapital.instances[0].price_calls)


class TestHigherTimeframeWarmup:

    @pytest.mark.asyncio
    async def test_h1_is_not_fetched_when_the_gate_is_off(self, broker):
        orch = FakeOrchestrator({'analysis': FakeAnalysis()}, running=False)
        await run_live_mode(base_config(), orch, 'demo')
        assert not any(c['resolution'] == 'HOUR'
                       for c in FakeCapital.instances[0].price_calls)

    @pytest.mark.asyncio
    async def test_h1_is_fetched_and_loaded_when_required(self, broker):
        class Seeded(FakeCapital):
            def __init__(self, **kw):
                super().__init__(**kw)
                self.history = {'HOUR': [candle(i) for i in range(3)]}

        import clients.capital_api as m
        m.CapitalAPIClient = Seeded
        a = FakeAnalysis(require_h1_bb=True)
        orch = FakeOrchestrator({'analysis': a}, running=False)
        try:
            await run_live_mode(base_config(), orch, 'demo')
        finally:
            m.CapitalAPIClient = FakeCapital
        h1 = [c for c in FakeCapital.instances[0].price_calls
              if c['resolution'] == 'HOUR']
        assert h1[0]['max_bars'] == 60      # mtf_h1_bb_period 20 x 3
        assert len(a.h1_loaded) == 3

    @pytest.mark.asyncio
    async def test_a_failed_h1_fetch_leaves_the_gate_unloaded(self, broker):
        class Boom(FakeCapital):
            def __init__(self, **kw):
                super().__init__(**kw)
                self.history_raises = {'HOUR'}

        import clients.capital_api as m
        m.CapitalAPIClient = Boom
        a = FakeAnalysis(require_h1_bb=True)
        orch = FakeOrchestrator({'analysis': a}, running=False)
        try:
            await run_live_mode(base_config(), orch, 'demo')
        finally:
            m.CapitalAPIClient = FakeCapital
        assert a.h1_loaded is None

    @pytest.mark.asyncio
    async def test_daily_is_fetched_and_loaded_when_required(self, broker):
        class Seeded(FakeCapital):
            def __init__(self, **kw):
                super().__init__(**kw)
                self.history = {'DAY': [candle(i) for i in range(2)]}

        import clients.capital_api as m
        m.CapitalAPIClient = Seeded
        a = FakeAnalysis(require_daily_bias=True)
        orch = FakeOrchestrator({'analysis': a}, running=False)
        try:
            await run_live_mode(base_config(), orch, 'demo')
        finally:
            m.CapitalAPIClient = FakeCapital
        day = [c for c in FakeCapital.instances[0].price_calls
               if c['resolution'] == 'DAY']
        assert day[0]['max_bars'] == 60     # mtf_daily_sma 20 x 3
        assert len(a.daily_loaded) == 2

    @pytest.mark.asyncio
    async def test_a_failed_daily_fetch_leaves_the_gate_unloaded(self, broker):
        class Boom(FakeCapital):
            def __init__(self, **kw):
                super().__init__(**kw)
                self.history_raises = {'DAY'}

        import clients.capital_api as m
        m.CapitalAPIClient = Boom
        a = FakeAnalysis(require_daily_bias=True)
        orch = FakeOrchestrator({'analysis': a}, running=False)
        try:
            await run_live_mode(base_config(), orch, 'demo')
        finally:
            m.CapitalAPIClient = FakeCapital
        assert a.daily_loaded is None


# ──────────────────────────────────────────────────────────────────────────
# WebSocket loop
# ──────────────────────────────────────────────────────────────────────────

class TestWebSocketLoop:

    @pytest.mark.asyncio
    async def test_a_clean_run_connects_and_subscribes(self, broker):
        orch = FakeOrchestrator({'analysis': FakeAnalysis()}, running=True)
        ws_holder = []

        class OneShot(FakeWS):
            async def run(self):
                orch.running = False      # exit the reconnect loop after one pass
                ws_holder.append(self)

        import clients.capital_websocket as m
        m.CapitalWebSocketClient = OneShot
        try:
            await run_live_mode(base_config(), orch, 'demo')
        finally:
            m.CapitalWebSocketClient = FakeWS
        ws = ws_holder[0]
        assert ws.connected is True
        assert ws.ohlc_subs[0] == (('US100',), 'MINUTE_5')
        assert ws.quote_subs == [('US100',)]

    @pytest.mark.asyncio
    async def test_tokens_are_refreshed_before_each_connect(self, broker):
        orch = FakeOrchestrator(running=True)

        class OneShot(FakeWS):
            async def run(self):
                orch.running = False

        import clients.capital_websocket as m
        m.CapitalWebSocketClient = OneShot
        try:
            await run_live_mode(base_config(), orch, 'demo')
        finally:
            m.CapitalWebSocketClient = FakeWS
        # once at authentication, once before the connect attempt
        assert FakeCapital.instances[0].token_calls == 2

    @pytest.mark.asyncio
    async def test_the_session_tokens_are_handed_to_the_socket(self, broker):
        orch = FakeOrchestrator(running=True)
        holder = []

        class OneShot(FakeWS):
            async def run(self):
                orch.running = False
                holder.append(self)

        import clients.capital_websocket as m
        m.CapitalWebSocketClient = OneShot
        try:
            await run_live_mode(base_config(), orch, 'demo')
        finally:
            m.CapitalWebSocketClient = FakeWS
        assert holder[0].cst == 'cst-tok'
        assert holder[0].security_token == 'sec-tok'

    @pytest.mark.asyncio
    async def test_an_h1_subscription_is_added_only_when_the_gate_is_on(self, broker):
        orch = FakeOrchestrator({'analysis': FakeAnalysis(require_h1_bb=True)},
                                running=True)
        holder = []

        class OneShot(FakeWS):
            async def run(self):
                orch.running = False
                holder.append(self)

        import clients.capital_websocket as m
        m.CapitalWebSocketClient = OneShot
        try:
            await run_live_mode(base_config(), orch, 'demo')
        finally:
            m.CapitalWebSocketClient = FakeWS
        assert holder[0].ohlc_subs == [(('US100',), 'MINUTE_5'),
                                       (('US100',), 'HOUR')]

    @pytest.mark.asyncio
    async def test_a_dropped_socket_is_retried_then_gives_up_on_shutdown(self, broker):
        orch = FakeOrchestrator(running=True)
        attempts = []

        class Flaky(FakeWS):
            async def run(self):
                attempts.append(1)
                if len(attempts) >= 3:
                    orch.running = False
                    return
                raise RuntimeError('ws dropped')

        import clients.capital_websocket as m
        m.CapitalWebSocketClient = Flaky
        try:
            await run_live_mode(base_config(), orch, 'demo')
        finally:
            m.CapitalWebSocketClient = FakeWS
        assert len(attempts) == 3, "must reconnect after a drop"

    @pytest.mark.asyncio
    async def test_cancellation_breaks_the_reconnect_loop(self, broker):
        orch = FakeOrchestrator(running=True)

        class Cancelled(FakeWS):
            async def run(self):
                raise asyncio.CancelledError()

        import clients.capital_websocket as m
        m.CapitalWebSocketClient = Cancelled
        try:
            # must RETURN, not raise, and must not spin forever
            await asyncio.wait_for(
                run_live_mode(base_config(), orch, 'demo'), timeout=5)
        finally:
            m.CapitalWebSocketClient = FakeWS

    @pytest.mark.asyncio
    async def test_a_stopped_orchestrator_never_connects(self, broker):
        orch = FakeOrchestrator(running=False)
        await run_live_mode(base_config(), orch, 'demo')
        assert FakeWS.instances == []


class TestStreamCallbacks:
    """
    The three callbacks wired onto the socket are where live data actually
    enters the system, so they are driven directly here.
    """

    async def _connected_ws(self, cfg, orch):
        holder = []

        class Capture(FakeWS):
            async def run(self):
                orch.running = False
                holder.append(self)

        import clients.capital_websocket as m
        m.CapitalWebSocketClient = Capture
        try:
            await run_live_mode(cfg, orch, 'demo')
        finally:
            m.CapitalWebSocketClient = FakeWS
        return holder[0]

    @pytest.mark.asyncio
    async def test_a_streamed_candle_reaches_the_orchestrator(self, broker):
        orch = FakeOrchestrator(running=True)
        ws = await self._connected_ws(base_config(), orch)
        before = len(orch.candles)
        await ws.on_candle({'time': datetime(2026, 10, 21, 14, 5), 'open': 1.0,
                            'high': 2.0, 'low': 0.5, 'close': 1.5})
        assert len(orch.candles) == before + 1
        c = orch.candles[-1]
        assert c['timestamp'] == '2026-10-21T14:05:00'
        assert (c['open'], c['high'], c['low'], c['close']) == (1.0, 2.0, 0.5, 1.5)
        assert c['volume'] == 0

    @pytest.mark.asyncio
    async def test_a_candle_without_a_time_gets_an_empty_timestamp(self, broker):
        orch = FakeOrchestrator(running=True)
        ws = await self._connected_ws(base_config(), orch)
        await ws.on_candle({'close': 1.5})
        assert orch.candles[-1]['timestamp'] == ''

    @pytest.mark.asyncio
    async def test_an_h1_candle_updates_the_analysis_skill(self, broker):
        class Recording(FakeAnalysis):
            def __init__(self):
                super().__init__()
                self.h1_updates = []

            def update_h1_candle(self, candle):
                self.h1_updates.append(candle)

        a = Recording()
        orch = FakeOrchestrator({'analysis': a}, running=True)
        ws = await self._connected_ws(base_config(), orch)
        await ws.on_h1_candle({'time': datetime(2026, 10, 21, 14, 0),
                               'open': 1, 'high': 2, 'low': 0, 'close': 1.5})
        assert a.h1_updates[-1]['close'] == 1.5

    @pytest.mark.asyncio
    async def test_an_h1_candle_without_an_analysis_skill_is_a_noop(self, broker):
        orch = FakeOrchestrator(running=True)
        ws = await self._connected_ws(base_config(), orch)
        await ws.on_h1_candle({'close': 1.5})      # must not raise

    @pytest.mark.asyncio
    async def test_a_quote_drives_the_tick_exit_and_the_stop_manager(self, broker):
        a = FakeAnalysis()
        orch = FakeOrchestrator({'analysis': a}, running=True)
        ws = await self._connected_ws(base_config(), orch)
        await ws.on_quote({'mid': 29500.0, 'time': 'T'})
        assert a.ticks == [(29500.0, 'T')]
        assert FakeStopManager.instances[0].prices == [29500.0]

    @pytest.mark.asyncio
    async def test_a_quote_without_a_mid_is_ignored(self, broker):
        a = FakeAnalysis()
        orch = FakeOrchestrator({'analysis': a}, running=True)
        ws = await self._connected_ws(base_config(), orch)
        await ws.on_quote({})
        assert a.ticks == []
        assert FakeStopManager.instances[0].prices == []

    @pytest.mark.asyncio
    async def test_a_zero_mid_is_ignored(self, broker):
        a = FakeAnalysis()
        orch = FakeOrchestrator({'analysis': a}, running=True)
        ws = await self._connected_ws(base_config(), orch)
        await ws.on_quote({'mid': 0})
        assert a.ticks == []

    @pytest.mark.asyncio
    async def test_a_quote_still_ratchets_the_stop_without_analysis(self, broker):
        orch = FakeOrchestrator(running=True)
        ws = await self._connected_ws(base_config(), orch)
        await ws.on_quote({'mid': 100.0})
        assert FakeStopManager.instances[0].prices == [100.0]


# ──────────────────────────────────────────────────────────────────────────
# main() — CLI parsing, config overlay, dispatch
# ──────────────────────────────────────────────────────────────────────────

@pytest.fixture
def cli(monkeypatch, tmp_path):
    """
    Drive main() with a temp config, a recording orchestrator, and
    run_live_mode / setup_logging stubbed out.
    """
    cfg_path = tmp_path / 'trading_config.yaml'
    cfg_path.write_text(
        'bot:\n  name: Gold M5 Bot\n'
        'execution:\n  epic: GOLD\n'
        'market_data:\n  timeframe: M5\n'
    )

    seen = {}
    orchs = []

    class Orch(FakeOrchestrator):
        def __init__(self, config):
            super().__init__({}, running=False)
            self.config = config
            orchs.append(self)

    async def fake_live(config, orchestrator, environment):
        seen['config'] = config
        seen['environment'] = environment

    monkeypatch.setattr(main_mod, 'TradingOrchestrator', Orch)
    monkeypatch.setattr(main_mod, 'run_live_mode', fake_live)
    monkeypatch.setattr(main_mod, 'register_skills',
                        lambda o, c, mode, bot_id=None: seen.update(
                            {'mode': mode, 'bot_id': bot_id}))
    monkeypatch.setattr(main_mod, 'setup_logging',
                        lambda c, bot_id, run_id: seen.update(
                            {'log_bot_id': bot_id, 'run_id': run_id}))

    def run(*argv):
        monkeypatch.setattr(sys, 'argv',
                            ['main.py', '--config', str(cfg_path), *argv])
        return seen, orchs

    return run


class TestMainEntry:

    @pytest.mark.asyncio
    async def test_demo_is_the_default_mode(self, cli):
        seen, _ = cli()
        await main_entry()
        assert seen['environment'] == 'demo'
        assert seen['mode'] == 'demo'

    @pytest.mark.asyncio
    async def test_live_mode_maps_to_the_live_environment(self, cli):
        seen, _ = cli('--mode', 'live')
        await main_entry()
        assert seen['environment'] == 'live'

    @pytest.mark.asyncio
    async def test_backtest_mode_does_not_start_the_live_loop(self, cli):
        seen, _ = cli('--mode', 'backtest')
        await main_entry()
        assert 'environment' not in seen

    @pytest.mark.asyncio
    async def test_bot_id_is_derived_from_the_config_name(self, cli):
        seen, _ = cli()
        await main_entry()
        assert seen['bot_id'] == 'gold_m5_bot'

    @pytest.mark.asyncio
    async def test_an_explicit_bot_id_wins(self, cli):
        seen, _ = cli('--bot-id', 'ethusd_m5_bot')
        await main_entry()
        assert seen['bot_id'] == 'ethusd_m5_bot'
        assert seen['log_bot_id'] == 'ethusd_m5_bot'

    @pytest.mark.asyncio
    async def test_the_instrument_override_sets_market_data(self, cli):
        seen, _ = cli('--instrument', 'us100')
        await main_entry()
        assert seen['config']['market_data']['instrument'] == 'US100'

    @pytest.mark.asyncio
    async def test_the_instrument_overlay_is_deep_merged(self, cli):
        """
        config/instruments/US100.yaml exists in the repo, so this exercises the
        real overlay: its `risk` block must win over the base config.
        """
        seen, _ = cli('--instrument', 'US100')
        await main_entry()
        assert seen['config']['execution']['epic'] == 'US100', \
            "the instrument overlay must override the base epic"

    @pytest.mark.asyncio
    async def test_an_unknown_instrument_has_no_overlay_file(self, cli):
        seen, _ = cli('--instrument', 'NOSUCHTHING')
        await main_entry()
        assert seen['config']['market_data']['instrument'] == 'NOSUCHTHING'
        assert seen['config']['execution']['epic'] == 'GOLD'   # base untouched

    @pytest.mark.asyncio
    async def test_the_timeframe_override_is_upper_cased(self, cli):
        seen, _ = cli('--timeframe', 'm15')
        await main_entry()
        assert seen['config']['market_data']['timeframe'] == 'M15'

    @pytest.mark.asyncio
    async def test_the_quantity_override_reaches_risk_and_execution(self, cli):
        """
        CLAUDE.md gotcha 26 — size has to land in BOTH sections or
        execution_skill's 0.5 default wins.
        """
        seen, _ = cli('--quantity', '10')
        await main_entry()
        assert seen['config']['execution']['position_size'] == 10.0
        assert seen['config']['risk']['position_size'] == 10.0

    @pytest.mark.asyncio
    async def test_no_quantity_leaves_position_size_unset(self, cli):
        seen, _ = cli()
        await main_entry()
        assert 'position_size' not in seen['config'].get('execution', {})

    @pytest.mark.asyncio
    async def test_the_orchestrator_is_started_and_stopped(self, cli):
        _, orchs = cli()
        await main_entry()
        assert orchs[0].started == 1
        assert orchs[0].stopped == 1

    @pytest.mark.asyncio
    async def test_the_orchestrator_is_stopped_even_when_the_loop_raises(
            self, cli, monkeypatch):
        _, orchs = cli()

        async def boom(config, orchestrator, environment):
            raise KeyboardInterrupt()

        monkeypatch.setattr(main_mod, 'run_live_mode', boom)
        await main_entry()
        assert orchs[0].stopped == 1, "shutdown must run in the finally block"

    @pytest.mark.asyncio
    async def test_a_log_publisher_is_flushed_on_shutdown(self, cli):
        class Pub:
            def __init__(self):
                self.stopped = 0

            def stop_batch_writer(self):
                self.stopped += 1

        pub = Pub()
        root = logging.getLogger()
        root.firestore_log_publisher = pub
        try:
            cli()
            await main_entry()
            assert pub.stopped == 1
        finally:
            del root.firestore_log_publisher

    @pytest.mark.asyncio
    async def test_the_run_id_is_a_timestamp(self, cli):
        seen, _ = cli()
        await main_entry()
        datetime.strptime(seen['run_id'], '%Y%m%d_%H%M%S')


class TestSetupLogging:

    def test_storage_disabled_attaches_no_handler(self):
        before = len(logging.getLogger().handlers)
        main_mod.setup_logging({'storage': {'enabled': False}},
                               bot_id='b', run_id='r')
        assert len(logging.getLogger().handlers) == before

    def test_a_failing_publisher_does_not_raise(self, monkeypatch):
        """
        Log streaming is best-effort: a broken publisher must not stop the bot
        from starting.
        """
        import clients.log_publisher as lp
        monkeypatch.setattr(lp, 'LogPublisher',
                            lambda **kw: (_ for _ in ()).throw(RuntimeError('no db')))
        main_mod.setup_logging({'storage': {'enabled': True}},
                               bot_id='b', run_id='r')


# ──────────────────────────────────────────────────────────────────────────
# Candle watchdog
# ──────────────────────────────────────────────────────────────────────────

class ClockStub:
    """
    Stands in for `datetime` inside orchestrator.main so utcnow() can be
    advanced on demand. Only utcnow() is overridden; everything else is
    delegated to the real class.
    """

    def __init__(self, start, step_seconds=0):
        self.now = start
        self.step = step_seconds

    def utcnow(self):
        value = self.now
        self.now = self.now + __import__('datetime').timedelta(seconds=self.step)
        return value

    def __getattr__(self, name):
        return getattr(datetime, name)


class TestCandleWatchdog:
    """
    Capital.com silently drops OHLC subscriptions without closing the socket:
    the keepalive ping keeps answering while candles stop arriving. The
    watchdog is the only thing that notices, so a bot can otherwise sit
    "connected" and untrading indefinitely.
    """

    @pytest.mark.asyncio
    async def test_a_candle_drought_closes_the_socket_to_force_a_reconnect(
            self, broker, monkeypatch):
        import datetime as dt
        # Weekday (Wednesday 2026-10-21), and each utcnow() reading jumps 10 min,
        # so `elapsed` passes the 900s threshold within a couple of loop passes.
        monkeypatch.setattr(
            main_mod, 'datetime',
            ClockStub(dt.datetime(2026, 10, 21, 12, 0), step_seconds=600))

        orch = FakeOrchestrator(running=True)
        closed = []

        class Hanging(FakeWS):
            async def run(self):
                # Block until the watchdog closes us, then end the reconnect loop
                for _ in range(500):
                    await asyncio.sleep(0)
                    if self.closed:
                        break
                orch.running = False

            async def close(self):
                self.closed += 1
                closed.append(1)

        import clients.capital_websocket as m
        m.CapitalWebSocketClient = Hanging
        try:
            await asyncio.wait_for(
                run_live_mode(base_config(), orch, 'demo'), timeout=10)
        finally:
            m.CapitalWebSocketClient = FakeWS
        assert closed, "the watchdog must close the socket after a candle drought"

    @pytest.mark.asyncio
    async def test_the_weekend_is_exempt(self, broker, monkeypatch):
        """
        Saturday/Sunday have no data, so a drought there is not a fault.

        The clock starts Saturday 2026-10-24 00:00 and advances 10 min per
        reading; the run loop is bounded to 100 yields, so the stub never
        leaves the weekend. Elapsed therefore exceeds the 900s threshold many
        times over and only the weekday guard prevents a close — if that guard
        were removed this test would fail.
        """
        import datetime as dt
        clock = ClockStub(dt.datetime(2026, 10, 24, 0, 0), step_seconds=600)
        monkeypatch.setattr(main_mod, 'datetime', clock)

        orch = FakeOrchestrator(running=True)
        holder = []

        class Hanging(FakeWS):
            async def run(self):
                holder.append(self)
                for _ in range(100):
                    await asyncio.sleep(0)
                    if self.closed:
                        break
                orch.running = False

        import clients.capital_websocket as m
        m.CapitalWebSocketClient = Hanging
        try:
            await asyncio.wait_for(
                run_live_mode(base_config(), orch, 'demo'), timeout=10)
        finally:
            m.CapitalWebSocketClient = FakeWS
        assert clock.now.weekday() >= 5, "the stub must stay on the weekend"
        assert holder[0].closed == 0, "no reconnect should be forced at the weekend"

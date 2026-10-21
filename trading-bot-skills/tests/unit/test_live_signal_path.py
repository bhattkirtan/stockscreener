"""
Unit tests — LIVE signal path, driven as the live bot actually receives data.

Why this file exists separately from the backtest tests: the backtester feeds a
complete, clean, strictly-ordered DataFrame to vectorised code. The live bot
receives a WebSocket stream and the dynamics are materially different:

  * Capital.com pushes BOTH a BID and an ASK/OFR candle for every bar, so every
    bar arrives at least twice and only one of them may be acted on.
  * Updates can repeat for the same bar.
  * Messages can arrive out of order or be re-sent after a reconnect.
  * The analysis buffer is a rolling window rebuilt from whatever arrived, not
    the full history.
  * Quotes arrive between bars and drive stop management independently.

A live/backtest divergence was measured on 2026-10-21 (GOLD took 93 live trades
against 61 in the backtest over the same window, with a materially worse win
rate) and is still unexplained. These tests drive the real event path bar by
bar so that class of defect is observable.
"""
import asyncio
import os
import sys
from datetime import datetime, timedelta

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from clients.capital_websocket import CapitalWebSocketClient
from core.event_bus import Event, EventBus, EventType
from skills.market_data.market_data_skill import M5toM15Aggregator, MarketDataSkill


# ──────────────────────────────────────────────────────────────────────────
# Helpers that mimic the wire format
# ──────────────────────────────────────────────────────────────────────────
def ohlc_payload(epic='GOLD', ts_ms=None, o=4100.0, h=4105.0, l=4095.0, c=4102.0,
                 price_type='ASK', resolution='MINUTE_5'):
    """A single OHLCMarketData.subscribe payload as it arrives on the wire."""
    if ts_ms is None:
        ts_ms = int(datetime(2026, 10, 21, 10, 0).timestamp() * 1000)
    return {'epic': epic, 'resolution': resolution, 'o': o, 'h': h, 'l': l,
            'c': c, 'priceType': price_type, 't': ts_ms}


def m5_candle(minute_offset=0, close=4100.0, base_hour=10, day=21):
    ts = datetime(2026, 10, day, base_hour, 0) + timedelta(minutes=minute_offset)
    return {'timestamp': ts, 'open': close - 1.0, 'high': close + 2.0,
            'low': close - 2.0, 'close': close, 'volume': 100}


class Recorder:
    """Captures events published on the bus."""

    def __init__(self):
        self.events = []

    async def __call__(self, event):
        self.events.append(event)

    @property
    def candles(self):
        return [e.payload.get('candle') for e in self.events]


def make_md_skill(bus, timeframe='M5', buffer_size=500, dedup=True):
    return MarketDataSkill({
        'enabled': True, 'instrument': 'GOLD', 'timeframe': timeframe,
        'buffer_size': buffer_size, 'dedup_enabled': dedup,
    }, event_bus=bus)


# ──────────────────────────────────────────────────────────────────────────
# WebSocket ingest — the first place live differs from backtest
# ──────────────────────────────────────────────────────────────────────────
class TestWebSocketOhlcIngest:

    def _client(self):
        c = CapitalWebSocketClient.__new__(CapitalWebSocketClient)
        c.latest_candles, c.latest_quotes = {}, {}
        c.on_quote = c.on_candle = c.on_h1_candle = None
        return c

    @pytest.mark.asyncio
    async def test_bid_candles_are_not_acted_on(self):
        """
        Every bar arrives twice — once BID, once ASK/OFR. Acting on both would
        double every signal. Only ASK/OFR may reach the strategy.
        """
        c = self._client()
        seen = []
        c.on_candle = lambda d: asyncio.sleep(0, result=seen.append(d))
        await c._handle_ohlc(ohlc_payload(price_type='BID'))
        assert seen == []
        await c._handle_ohlc(ohlc_payload(price_type='ASK'))
        assert len(seen) == 1

    @pytest.mark.asyncio
    async def test_ofr_is_treated_as_ask(self):
        c = self._client()
        seen = []
        c.on_candle = lambda d: asyncio.sleep(0, result=seen.append(d))
        await c._handle_ohlc(ohlc_payload(price_type='OFR'))
        assert len(seen) == 1

    @pytest.mark.asyncio
    async def test_price_type_matching_is_case_insensitive(self):
        c = self._client()
        seen = []
        c.on_candle = lambda d: asyncio.sleep(0, result=seen.append(d))
        await c._handle_ohlc(ohlc_payload(price_type='ask'))
        assert len(seen) == 1

    @pytest.mark.asyncio
    async def test_hour_resolution_routes_to_the_h1_handler(self):
        """H1 feeds the MTF filters, not the M5 strategy."""
        c = self._client()
        m5, h1 = [], []
        c.on_candle = lambda d: asyncio.sleep(0, result=m5.append(d))
        c.on_h1_candle = lambda d: asyncio.sleep(0, result=h1.append(d))
        await c._handle_ohlc(ohlc_payload(resolution='HOUR'))
        assert len(h1) == 1 and m5 == []

    @pytest.mark.asyncio
    async def test_latest_candle_is_cached_even_for_bid(self):
        """The cache is a snapshot of the feed, independent of routing."""
        c = self._client()
        await c._handle_ohlc(ohlc_payload(price_type='BID', c=4111.0))
        assert c.get_latest_candle('GOLD')['close'] == 4111.0

    @pytest.mark.asyncio
    async def test_missing_callback_does_not_raise(self):
        """A bar arriving before wiring completes must not kill the stream."""
        c = self._client()
        await c._handle_ohlc(ohlc_payload())   # on_candle is None

    @pytest.mark.asyncio
    async def test_timestamp_is_converted(self):
        c = self._client()
        ts = int(datetime(2026, 10, 21, 10, 5).timestamp() * 1000)
        await c._handle_ohlc(ohlc_payload(ts_ms=ts))
        assert c.get_latest_candle('GOLD')['time'] == datetime.fromtimestamp(ts / 1000)

    @pytest.mark.asyncio
    async def test_missing_timestamp_is_tolerated(self):
        c = self._client()
        p = ohlc_payload()
        p['t'] = None
        await c._handle_ohlc(p)
        assert c.get_latest_candle('GOLD')['time'] is None


class TestWebSocketQuoteIngest:
    """Quotes drive stop management and tick exit between bars."""

    def _client(self):
        c = CapitalWebSocketClient.__new__(CapitalWebSocketClient)
        c.latest_candles, c.latest_quotes = {}, {}
        c.on_quote = c.on_candle = c.on_h1_candle = None
        return c

    @pytest.mark.asyncio
    async def test_quote_is_cached_and_forwarded(self):
        c = self._client()
        seen = []
        c.on_quote = lambda d: asyncio.sleep(0, result=seen.append(d))
        await c._handle_quote({'epic': 'GOLD', 'bid': 4100.0, 'ofr': 4100.5,
                               'timestamp': 1})
        assert len(seen) == 1
        assert c.get_latest_quote('GOLD') is not None

    @pytest.mark.asyncio
    async def test_quote_without_handler_does_not_raise(self):
        c = self._client()
        await c._handle_quote({'epic': 'GOLD', 'bid': 4100.0, 'ofr': 4100.5})


# ──────────────────────────────────────────────────────────────────────────
# MarketDataSkill — dedup, buffering, ordering
# ──────────────────────────────────────────────────────────────────────────
class TestCandleDedup:

    @pytest.mark.asyncio
    async def test_consecutive_duplicate_is_suppressed(self):
        """
        The broker can re-send the same bar. A second CANDLE_CLOSED for one bar
        would run the strategy twice on identical data.
        """
        bus, rec = EventBus(fast_mode=True), Recorder()
        bus.subscribe(EventType.CANDLE_CLOSED, rec)
        md = make_md_skill(bus)
        c = m5_candle()
        await md.process_candle(c)
        await md.process_candle(c)
        assert len(rec.events) == 1

    @pytest.mark.asyncio
    async def test_distinct_bars_both_publish(self):
        bus, rec = EventBus(fast_mode=True), Recorder()
        bus.subscribe(EventType.CANDLE_CLOSED, rec)
        md = make_md_skill(bus)
        await md.process_candle(m5_candle(0))
        await md.process_candle(m5_candle(5))
        assert len(rec.events) == 2

    @pytest.mark.asyncio
    async def test_non_consecutive_resend_is_NOT_suppressed(self):
        """
        Documents a real limitation: dedup tracks only the LAST timestamp, so a
        re-sent older bar (A, B, A) passes through and is appended to history a
        second time. After a reconnect replays recent bars this produces a
        duplicated bar in the analysis buffer and can fire an extra signal.
        This is a candidate explanation for the measured live/backtest trade
        count divergence.
        """
        bus, rec = EventBus(fast_mode=True), Recorder()
        bus.subscribe(EventType.CANDLE_CLOSED, rec)
        md = make_md_skill(bus)
        a, b = m5_candle(0), m5_candle(5)
        await md.process_candle(a)
        await md.process_candle(b)
        await md.process_candle(a)          # replayed after a reconnect
        assert len(rec.events) == 3, "dedup is last-timestamp-only"
        ts = [c['timestamp'] for c in md.get_candle_history()]
        assert len(ts) == 3 and ts != sorted(set(ts)), "duplicate bar in buffer"

    @pytest.mark.asyncio
    async def test_dedup_can_be_disabled(self):
        bus, rec = EventBus(fast_mode=True), Recorder()
        bus.subscribe(EventType.CANDLE_CLOSED, rec)
        md = make_md_skill(bus, dedup=False)
        c = m5_candle()
        await md.process_candle(c)
        await md.process_candle(c)
        assert len(rec.events) == 2

    @pytest.mark.asyncio
    async def test_malformed_candle_is_rejected(self):
        bus, rec = EventBus(fast_mode=True), Recorder()
        bus.subscribe(EventType.CANDLE_CLOSED, rec)
        md = make_md_skill(bus)
        await md.process_candle({'timestamp': datetime.now(), 'open': 1.0})
        assert rec.events == []

    @pytest.mark.asyncio
    async def test_out_of_order_arrival_is_sorted_into_history(self):
        """Indicators require monotonic history regardless of arrival order."""
        bus = EventBus(fast_mode=True)
        md = make_md_skill(bus)
        await md.process_candle(m5_candle(10))
        await md.process_candle(m5_candle(0))
        await md.process_candle(m5_candle(5))
        ts = [c['timestamp'] for c in md.get_candle_history()]
        assert ts == sorted(ts)

    @pytest.mark.asyncio
    async def test_buffer_is_trimmed_to_configured_size(self):
        """A live process runs for days; the buffer must not grow without bound."""
        bus = EventBus(fast_mode=True)
        md = make_md_skill(bus, buffer_size=10)
        for i in range(40):
            await md.process_candle(m5_candle(i * 5))
        assert len(md.get_candle_history()) == 10

    @pytest.mark.asyncio
    async def test_trimming_keeps_the_most_recent_bars(self):
        bus = EventBus(fast_mode=True)
        md = make_md_skill(bus, buffer_size=5)
        for i in range(20):
            await md.process_candle(m5_candle(i * 5, close=4100.0 + i))
        closes = [c['close'] for c in md.get_candle_history()]
        assert closes == [4115.0, 4116.0, 4117.0, 4118.0, 4119.0]

    @pytest.mark.asyncio
    async def test_gap_in_the_stream_does_not_break_history(self):
        """Weekend/outage gaps are normal; the skill must not interpolate."""
        bus = EventBus(fast_mode=True)
        md = make_md_skill(bus)
        await md.process_candle(m5_candle(0))
        await md.process_candle(m5_candle(0, day=24))   # 3 days later
        assert len(md.get_candle_history()) == 2

    @pytest.mark.asyncio
    async def test_no_event_bus_is_tolerated(self):
        md = make_md_skill(None)
        await md.process_candle(m5_candle())
        assert len(md.get_candle_history()) == 1


class TestM15Aggregation:
    """resample_to M15 changes when signals fire — partial bars must not publish."""

    @pytest.mark.asyncio
    async def test_partial_m15_does_not_publish(self):
        bus, rec = EventBus(fast_mode=True), Recorder()
        bus.subscribe(EventType.CANDLE_CLOSED, rec)
        md = make_md_skill(bus, timeframe='M15')
        await md.process_candle(m5_candle(0))
        await md.process_candle(m5_candle(5))
        assert rec.events == []

    @pytest.mark.asyncio
    async def test_completed_m15_publishes_once(self):
        bus, rec = EventBus(fast_mode=True), Recorder()
        bus.subscribe(EventType.CANDLE_CLOSED, rec)
        md = make_md_skill(bus, timeframe='M15')
        # 10:00, 10:05, 10:10 -> the third lands on :10, not an M15 boundary
        for off in (0, 5, 10):
            await md.process_candle(m5_candle(off))
        assert rec.events == []
        # 10:15 completes a bar on the boundary
        for off in (15, 20, 25):
            await md.process_candle(m5_candle(off))
        assert len(rec.events) == 1

    def test_aggregator_takes_ohlc_from_the_right_bars(self):
        agg = M5toM15Aggregator()
        bars = [
            {'timestamp': datetime(2026, 10, 21, 10, 5), 'open': 10.0, 'high': 12.0,
             'low': 9.0, 'close': 11.0, 'volume': 1},
            {'timestamp': datetime(2026, 10, 21, 10, 10), 'open': 11.0, 'high': 15.0,
             'low': 10.5, 'close': 14.0, 'volume': 2},
            {'timestamp': datetime(2026, 10, 21, 10, 15), 'open': 14.0, 'high': 14.5,
             'low': 8.0, 'close': 9.5, 'volume': 3},
        ]
        out = None
        for b in bars:
            out = agg.add_m5_candle(b)
        assert out['open'] == 10.0        # first bar's open
        assert out['high'] == 15.0        # max across all three
        assert out['low'] == 8.0          # min across all three
        assert out['close'] == 9.5        # last bar's close
        assert out['volume'] == 6

    def test_aggregator_accepts_iso_timestamps(self):
        """Live payloads can carry strings rather than datetimes."""
        agg = M5toM15Aggregator()
        out = None
        for minute in (5, 10, 15):
            out = agg.add_m5_candle({
                'timestamp': f'2026-10-21T10:{minute:02d}:00',
                'open': 1.0, 'high': 2.0, 'low': 0.5, 'close': 1.5, 'volume': 1})
        assert out is not None

    def test_aggregator_resets_after_emitting(self):
        agg = M5toM15Aggregator()
        for minute in (5, 10, 15):
            agg.add_m5_candle({'timestamp': datetime(2026, 10, 21, 10, minute),
                               'open': 1.0, 'high': 2.0, 'low': 0.5,
                               'close': 1.5, 'volume': 1})
        assert len(agg.m5_buffer) == 0

    def test_aggregator_needs_three_bars(self):
        agg = M5toM15Aggregator()
        assert agg.add_m5_candle({'timestamp': datetime(2026, 10, 21, 10, 15),
                                  'open': 1.0, 'high': 2.0, 'low': 0.5,
                                  'close': 1.5, 'volume': 1}) is None


# ──────────────────────────────────────────────────────────────────────────
# End to end: wire payloads -> CANDLE_CLOSED
# ──────────────────────────────────────────────────────────────────────────
class TestWireToEventChain:

    @pytest.mark.asyncio
    async def test_bid_ask_pairs_produce_one_event_per_bar(self):
        """
        The realistic stream: each bar arrives as BID then ASK. Over 10 bars
        that is 20 messages and must yield exactly 10 CANDLE_CLOSED events.
        """
        bus, rec = EventBus(fast_mode=True), Recorder()
        bus.subscribe(EventType.CANDLE_CLOSED, rec)
        md = make_md_skill(bus)

        ws = CapitalWebSocketClient.__new__(CapitalWebSocketClient)
        ws.latest_candles, ws.latest_quotes = {}, {}
        ws.on_quote = ws.on_h1_candle = None

        async def on_candle(d):
            await md.process_candle({
                'timestamp': d['time'], 'open': d['open'], 'high': d['high'],
                'low': d['low'], 'close': d['close'], 'volume': 0})
        ws.on_candle = on_candle

        base = datetime(2026, 10, 21, 10, 0)
        for i in range(10):
            ts = int((base + timedelta(minutes=5 * i)).timestamp() * 1000)
            for pt in ('BID', 'ASK'):
                await ws._handle_ohlc(ohlc_payload(ts_ms=ts, c=4100.0 + i,
                                                   price_type=pt))
        assert len(rec.events) == 10
        assert len(md.get_candle_history()) == 10

    @pytest.mark.asyncio
    async def test_reconnect_replay_produces_extra_events(self):
        """
        Mimics a reconnect that replays the last 3 bars. Because dedup is
        last-timestamp-only, the replay is NOT fully suppressed — 13 events for
        10 distinct bars. Pinned as observed behaviour, not endorsed.
        """
        bus, rec = EventBus(fast_mode=True), Recorder()
        bus.subscribe(EventType.CANDLE_CLOSED, rec)
        md = make_md_skill(bus)
        for i in range(10):
            await md.process_candle(m5_candle(i * 5, close=4100.0 + i))
        for i in (7, 8, 9):
            await md.process_candle(m5_candle(i * 5, close=4100.0 + i))
        assert len(rec.events) == 13
        assert len(md.get_candle_history()) == 13

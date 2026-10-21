"""
Unit Tests — trade_history persistence

Regression cover for the bug where StorageSkill resolved its trades collection
from the wrong config key ('trade_history' instead of the YAML's 'trades'), and
never wrote a closed-trade record at all — leaving the live performance report
permanently empty.
"""
import json
import os
import sqlite3
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

import clients.sqlite_api as sqlite_api
from skills.storage.storage_skill import StorageSkill


@pytest.fixture
def db_path():
    path = os.path.join(tempfile.mkdtemp(), 'trading.db')
    sqlite_api.DB_PATH = path
    sqlite_api._ensure_schema()
    return path


@pytest.fixture
def skill(db_path):
    s = StorageSkill({
        'enabled': True,
        'backend': 'firestore',
        'bot_id': 'gold_m5_bot',
        'epic': 'GOLD',
        'firestore': {
            'project_id': 'test',
            'collections': {
                'positions': 'active_positions',
                'signals': 'trading_signals',
                'trades': 'trade_history',
            },
        },
    })
    # SQLiteAPIClient.__init__ resets the module global — point it back at the tmp DB
    sqlite_api.DB_PATH = db_path
    return s


def read_trades(db_path):
    con = sqlite3.connect(db_path)
    rows = con.execute(
        "SELECT doc_id, data FROM kv_store WHERE collection='trade_history'"
    ).fetchall()
    con.close()
    return {doc_id: json.loads(data) for doc_id, data in rows}


class TestCollectionResolution:

    def test_resolves_yaml_trades_key(self, skill):
        """YAML declares `trades:` — must not fall back to 'test_trades'."""
        assert skill.trades_collection == 'trade_history'

    def test_accepts_trade_history_key(self, db_path):
        s = StorageSkill({
            'firestore': {'collections': {'trade_history': 'trade_history'}},
        })
        assert s.trades_collection == 'trade_history'

    def test_defaults_without_config(self, db_path):
        s = StorageSkill({'firestore': {'collections': {}}})
        assert s.trades_collection == 'trade_history'


class TestTradeRecording:

    @pytest.mark.asyncio
    async def test_close_writes_trade_record(self, skill, db_path):
        await skill.save_open_position(
            deal_id='D1', epic='GOLD', direction='BUY', level=4000.0, size=0.5,
            stop_level=3985.0, profit_level=4045.0, opened_at='2026-07-30T10:00:00',
        )
        await skill.close_position('D1', close_price=4045.0, close_reason='TP_HIT',
                                   pnl=22.5, direction='BUY', entry_price=4000.0, size=0.5)

        trades = read_trades(db_path)
        assert list(trades) == ['D1']
        t = trades['D1']
        assert t['pnl'] == 22.5
        assert t['exit_reason'] == 'TP_HIT'
        assert t['bot_id'] == 'gold_m5_bot'
        assert t['epic'] == 'GOLD'
        assert t['entry_price'] == 4000.0
        assert t['exit_price'] == 4045.0
        assert t['entry_time'] == '2026-07-30T10:00:00'
        assert t['pnl_estimated'] is False

    @pytest.mark.asyncio
    async def test_broker_pnl_is_not_recomputed(self, skill, db_path):
        """Broker P&L includes spread/fees — arithmetic must not override it."""
        await skill.save_open_position(deal_id='D1', epic='GOLD', direction='BUY',
                                       level=4000.0, size=0.5)
        await skill.close_position('D1', close_price=4045.0, close_reason='TP_HIT',
                                   pnl=21.30, direction='BUY', entry_price=4000.0, size=0.5)
        assert read_trades(db_path)['D1']['pnl'] == 21.30

    @pytest.mark.asyncio
    async def test_estimates_pnl_when_broker_gives_none(self, skill, db_path):
        """None means 'unknown' → fall back to arithmetic and flag it."""
        await skill.save_open_position(deal_id='D2', epic='GOLD', direction='SELL',
                                       level=4000.0, size=0.5)
        await skill.close_position('D2', close_price=4015.0, close_reason='SL_HIT',
                                   pnl=None, direction='SELL', entry_price=4000.0, size=0.5)
        t = read_trades(db_path)['D2']
        assert t['pnl'] == -7.5           # (4000-4015) * 0.5
        assert t['pnl_estimated'] is True
        assert t['pnl_unknown'] is False

    @pytest.mark.asyncio
    async def test_genuine_zero_broker_pnl_is_preserved(self, skill, db_path):
        """A real break-even figure of 0.0 must NOT be replaced by an estimate."""
        await skill.save_open_position(deal_id='D2b', epic='GOLD', direction='SELL',
                                       level=4000.0, size=0.5)
        await skill.close_position('D2b', close_price=4015.0, close_reason='SL_HIT',
                                   pnl=0.0, direction='SELL', entry_price=4000.0, size=0.5)
        t = read_trades(db_path)['D2b']
        assert t['pnl'] == 0.0
        assert t['pnl_estimated'] is False

    @pytest.mark.asyncio
    async def test_unknown_pnl_is_flagged_not_recorded_as_breakeven(self, skill, db_path):
        """
        The regression that zeroed 365 live trades: the REST reconcile supplied
        close_price=0.0 and no P&L, so nothing could be computed.  That must be
        flagged, not silently written as a break-even trade.
        """
        await skill.save_open_position(deal_id='D2c', epic='GOLD', direction='BUY',
                                       level=4000.0, size=0.5)
        await skill.close_position('D2c', close_price=0.0, close_reason='SIGNAL',
                                   pnl=None, direction='BUY', entry_price=4000.0, size=0.5)
        t = read_trades(db_path)['D2c']
        assert t['pnl_unknown'] is True
        assert t['pnl_estimated'] is False

    @pytest.mark.asyncio
    async def test_backfills_fields_from_open_row(self, skill, db_path):
        """Caller may not know size/epic — read them off the open position."""
        await skill.save_open_position(deal_id='D3', epic='GOLD', direction='BUY',
                                       level=4000.0, size=2.0,
                                       opened_at='2026-07-30T09:00:00')
        await skill.close_position('D3', close_price=4010.0, close_reason='SIGNAL', pnl=20.0)
        t = read_trades(db_path)['D3']
        assert t['size'] == 2.0
        assert t['direction'] == 'BUY'
        assert t['entry_price'] == 4000.0
        assert t['epic'] == 'GOLD'

    @pytest.mark.asyncio
    async def test_duplicate_close_does_not_double_count(self, skill, db_path):
        """Activity poll and REST reconcile can both report the same close."""
        await skill.save_open_position(deal_id='D1', epic='GOLD', direction='BUY',
                                       level=4000.0, size=0.5)
        for _ in range(3):
            await skill.close_position('D1', close_price=4045.0, close_reason='TP_HIT',
                                       pnl=22.5, direction='BUY', entry_price=4000.0, size=0.5)
        trades = read_trades(db_path)
        assert len(trades) == 1
        assert trades['D1']['pnl'] == 22.5

    @pytest.mark.asyncio
    async def test_close_still_marks_position_closed(self, skill, db_path):
        await skill.save_open_position(deal_id='D1', epic='GOLD', direction='BUY',
                                       level=4000.0, size=0.5)
        await skill.close_position('D1', close_price=4045.0, close_reason='TP_HIT', pnl=22.5)

        con = sqlite3.connect(db_path)
        row = con.execute(
            "SELECT data FROM kv_store WHERE collection='active_positions' AND doc_id='D1'"
        ).fetchone()
        con.close()
        pos = json.loads(row[0])
        assert pos['status'] == 'CLOSED'
        assert pos['realized_pnl'] == 22.5


class TestOpenedAtPreservation:
    """
    _save_position re-runs on every REST reconcile (~60s) to refresh live P&L.
    The `datetime.now()` fallback used to overwrite opened_at each pass, so every
    trade's recorded hold time collapsed to seconds.
    """

    @pytest.mark.asyncio
    async def test_reconcile_does_not_reset_opened_at(self, skill, db_path):
        await skill.save_open_position(deal_id='D1', epic='GOLD', direction='BUY',
                                       level=4000.0, size=0.5,
                                       opened_at='2026-07-30T09:00:00')
        # Reconcile passes no opened_at — the original must survive
        for _ in range(3):
            await skill.save_open_position(deal_id='D1', epic='GOLD', direction='BUY',
                                           level=4000.0, size=0.5, upl=3.2)

        con = sqlite3.connect(db_path)
        row = con.execute(
            "SELECT data FROM kv_store WHERE collection='active_positions' AND doc_id='D1'"
        ).fetchone()
        con.close()
        assert json.loads(row[0])['opened_at'] == '2026-07-30T09:00:00'

    @pytest.mark.asyncio
    async def test_hold_time_survives_into_trade_record(self, skill, db_path):
        await skill.save_open_position(deal_id='D1', epic='GOLD', direction='BUY',
                                       level=4000.0, size=0.5,
                                       opened_at='2026-07-30T09:00:00')
        await skill.save_open_position(deal_id='D1', epic='GOLD', direction='BUY',
                                       level=4000.0, size=0.5, upl=3.2)
        await skill.close_position('D1', close_price=4045.0, close_reason='TP_HIT', pnl=22.5)
        assert read_trades(db_path)['D1']['entry_time'] == '2026-07-30T09:00:00'


class TestLiveReportIntegration:

    @pytest.mark.asyncio
    async def test_report_reads_recorded_trades(self, skill, db_path):
        await skill.save_open_position(deal_id='D1', epic='GOLD', direction='BUY',
                                       level=4000.0, size=0.5)
        await skill.close_position('D1', close_price=4045.0, close_reason='TP_HIT',
                                   pnl=22.5, direction='BUY', entry_price=4000.0, size=0.5)
        await skill.save_open_position(deal_id='D2', epic='GOLD', direction='SELL',
                                       level=4000.0, size=0.5)
        await skill.close_position('D2', close_price=4015.0, close_reason='SL_HIT',
                                   pnl=-7.5, direction='SELL', entry_price=4000.0, size=0.5)

        sys.path.insert(0, os.path.abspath(
            os.path.join(os.path.dirname(__file__), '../../../cloud-function/api')))
        import database as db
        import live_report as lr
        db.DB_PATH = db_path

        report = lr.get_live_report(bot_id='gold_m5_bot', initial_capital=10000)
        s = report['summary']
        assert s['total_trades'] == 2
        assert s['total_pnl'] == 15.0
        assert s['win_rate'] == 50.0
        assert report['trade_distribution']['by_exit_reason']['TP_HIT']['count'] == 1

        # bot_id filter must exclude other bots
        other = lr.get_live_report(bot_id='ethusd_m5_bot', initial_capital=10000)
        assert other['summary']['total_trades'] == 0

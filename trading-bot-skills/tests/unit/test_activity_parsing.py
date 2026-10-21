"""
Unit tests — activity close detection

Regression cover for the bug that silently disabled live P&L recording, the
SL/TP cooldowns, the daily-loss limit and the consecutive-loss breaker for
~3 months:

  1. `get_activity()` filtered on `status==EXECUTED`, which matches nothing on
     this API (200 with an empty list).  `ACCEPTED` is the correct value.
  2. The close parser walked a `details['actions']` array that does not exist
     in the response, so even a working filter would have parsed nothing.

Every close therefore fell through to the 60s REST reconcile, which supplied a
0.0 close level and no reason -> P&L recorded as exactly 0.0 and every exit
labelled 'SIGNAL'.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from clients.capital_api import CapitalAPIClient


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class _RecordingClient(CapitalAPIClient):
    """Captures request params instead of calling the network."""

    def __init__(self, payload=None):
        self.calls = []
        self._payload = payload or {'activities': []}

    def _request(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs.get('params', {})))
        return _FakeResponse(self._payload)


class TestActivityFilter:

    def test_uses_accepted_not_executed(self):
        """status==EXECUTED matches nothing on this API — must be ACCEPTED."""
        c = _RecordingClient()
        c.get_activity(last_period_seconds=120)
        _, path, params = c.calls[0]
        assert path == '/api/v1/history/activity'
        assert 'status==ACCEPTED' in params['filter']
        assert 'EXECUTED' not in params['filter']

    def test_epic_filter_is_included(self):
        """epic== is supported alongside ACCEPTED (verified against live API)."""
        c = _RecordingClient()
        c.get_activity(last_period_seconds=120, epic='US100')
        assert 'epic==US100' in c.calls[0][2]['filter']

    def test_detailed_is_requested(self):
        """Without detailed=true there is no `details` object to parse."""
        c = _RecordingClient()
        c.get_activity()
        assert c.calls[0][2]['detailed'] == 'true'


# The real response shape. Note: no 'actions' array, no 'profit', and
# 'openPrice' present only on the close.
_CLOSE_EVENT = {
    'epic': 'US100', 'dealId': 'D-1', 'source': 'SL',
    'type': 'POSITION', 'status': 'ACCEPTED',
    'details': {
        'size': 1.0, 'direction': 'BUY',       # closing direction = opposite of position
        'level': 29579.9, 'stopLevel': 29579.7, 'profitLevel': 29379.7,
        'openPrice': 29526.9,
    },
}
_OPEN_EVENT = {
    'epic': 'US100', 'dealId': 'D-1', 'source': 'USER',
    'type': 'POSITION', 'status': 'ACCEPTED',
    'details': {
        'size': 1.0, 'direction': 'SELL',
        'level': 29526.9, 'stopLevel': 29579.7, 'profitLevel': 29379.7,
    },
}


def _classify(activity):
    """Mirror of the parsing in orchestrator/main.py's _poll_positions."""
    details = activity.get('details', {})
    is_close = 'openPrice' in details
    source = (activity.get('source') or '').upper()
    reason = {'SL': 'SL_HIT', 'TP': 'TP_HIT'}.get(source, 'SIGNAL')
    return is_close, reason


class TestCloseDetection:

    def test_openprice_marks_a_close(self):
        is_close, _ = _classify(_CLOSE_EVENT)
        assert is_close is True

    def test_missing_openprice_marks_an_open(self):
        is_close, _ = _classify(_OPEN_EVENT)
        assert is_close is False

    @pytest.mark.parametrize('source,expected', [
        ('SL', 'SL_HIT'),
        ('TP', 'TP_HIT'),
        ('USER', 'SIGNAL'),
        ('', 'SIGNAL'),
    ])
    def test_source_maps_to_exit_reason(self, source, expected):
        """
        'source' is authoritative. The old code string-matched a `description`
        that the REST fallback passed as '', so everything became 'SIGNAL' and
        the SL/TP cooldowns never applied.
        """
        event = dict(_CLOSE_EVENT, source=source)
        _, reason = _classify(event)
        assert reason == expected

    def test_response_has_no_actions_array(self):
        """Guards the assumption the old parser got wrong."""
        assert 'actions' not in _CLOSE_EVENT['details']

    def test_response_has_no_profit_field(self):
        """P&L must be joined from /history/transactions, not read from here."""
        assert 'profit' not in _CLOSE_EVENT['details']


class TestRealisedPnlLookup:

    def test_reads_size_field_as_pnl(self):
        """In /history/transactions the `size` field IS the realised P&L."""
        c = _RecordingClient({'transactions': [
            {'dealId': 'D-1', 'transactionType': 'TRADE', 'size': '-48.01'},
        ]})
        assert c.get_realised_pnl('D-1') == pytest.approx(-48.01)

    def test_returns_none_when_no_matching_deal(self):
        """None means 'unknown' — callers must not treat it as break-even."""
        c = _RecordingClient({'transactions': [
            {'dealId': 'OTHER', 'transactionType': 'TRADE', 'size': '-48.01'},
        ]})
        assert c.get_realised_pnl('D-1') is None

    def test_ignores_non_trade_rows(self):
        """SWAP/CORPORATE_ACTION rows also carry a dealId."""
        c = _RecordingClient({'transactions': [
            {'dealId': 'D-1', 'transactionType': 'SWAP', 'size': '-1.40'},
        ]})
        assert c.get_realised_pnl('D-1') is None

    def test_lastperiod_is_capped_at_86400(self):
        """The API rejects lastPeriod > 86400 with a 400."""
        c = _RecordingClient({'transactions': []})
        c.get_realised_pnl('D-1', last_period_seconds=7 * 86400)
        assert c.calls[0][2]['lastPeriod'] == 86400

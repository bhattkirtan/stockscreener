"""
Unit tests — clients/capital_api.py, the broker boundary.

This is the only module in the repo that can move money.  `place_order` was at
**0% cover** before this suite: the single highest-risk untested function here.

Why the harness looks the way it does
-------------------------------------
Every other suite that touches this client stubs `_request` and asserts on the
params (see `test_activity_parsing.py`).  That is the right level for "did we
send the correct filter", but it cannot test `_request` itself — the shared
auth/retry/error layer every other method flows through, and the largest single
uncovered block in the file.

So this suite patches one level lower, over `requests.request` / `requests.post`,
and hands back **real `requests.Response` objects**.  That matters concretely:

  * `raise_for_status()` raises a genuine `HTTPError` with `.response` attached,
  * `Response.__bool__` returns `self.ok` — i.e. **False for every 4xx/5xx**.

That second property is not a detail.  `create_session` guards its rate-limit
branch with `if e.response and e.response.status_code == 429`, which can never
be true for a 429 because the response is falsy.  A hand-rolled fake response
object (truthy, as plain objects are) would have hidden that bug and the test
would have asserted the wrong behaviour.  Pinning this boundary with fakes that
are *more* forgiving than production is how a broker client passes its tests and
still fails live.

Nothing here reaches the network: `requests.request` and `requests.post` are
patched for the whole module via an autouse fixture, so a missed patch fails
loudly rather than dialling Capital.com.

Assertions are exact values, never inequalities — the lesson of gotcha 31 (a 50x
`slippage_cost_usd` typo) and gotcha 50 (a factor-of-50 error passes every
inequality test).
"""
import json
import os
import sys

import pytest
import requests

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from clients.capital_api import CapitalAPIClient

DEMO_URL = 'https://demo-api-capital.backend-capital.com'
LIVE_URL = 'https://api-capital.backend-capital.com'


# ────────────────────────────────────────────────────────────────────────────
#  Harness
# ────────────────────────────────────────────────────────────────────────────

def make_response(status=200, payload=None, headers=None, body=None,
                  reason=None, url=DEMO_URL + '/api/v1/test'):
    """
    Build a REAL requests.Response.

    Real, not a stand-in, so `raise_for_status()`, `.json()`, `.headers` and
    `__bool__` all behave exactly as they do against the live API.
    """
    r = requests.Response()
    r.status_code = status
    r.url = url
    r.reason = reason
    r.encoding = 'utf-8'
    if headers:
        r.headers.update(headers)
    if body is None:
        body = json.dumps({} if payload is None else payload)
    r._content = body.encode('utf-8') if isinstance(body, str) else body
    return r


def rate_limited():
    """A 429 whose HTTPError message carries the real API's reason string."""
    return make_response(429, {'errorCode': 'error.too-many-requests'},
                         reason='Too Many Requests')


class _Call:
    """One recorded outgoing HTTP call.

    `headers` and `params` are **snapshotted**, deliberately.  `_request`
    mutates and re-uses the same header dict across a 401 retry, so holding the
    live reference would make call #1 and call #2 indistinguishable and quietly
    turn the retry assertions vacuous.
    """

    def __init__(self, method, url, kwargs):
        self.method = method
        self.url = url
        self.kwargs = dict(kwargs)
        self.headers = dict(kwargs.get('headers') or {})
        self.params = dict(kwargs.get('params') or {})
        self.json = kwargs.get('json')
        self.timeout = kwargs.get('timeout')

    def __repr__(self):
        return f"<{self.method} {self.url} params={self.params}>"


class FakeTransport:
    """
    Replays a queue of responses and records what was sent.

    Queue entries are either a `requests.Response` (returned) or an `Exception`
    instance (raised) — so connection errors and timeouts are expressible.
    A callable entry is invoked with the `_Call` and its result returned/raised,
    for the few tests that need to react to the request.
    """

    def __init__(self, *responses):
        self.queue = list(responses)
        self.calls = []

    def push(self, *responses):
        self.queue.extend(responses)
        return self

    # requests.request(method, url, **kwargs)
    def request(self, method, url, **kwargs):
        return self._serve(_Call(method, url, kwargs))

    # requests.post(url, **kwargs)
    def post(self, url, **kwargs):
        return self._serve(_Call('POST', url, kwargs))

    def _serve(self, call):
        self.calls.append(call)
        if not self.queue:
            raise AssertionError(
                f"FakeTransport: unexpected call {call!r} — queue is empty. "
                f"{len(self.calls)} call(s) so far: {self.calls}"
            )
        nxt = self.queue.pop(0)
        if callable(nxt) and not isinstance(nxt, requests.Response):
            nxt = nxt(call)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt

    @property
    def n(self):
        return len(self.calls)

    def call(self, i):
        assert len(self.calls) > i, f"expected > {i} call(s), got {len(self.calls)}"
        return self.calls[i]


SESSION_OK = dict(
    status=200,
    payload={'accountId': 'ACC1', 'currency': 'EUR'},
    headers={'CST': 'CST-NEW', 'X-SECURITY-TOKEN': 'TOK-NEW'},
)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Fail loudly rather than reaching Capital.com if a test forgets to patch."""
    def _boom(*a, **k):
        raise AssertionError('a test made an unpatched HTTP call')
    monkeypatch.setattr(requests, 'request', _boom)
    monkeypatch.setattr(requests, 'post', _boom)
    monkeypatch.setattr(requests, 'get', _boom)


@pytest.fixture
def transport(monkeypatch):
    t = FakeTransport()
    monkeypatch.setattr(requests, 'request', t.request)
    monkeypatch.setattr(requests, 'post', t.post)
    return t


@pytest.fixture
def clean_env(monkeypatch):
    for k in ('CAPITAL_IDENTIFIER', 'CAPITAL_USERNAME', 'CAPITAL_PASSWORD',
              'CAPITAL_API_KEY', 'CAPITAL_ENVIRONMENT'):
        monkeypatch.delenv(k, raising=False)


@pytest.fixture
def client(clean_env):
    return CapitalAPIClient(username='user@example.com', password='pw',
                            api_key='KEY', environment='demo')


@pytest.fixture
def authed(client):
    """A client that already holds a valid session, so `_request` sends no POST."""
    client.cst = 'CST-OLD'
    client.security_token = 'TOK-OLD'
    client._token_cache['valid'] = True
    return client


# ────────────────────────────────────────────────────────────────────────────
#  _request — the shared auth / retry / error layer.  Everything flows here.
# ────────────────────────────────────────────────────────────────────────────

class TestRequestLayer:

    def test_sends_both_session_headers_and_json_content_type(self, authed, transport):
        transport.push(make_response(200, {'ok': True}))
        authed._request('GET', '/api/v1/positions')
        h = transport.call(0).headers
        assert h['CST'] == 'CST-OLD'
        assert h['X-SECURITY-TOKEN'] == 'TOK-OLD'
        assert h['Content-Type'] == 'application/json'

    def test_url_is_base_plus_path(self, authed, transport):
        transport.push(make_response(200))
        authed._request('GET', '/api/v1/positions')
        assert transport.call(0).url == DEMO_URL + '/api/v1/positions'

    def test_live_environment_changes_the_base_url(self, clean_env, transport):
        c = CapitalAPIClient(username='u', password='p', api_key='k', environment='live')
        c.cst, c.security_token = 'C', 'T'
        c._token_cache['valid'] = True
        transport.push(make_response(200))
        c._request('GET', '/api/v1/accounts')
        assert transport.call(0).url == LIVE_URL + '/api/v1/accounts'

    def test_timeout_is_fifteen_seconds(self, authed, transport):
        transport.push(make_response(200))
        authed._request('GET', '/api/v1/positions')
        assert transport.call(0).timeout == 15

    @pytest.mark.parametrize('method', ['GET', 'POST', 'PUT', 'DELETE'])
    def test_method_is_forwarded_verbatim(self, authed, transport, method):
        transport.push(make_response(200))
        authed._request(method, '/api/v1/positions')
        assert transport.call(0).method == method

    def test_extra_kwargs_are_forwarded(self, authed, transport):
        transport.push(make_response(200))
        authed._request('POST', '/api/v1/positions',
                        json={'epic': 'GOLD'}, params={'x': '1'})
        call = transport.call(0)
        assert call.json == {'epic': 'GOLD'}
        assert call.params == {'x': '1'}

    def test_returns_the_response_object_itself(self, authed, transport):
        resp = make_response(200, {'positions': []})
        transport.push(resp)
        assert authed._request('GET', '/api/v1/positions') is resp

    def test_caller_headers_are_merged_and_auth_headers_win(self, authed, transport):
        transport.push(make_response(200))
        authed._request('GET', '/x', headers={'X-Trace': 'abc', 'CST': 'IGNORED'})
        h = transport.call(0).headers
        assert h['X-Trace'] == 'abc'          # caller's own header survives
        assert h['CST'] == 'CST-OLD'          # but the session token overrides

    def test_caller_supplied_headers_dict_is_mutated_in_place(self, authed, transport):
        """Documented side effect: the caller's dict gains the auth headers.

        Harmless today (no production caller passes `headers`), but a caller
        that reused one dict across requests would carry stale tokens into the
        next call.
        """
        transport.push(make_response(200))
        mine = {'X-Trace': 'abc'}
        authed._request('GET', '/x', headers=mine)
        assert mine['CST'] == 'CST-OLD'
        assert set(mine) == {'X-Trace', 'CST', 'X-SECURITY-TOKEN', 'Content-Type'}

    def test_no_session_is_created_when_tokens_are_valid(self, authed, transport):
        transport.push(make_response(200))
        authed._request('GET', '/x')
        assert transport.n == 1
        assert transport.call(0).method == 'GET'

    def test_a_session_is_created_when_tokens_are_absent(self, client, transport):
        transport.push(make_response(**SESSION_OK), make_response(200))
        client._request('GET', '/x')
        assert transport.n == 2
        assert transport.call(0).url == DEMO_URL + '/api/v1/session'
        assert transport.call(1).headers['CST'] == 'CST-NEW'


class TestRequestRateLimit:

    def test_429_raises_with_the_path_in_the_message(self, authed, transport):
        transport.push(rate_limited())
        with pytest.raises(Exception, match=r'Rate limit exceeded on /api/v1/positions'):
            authed._request('GET', '/api/v1/positions')

    def test_429_is_not_retried(self, authed, transport):
        transport.push(rate_limited())
        with pytest.raises(Exception):
            authed._request('GET', '/x')
        assert transport.n == 1

    def test_429_raises_before_raise_for_status_so_it_is_not_an_httperror(self, authed, transport):
        """The 429 branch raises a bare Exception, deliberately ahead of
        `raise_for_status()`.  Callers that catch only HTTPError will not see it."""
        transport.push(rate_limited())
        with pytest.raises(Exception) as exc:
            authed._request('GET', '/x')
        assert not isinstance(exc.value, requests.exceptions.HTTPError)


class TestRequest401Refresh:

    def test_401_clears_tokens_creates_a_session_and_retries_once(self, authed, transport):
        transport.push(
            make_response(401, reason='Unauthorized'),
            make_response(**SESSION_OK),
            make_response(200, {'retried': True}),
        )
        resp = authed._request('GET', '/api/v1/positions')
        assert resp.json() == {'retried': True}
        assert [c.method for c in transport.calls] == ['GET', 'POST', 'GET']
        assert transport.call(1).url == DEMO_URL + '/api/v1/session'

    def test_the_retry_carries_the_NEW_tokens(self, authed, transport):
        """The retry hands the *old* header dict back into `_request`, which
        then `update()`s the fresh tokens over it.  So the retry is correctly
        authenticated — but only because update() overwrites.  Pinned because
        re-ordering those two lines would silently retry with dead tokens."""
        transport.push(
            make_response(401, reason='Unauthorized'),
            make_response(**SESSION_OK),
            make_response(200),
        )
        authed._request('GET', '/x')
        assert transport.call(0).headers['CST'] == 'CST-OLD'
        assert transport.call(2).headers['CST'] == 'CST-NEW'
        assert transport.call(2).headers['X-SECURITY-TOKEN'] == 'TOK-NEW'

    def test_the_token_cache_is_cleared_on_401(self, authed, transport):
        transport.push(
            make_response(401, reason='Unauthorized'),
            make_response(**SESSION_OK),
            make_response(200),
        )
        authed._request('GET', '/x')
        # create_session re-primed it, and the client holds the new tokens
        assert authed.cst == 'CST-NEW'
        assert authed.security_token == 'TOK-NEW'
        assert 'valid' in authed._token_cache

    def test_a_second_401_raises_rather_than_recursing(self, authed, transport):
        transport.push(
            make_response(401, reason='Unauthorized'),
            make_response(**SESSION_OK),
            make_response(401, reason='Unauthorized'),
        )
        with pytest.raises(requests.exceptions.HTTPError):
            authed._request('GET', '/x')
        assert transport.n == 3      # GET, session POST, GET — then it gives up

    def test_retry_on_401_false_raises_immediately(self, authed, transport):
        transport.push(make_response(401, reason='Unauthorized'))
        with pytest.raises(requests.exceptions.HTTPError):
            authed._request('GET', '/x', retry_on_401=False)
        assert transport.n == 1


class TestRequestErrors:

    @pytest.mark.parametrize('status,reason', [
        (400, 'Bad Request'), (403, 'Forbidden'), (404, 'Not Found'),
        (500, 'Internal Server Error'), (503, 'Service Unavailable'),
    ])
    def test_error_statuses_raise_httperror(self, authed, transport, status, reason):
        transport.push(make_response(status, reason=reason))
        with pytest.raises(requests.exceptions.HTTPError):
            authed._request('GET', '/x')

    def test_the_httperror_carries_the_response_for_the_caller_to_inspect(self, authed, transport):
        transport.push(make_response(404, {'errorCode': 'error.not-found'}, reason='Not Found'))
        with pytest.raises(requests.exceptions.HTTPError) as exc:
            authed._request('GET', '/x')
        assert exc.value.response.status_code == 404
        assert exc.value.response.json() == {'errorCode': 'error.not-found'}

    def test_an_error_response_is_FALSY_which_is_why_truthiness_guards_fail(self, authed, transport):
        """`requests.Response.__bool__` is `self.ok`.  Any `if e.response:` guard
        is therefore dead for exactly the error cases it was written to handle —
        the bug this suite found in `create_session`.  Use `is not None`."""
        transport.push(make_response(404, reason='Not Found'))
        with pytest.raises(requests.exceptions.HTTPError) as exc:
            authed._request('GET', '/x')
        assert bool(exc.value.response) is False
        assert exc.value.response is not None

    @pytest.mark.parametrize('exc', [
        requests.exceptions.ConnectionError('dns failure'),
        requests.exceptions.Timeout('read timed out'),
        requests.exceptions.SSLError('bad handshake'),
    ])
    def test_transport_level_errors_propagate_uncaught(self, authed, transport, exc):
        """`_request` catches only HTTPError, so connection errors and timeouts
        pass straight through — unlogged at this layer.  Every public method
        wraps them in its own `except Exception`, so nothing crashes the bot;
        this pins where the handling actually happens."""
        transport.push(exc)
        with pytest.raises(type(exc)):
            authed._request('GET', '/x')


# ────────────────────────────────────────────────────────────────────────────
#  create_session / get_tokens
# ────────────────────────────────────────────────────────────────────────────

class TestCreateSession:

    def test_posts_credentials_to_the_session_endpoint(self, client, transport):
        transport.push(make_response(**SESSION_OK))
        client.create_session()
        call = transport.call(0)
        assert call.method == 'POST'
        assert call.url == DEMO_URL + '/api/v1/session'
        assert call.headers == {'X-CAP-API-KEY': 'KEY',
                                'Content-Type': 'application/json'}
        assert call.json == {'identifier': 'user@example.com',
                             'password': 'pw',
                             'encryptedPassword': False}
        assert call.timeout == 15

    def test_tokens_come_from_response_HEADERS_not_the_body(self, client, transport):
        transport.push(make_response(
            200,
            payload={'CST': 'BODY-DECOY', 'X-SECURITY-TOKEN': 'BODY-DECOY'},
            headers={'CST': 'CST-NEW', 'X-SECURITY-TOKEN': 'TOK-NEW'},
        ))
        client.create_session()
        assert client.cst == 'CST-NEW'
        assert client.security_token == 'TOK-NEW'

    def test_returns_tokens_plus_the_account_body(self, client, transport):
        transport.push(make_response(**SESSION_OK))
        out = client.create_session()
        assert out == {'CST': 'CST-NEW',
                       'X-SECURITY-TOKEN': 'TOK-NEW',
                       'account': {'accountId': 'ACC1', 'currency': 'EUR'}}

    def test_primes_the_token_cache(self, client, transport):
        transport.push(make_response(**SESSION_OK))
        assert 'valid' not in client._token_cache
        client.create_session()
        assert client._token_cache['valid'] is True

    @pytest.mark.parametrize('headers', [
        {'X-SECURITY-TOKEN': 'TOK'},          # no CST
        {'CST': 'CST'},                       # no security token
        {},                                   # neither
    ])
    def test_missing_either_token_raises(self, client, transport, headers):
        transport.push(make_response(200, payload={}, headers=headers))
        with pytest.raises(Exception, match='Missing CST or X-SECURITY-TOKEN'):
            client.create_session()

    def test_a_401_raises_with_the_generic_message(self, client, transport):
        transport.push(make_response(401, reason='Unauthorized'))
        with pytest.raises(Exception, match='Failed to create session'):
            client.create_session()

    def test_transport_errors_propagate_unchanged(self, client, transport):
        transport.push(requests.exceptions.ConnectionError('dns failure'))
        with pytest.raises(requests.exceptions.ConnectionError):
            client.create_session()


class TestCreateSessionRateLimitBranchWasDead:
    """
    `create_session` guards its rate-limit branch with

        if e.response and e.response.status_code == 429:

    `requests.Response.__bool__` returns `self.ok`, so a 429 response is
    **falsy** and that branch never ran — the one status it exists to classify
    is the one status it cannot see.  Fixed to `is not None`.

    Impact was cosmetic rather than behavioural, and the tests say why:
    `idempotency.is_transient_error` matches on the substring 'too many
    requests', which the generic message happens to carry anyway, and no
    production caller retries session creation.  It is pinned because the
    *shape* is the hazard — a magnitude/classification guard that silently
    never fires, the same family as gotcha 50's wrong-side stop and gotcha
    53(e)'s truthiness test on a float.
    """

    def test_a_429_is_now_reported_as_a_rate_limit(self, client, transport):
        transport.push(rate_limited())
        with pytest.raises(Exception, match='rate limit exceeded') as exc:
            client.create_session()
        assert not isinstance(exc.value, requests.exceptions.HTTPError)

    def test_the_falsy_response_is_why_the_old_guard_could_not_work(self, client, transport):
        resp = rate_limited()
        assert bool(resp) is False, 'a 429 Response is falsy — `if e.response` is dead here'
        assert resp.status_code == 429

    def test_other_error_statuses_still_get_the_generic_message(self, client, transport):
        transport.push(make_response(503, reason='Service Unavailable'))
        with pytest.raises(Exception, match='Failed to create session'):
            client.create_session()

    def test_the_generic_message_would_still_classify_as_transient(self):
        """Why the dead branch cost nothing in practice: the HTTPError text
        carries 'Too Many Requests', which the transient-error classifier
        already matches."""
        from core.idempotency import is_transient_error
        err = Exception('Failed to create session: 429 Client Error: '
                        'Too Many Requests for url: ...')
        assert is_transient_error(err) is True


class TestGetTokens:

    def test_reuses_a_live_session(self, authed, transport):
        assert authed.get_tokens() == {'CST': 'CST-OLD', 'X-SECURITY-TOKEN': 'TOK-OLD'}
        assert transport.n == 0

    @pytest.mark.parametrize('field', ['cst', 'security_token'])
    def test_a_missing_token_forces_a_new_session(self, authed, transport, field):
        setattr(authed, field, None)
        transport.push(make_response(**SESSION_OK))
        assert authed.get_tokens()['CST'] == 'CST-NEW'
        assert transport.n == 1

    def test_an_expired_cache_forces_a_new_session_even_with_tokens_held(self, authed, transport):
        """The 55-minute TTL is the only thing that refreshes a session
        pre-emptively; tokens stay set on the object after it lapses."""
        authed._token_cache.clear()
        transport.push(make_response(**SESSION_OK))
        assert authed.get_tokens()['CST'] == 'CST-NEW'
        assert transport.n == 1


# ────────────────────────────────────────────────────────────────────────────
#  place_order — the call that puts money at the broker.  Was 0% covered.
# ────────────────────────────────────────────────────────────────────────────

class TestPlaceOrder:

    def test_posts_the_exact_payload(self, authed, transport):
        transport.push(make_response(200, {'dealReference': 'o_ref1'}))
        authed.place_order('GOLD', 'BUY', 0.5, stop_level=4100.0, profit_level=4160.0)
        call = transport.call(0)
        assert call.method == 'POST'
        assert call.url == DEMO_URL + '/api/v1/positions'
        assert call.json == {
            'epic': 'GOLD',
            'direction': 'BUY',
            'size': 0.5,
            'guaranteedStop': False,
            'stopLevel': 4100.0,
            'profitLevel': 4160.0,
        }

    def test_returns_the_broker_payload_verbatim(self, authed, transport):
        transport.push(make_response(200, {'dealReference': 'o_ref1', 'extra': 1}))
        assert authed.place_order('GOLD', 'BUY', 0.5) == {'dealReference': 'o_ref1',
                                                          'extra': 1}

    @pytest.mark.parametrize('given,sent', [
        ('buy', 'BUY'), ('BUY', 'BUY'), ('sell', 'SELL'), ('Sell', 'SELL'),
    ])
    def test_direction_is_upper_cased(self, authed, transport, given, sent):
        transport.push(make_response(200, {'dealReference': 'r'}))
        authed.place_order('GOLD', given, 1)
        assert transport.call(0).json['direction'] == sent

    def test_direction_is_not_validated(self, authed, transport):
        """'LONG' is sent as-is for the broker to reject.  Pinned so the absence
        of client-side validation is a known property, not a surprise."""
        transport.push(make_response(200, {'dealReference': 'r'}))
        authed.place_order('GOLD', 'long', 1)
        assert transport.call(0).json['direction'] == 'LONG'

    def test_levels_are_omitted_when_None(self, authed, transport):
        transport.push(make_response(200, {'dealReference': 'r'}))
        authed.place_order('GOLD', 'BUY', 0.5)
        assert transport.call(0).json == {'epic': 'GOLD', 'direction': 'BUY',
                                          'size': 0.5, 'guaranteedStop': False}

    @pytest.mark.parametrize('kwargs,key', [
        ({'stop_level': 4100.0}, 'stopLevel'),
        ({'profit_level': 4160.0}, 'profitLevel'),
    ])
    def test_either_level_can_be_sent_alone(self, authed, transport, kwargs, key):
        transport.push(make_response(200, {'dealReference': 'r'}))
        authed.place_order('GOLD', 'BUY', 0.5, **kwargs)
        sent = transport.call(0).json
        assert key in sent
        assert len(sent) == 5

    def test_a_zero_level_is_sent_not_dropped(self, authed, transport):
        """`is not None`, not truthiness — so a legitimately-zero level survives.
        The opposite of gotcha 53(e)'s `if exit_price:` on a float.  An instrument
        priced near zero would otherwise have its stop silently removed."""
        transport.push(make_response(200, {'dealReference': 'r'}))
        authed.place_order('X', 'BUY', 1, stop_level=0.0, profit_level=0.0)
        assert transport.call(0).json['stopLevel'] == 0.0
        assert transport.call(0).json['profitLevel'] == 0.0

    def test_guaranteed_stop_defaults_to_False(self, authed, transport):
        """Why every live position has `guaranteedStop: false` and why a weekend
        or news gap is uncapped (gotchas 19, 51).  The default is here."""
        transport.push(make_response(200, {'dealReference': 'r'}))
        authed.place_order('GOLD', 'BUY', 0.5)
        assert transport.call(0).json['guaranteedStop'] is False

    def test_guaranteed_stop_can_be_requested(self, authed, transport):
        transport.push(make_response(200, {'dealReference': 'r'}))
        authed.place_order('GOLD', 'BUY', 0.5, guaranteed_stop=True)
        assert transport.call(0).json['guaranteedStop'] is True

    def test_a_missing_dealReference_does_NOT_raise(self, authed, transport):
        """The broker 200ing with no dealReference is logged as a success and
        returned.  `execution_skill` then confirms `None`, so the absence of a
        guard here is pinned rather than assumed benign."""
        transport.push(make_response(200, {}))
        assert authed.place_order('GOLD', 'BUY', 0.5) == {}

    @pytest.mark.parametrize('queued', [
        make_response(400, {'errorCode': 'error.invalid.size'}, reason='Bad Request'),
        requests.exceptions.ConnectionError('dns failure'),
    ])
    def test_failures_are_re_raised_never_swallowed(self, authed, transport, queued):
        """An order that may or may not have reached the broker must surface.
        Contrast `confirm_order` and `get_activity`, which both swallow."""
        transport.push(queued)
        with pytest.raises(Exception):
            authed.place_order('GOLD', 'BUY', 0.5)

    def test_a_429_on_an_order_surfaces_as_a_rate_limit(self, authed, transport):
        transport.push(rate_limited())
        with pytest.raises(Exception, match='Rate limit exceeded on /api/v1/positions'):
            authed.place_order('GOLD', 'BUY', 0.5)


class TestConfirmOrder:

    def test_gets_the_confirms_endpoint_for_the_reference(self, authed, transport):
        transport.push(make_response(200, {'dealId': 'D1', 'status': 'OPEN'}))
        authed.confirm_order('o_ref1')
        assert transport.call(0).method == 'GET'
        assert transport.call(0).url == DEMO_URL + '/api/v1/confirms/o_ref1'

    def test_returns_the_confirmation_verbatim(self, authed, transport):
        body = {'dealId': 'D1', 'status': 'OPEN', 'level': 4123.4}
        transport.push(make_response(200, body))
        assert authed.confirm_order('o_ref1') == body

    @pytest.mark.parametrize('status', ['DELETED', 'REJECTED'])
    def test_a_rejection_is_logged_but_still_RETURNED_not_raised(self, authed,
                                                                 transport, status):
        """The rejection decision belongs to `execution_skill`, which inspects
        `status` itself (`execution_skill.py:279`).  Raising here would move that
        decision and change the live path."""
        body = {'dealId': 'D1', 'status': status, 'reason': 'INSUFFICIENT_FUNDS'}
        transport.push(make_response(200, body))
        assert authed.confirm_order('o_ref1') == body

    @pytest.mark.parametrize('body,expected_in_log', [
        ({'status': 'REJECTED', 'reason': 'R1'}, 'R1'),
        ({'status': 'REJECTED', 'rejectReason': 'R2'}, 'R2'),
        ({'status': 'REJECTED'}, 'reason='),
    ])
    def test_reason_falls_back_through_reason_then_rejectReason(
            self, authed, transport, body, expected_in_log, caplog):
        transport.push(make_response(200, body))
        with caplog.at_level('ERROR'):
            authed.confirm_order('o_ref1')
        assert expected_in_log in caplog.text


class TestConfirmOrderSwallowsFailures:
    """
    `confirm_order` returns `{}` on ANY exception, so a transient network error
    is indistinguishable from a confirmation that arrived empty.

    The downstream consequence, pinned here because it is not visible from this
    module alone: `execution_skill.py:272-275` does

        deal_id = confirm.get('dealId') or deal_reference

    so an empty confirm makes the bot track the position under its
    **dealReference** — a different ID space from dealId (resolving one to the
    other is this function's entire job).  Nothing then rejects the trade, and
    `get_realised_pnl` joins `/history/transactions` on dealId, so that row can
    never resolve a real P&L.

    The blast radius is bounded, and it is worth being precise about why: the
    60s REST reconcile in `_poll_positions` re-keys `known` from
    `get_open_positions()` using the broker's own dealId and overwrites
    `risk.open_position_deal_id` (`main.py:465`).  So the wrong id is corrected
    within a minute.  Left as-is deliberately — the alternatives (raise, or
    treat empty as a rejection) would make the bot forget a position that is
    live at the broker, which is gotcha 49's accumulation hole in a new place.
    """

    @pytest.mark.parametrize('queued', [
        make_response(404, reason='Not Found'),
        make_response(500, reason='Internal Server Error'),
        requests.exceptions.Timeout('read timed out'),
        requests.exceptions.ConnectionError('dns failure'),
    ])
    def test_every_failure_mode_returns_an_empty_dict(self, authed, transport, queued):
        transport.push(queued)
        assert authed.confirm_order('o_ref1') == {}

    def test_a_429_is_also_swallowed(self, authed, transport):
        transport.push(rate_limited())
        assert authed.confirm_order('o_ref1') == {}

    def test_failure_is_indistinguishable_from_an_empty_confirmation(self, authed,
                                                                     transport):
        transport.push(make_response(200, {}))
        from_empty_body = authed.confirm_order('o_ref1')
        transport.push(requests.exceptions.ConnectionError('dns failure'))
        from_network_error = authed.confirm_order('o_ref1')
        assert from_empty_body == from_network_error == {}

    def test_the_caller_then_substitutes_the_dealReference_for_the_dealId(self, authed,
                                                                         transport):
        """Reproduces `execution_skill`'s fallback against a swallowed failure,
        so the wrong-id window is pinned by a test rather than by prose."""
        transport.push(requests.exceptions.ConnectionError('dns failure'))
        confirm = authed.confirm_order('o_ref1')
        deal_id = confirm.get('dealId') or 'o_ref1'
        assert deal_id == 'o_ref1'
        assert confirm.get('status', '') == ''
        assert not deal_id.startswith('00000000-0000-0000-')   # no rejection fires


# ────────────────────────────────────────────────────────────────────────────
#  Position read / close / amend
# ────────────────────────────────────────────────────────────────────────────

class TestGetOpenPositions:

    def test_unwraps_the_positions_array(self, authed, transport):
        transport.push(make_response(200, {'positions': [{'position': {'dealId': 'D1'}}]}))
        assert authed.get_open_positions() == [{'position': {'dealId': 'D1'}}]

    def test_a_missing_key_is_an_empty_list(self, authed, transport):
        transport.push(make_response(200, {}))
        assert authed.get_open_positions() == []

    def test_requests_all_epics(self, authed, transport):
        transport.push(make_response(200, {'positions': []}))
        authed.get_open_positions()
        assert transport.call(0).url == DEMO_URL + '/api/v1/positions'
        assert transport.call(0).params == {}

    def test_failures_RAISE_rather_than_returning_empty(self, authed, transport):
        """Deliberately unlike `get_activity`.  An empty list here would read as
        'flat at the broker' and `_poll_positions` would book every tracked
        position as closed."""
        transport.push(requests.exceptions.ConnectionError('dns failure'))
        with pytest.raises(requests.exceptions.ConnectionError):
            authed.get_open_positions()


class TestClosePosition:

    def test_deletes_the_position_by_deal_id(self, authed, transport):
        transport.push(make_response(200, {'dealReference': 'c_ref1'}))
        out = authed.close_position('D1')
        assert transport.call(0).method == 'DELETE'
        assert transport.call(0).url == DEMO_URL + '/api/v1/positions/D1'
        assert out == {'dealReference': 'c_ref1'}

    def test_a_close_returns_only_a_reference_not_a_pnl(self, authed, transport):
        """Why the flatten and reverse-exit paths must book nothing on close and
        wait for `get_realised_pnl` (gotchas 49a, 51)."""
        transport.push(make_response(200, {'dealReference': 'c_ref1'}))
        out = authed.close_position('D1')
        assert 'profit' not in out and 'profitAndLoss' not in out

    def test_failures_are_re_raised(self, authed, transport):
        transport.push(make_response(404, reason='Not Found'))
        with pytest.raises(requests.exceptions.HTTPError):
            authed.close_position('D-GONE')


class TestUpdatePosition:

    def test_puts_only_the_stop(self, authed, transport):
        transport.push(make_response(200, {'dealReference': 'u1'}))
        authed.update_position('D1', stop_level=4100.0)
        assert transport.call(0).method == 'PUT'
        assert transport.call(0).url == DEMO_URL + '/api/v1/positions/D1'
        assert transport.call(0).json == {'stopLevel': 4100.0}

    def test_puts_only_the_target(self, authed, transport):
        transport.push(make_response(200, {}))
        authed.update_position('D1', profit_level=4160.0)
        assert transport.call(0).json == {'profitLevel': 4160.0}

    def test_puts_both_when_both_given(self, authed, transport):
        transport.push(make_response(200, {}))
        authed.update_position('D1', stop_level=4100.0, profit_level=4160.0)
        assert transport.call(0).json == {'stopLevel': 4100.0, 'profitLevel': 4160.0}

    def test_a_zero_stop_is_sent_not_dropped(self, authed, transport):
        transport.push(make_response(200, {}))
        authed.update_position('D1', stop_level=0.0)
        assert transport.call(0).json == {'stopLevel': 0.0}

    def test_neither_level_raises_ValueError_and_sends_NOTHING(self, authed, transport):
        with pytest.raises(ValueError, match='at least one of stop_level or profit_level'):
            authed.update_position('D1')
        assert transport.n == 0

    def test_failures_are_re_raised_so_stop_manager_can_retry(self, authed, transport):
        """`core/stop_manager.py` relies on a failed amend leaving its tracked
        state untouched so the next tick retries (gotcha 16)."""
        transport.push(make_response(400, reason='Bad Request'))
        with pytest.raises(requests.exceptions.HTTPError):
            authed.update_position('D1', stop_level=4100.0)


class TestAccountAndMarkets:

    def test_get_account_info_returns_the_whole_body(self, authed, transport):
        transport.push(make_response(200, {'accounts': [{'balance': {'balance': 10000}}]}))
        out = authed.get_account_info()
        assert transport.call(0).url == DEMO_URL + '/api/v1/accounts'
        assert out == {'accounts': [{'balance': {'balance': 10000}}]}

    def test_get_account_info_re_raises(self, authed, transport):
        transport.push(make_response(500, reason='Internal Server Error'))
        with pytest.raises(requests.exceptions.HTTPError):
            authed.get_account_info()

    def test_find_market_sends_the_search_term(self, authed, transport):
        transport.push(make_response(200, {'markets': [{'epic': 'GOLD'}]}))
        out = authed.find_market('GOLD')
        assert transport.call(0).url == DEMO_URL + '/api/v1/markets'
        assert transport.call(0).params == {'searchTerm': 'GOLD'}
        assert out == [{'epic': 'GOLD'}]

    def test_find_market_with_no_matches_is_an_empty_list(self, authed, transport):
        transport.push(make_response(200, {}))
        assert authed.find_market('NOPE') == []

    def test_find_market_re_raises(self, authed, transport):
        transport.push(requests.exceptions.Timeout('read timed out'))
        with pytest.raises(requests.exceptions.Timeout):
            authed.find_market('GOLD')


# ────────────────────────────────────────────────────────────────────────────
#  get_historical_prices — biggest uncovered block, and a proven bug site.
#  This is the function whose date-filter bug starved the bars for two
#  quarters (gotchas 29, 38), and the one that fills the live warm-up buffer
#  (main.py:681 / :700 / :710).
# ────────────────────────────────────────────────────────────────────────────

def price_row(snap='2026/10/22 12:00:00:000', snap_utc='2026/10/22 10:00:00:000',
              o=4100.0, h=4110.0, lo=4090.0, c=4105.0, vol=1234):
    """One /prices row in the broker's real shape: bid/ask per OHLC field, and
    BOTH a local `snapshotTime` and a UTC `snapshotTimeUTC`."""
    def leg(bid):
        return {'bid': bid, 'ask': bid + 0.3}
    return {
        'snapshotTime': snap,
        'snapshotTimeUTC': snap_utc,
        'openPrice': leg(o), 'highPrice': leg(h),
        'lowPrice': leg(lo), 'closePrice': leg(c),
        'lastTradedVolume': vol,
    }


class TestHistoricalPricesRequest:

    def test_path_and_default_params(self, authed, transport):
        transport.push(make_response(200, {'prices': [price_row()]}))
        authed.get_historical_prices('GOLD')
        call = transport.call(0)
        assert call.url == DEMO_URL + '/api/v1/prices/GOLD'
        assert call.params == {'resolution': 'MINUTE_5', 'max': 100}

    def test_resolution_and_max_are_forwarded(self, authed, transport):
        transport.push(make_response(200, {'prices': [price_row()]}))
        authed.get_historical_prices('US100', resolution='HOUR', max_bars=500)
        assert transport.call(0).params == {'resolution': 'HOUR', 'max': 500}

    def test_max_is_capped_at_the_api_limit_of_1000(self, authed, transport):
        transport.push(make_response(200, {'prices': [price_row()]}))
        authed.get_historical_prices('GOLD', max_bars=5000)
        assert transport.call(0).params['max'] == 1000

    def test_date_params_are_omitted_unless_given(self, authed, transport):
        transport.push(make_response(200, {'prices': [price_row()]}))
        authed.get_historical_prices('GOLD')
        assert 'from' not in transport.call(0).params
        assert 'to' not in transport.call(0).params

    @pytest.mark.parametrize('kwargs,key', [
        ({'from_date': '2026-10-01T00:00:00'}, 'from'),
        ({'to_date': '2026-10-02T00:00:00'}, 'to'),
    ])
    def test_either_date_bound_can_be_sent_alone(self, authed, transport, kwargs, key):
        transport.push(make_response(200, {'prices': [price_row()]}))
        authed.get_historical_prices('GOLD', **kwargs)
        assert key in transport.call(0).params


class TestHistoricalPricesHasNoDateRangeMode:
    """
    `from` + `to` together returns **400** on this API — there is no date-range
    mode, only backward pagination on `to` + `max` (gotcha 30).

    The client does not know that: it forwards both, and the **docstring's own
    worked example passes both**, so following the documentation produces a
    guaranteed 400.  Pinned rather than fixed: rejecting the combination
    client-side is a behaviour change to a public signature, and callers that
    work (`fetch_data.py --bars N`) do not use it.  The hazard is the example.
    """

    def test_both_bounds_are_forwarded_even_though_the_api_rejects_that(self, authed,
                                                                       transport):
        transport.push(make_response(200, {'prices': [price_row()]}))
        authed.get_historical_prices('GOLD',
                                     from_date='2026-10-01T00:00:00',
                                     to_date='2026-10-02T00:00:00')
        params = transport.call(0).params
        assert params['from'] == '2026-10-01T00:00:00'
        assert params['to'] == '2026-10-02T00:00:00'

    def test_the_resulting_400_is_raised_to_the_caller(self, authed, transport):
        transport.push(make_response(400, {'errorCode': 'error.invalid.daterange'},
                                     reason='Bad Request'))
        with pytest.raises(requests.exceptions.HTTPError):
            authed.get_historical_prices('GOLD',
                                         from_date='2026-10-01T00:00:00',
                                         to_date='2026-10-02T00:00:00')


class TestHistoricalPricesTimestampField:
    """
    Which of the two timestamp fields wins, and why it matters.

    The API returns `snapshotTime` in **account-local** time (UTC+2, and it
    varies with DST) alongside `snapshotTimeUTC` (gotchas 30, 38).  The DB
    writer picks UTC and says why — `fetch_data.py:145`, "snapshotTime is
    local/exchange time and varies with DST".

    This client used to pick the opposite one, so the two readers of the same
    endpoint disagreed by the account offset: backtest/DB bars in UTC, the live
    warm-up buffer 2h ahead.  Now aligned on `snapshotTimeUTC`.
    """

    def test_the_utc_field_wins(self, authed, transport):
        transport.push(make_response(200, {'prices': [price_row(
            snap='2026/10/22 12:00:00:000', snap_utc='2026/10/22 10:00:00:000')]}))
        got = authed.get_historical_prices('GOLD')
        assert got[0]['timestamp'] == '2026/10/22 10:00:00:000'

    def test_it_falls_back_to_the_local_field_when_utc_is_absent(self, authed, transport):
        row = price_row()
        del row['snapshotTimeUTC']
        transport.push(make_response(200, {'prices': [row]}))
        got = authed.get_historical_prices('GOLD')
        assert got[0]['timestamp'] == '2026/10/22 12:00:00:000'

    def test_both_fields_missing_yields_an_empty_string_not_a_crash(self, authed,
                                                                   transport):
        row = price_row()
        del row['snapshotTimeUTC'], row['snapshotTime']
        transport.push(make_response(200, {'prices': [row]}))
        assert authed.get_historical_prices('GOLD')[0]['timestamp'] == ''

    def test_it_now_agrees_with_the_db_writer_on_the_same_row(self, authed, transport):
        """The actual regression: `fetch_data.parse_candle` and this function
        must choose the same field, or the backtest and the live warm-up buffer
        are two hours apart on identical broker data."""
        from fetch_data import parse_candle
        row = price_row(snap='2026/10/22 12:00:00:000',
                        snap_utc='2026/10/22 10:00:00:000')
        transport.push(make_response(200, {'prices': [row]}))
        live = authed.get_historical_prices('GOLD')[0]['timestamp']
        db = parse_candle(row)['timestamp']
        assert db == '2026-10-22 10:00:00'
        assert live.replace('/', '-')[:19] == db


class TestHistoricalPricesCandleMapping:

    def test_maps_bid_ohlc_and_volume(self, authed, transport):
        transport.push(make_response(200, {'prices': [price_row()]}))
        assert authed.get_historical_prices('GOLD') == [{
            'timestamp': '2026/10/22 10:00:00:000',
            'open': 4100.0, 'high': 4110.0, 'low': 4090.0, 'close': 4105.0,
            'volume': 1234,
        }]

    def test_bid_is_used_and_ask_ignored(self, authed, transport):
        """The live bot's Supertrend runs on bid-based candles; using mid or ask
        would shift every price and corrupt the trail's direction state."""
        transport.push(make_response(200, {'prices': [price_row(c=4105.0)]}))
        got = authed.get_historical_prices('GOLD')[0]
        assert got['close'] == 4105.0        # not 4105.3, the ask

    def test_missing_ohlc_blocks_become_zero(self, authed, transport):
        transport.push(make_response(200, {'prices': [{
            'snapshotTimeUTC': '2026/10/22 10:00:00:000'}]}))
        got = authed.get_historical_prices('GOLD')[0]
        assert (got['open'], got['high'], got['low'], got['close']) == (0.0, 0.0, 0.0, 0.0)
        assert got['volume'] == 0

    def test_a_float_volume_is_truncated_to_int(self, authed, transport):
        transport.push(make_response(200, {'prices': [price_row(vol=1234.9)]}))
        assert authed.get_historical_prices('GOLD')[0]['volume'] == 1234

    def test_only_the_last_max_bars_are_returned(self, authed, transport):
        rows = [price_row(snap_utc=f'2026/10/22 1{i}:00:00:000', c=4100.0 + i)
                for i in range(5)]
        transport.push(make_response(200, {'prices': rows}))
        got = authed.get_historical_prices('GOLD', max_bars=2)
        assert [c['close'] for c in got] == [4103.0, 4104.0]

    def test_a_null_price_block_raises_rather_than_inventing_a_price(self, authed,
                                                                    transport):
        """`price.get('openPrice', {})` only defaults when the KEY IS ABSENT, so
        an explicit JSON null reaches `.get` on None.  It raises, the warm-up in
        `main.py:687` logs "M5 prefetch failed — continuing without warm-up",
        and the bot starts with cold indicators instead of fabricated prices.
        Failing closed is the right direction here; pinned so it stays known."""
        row = price_row()
        row['openPrice'] = None
        transport.push(make_response(200, {'prices': [row]}))
        with pytest.raises(AttributeError):
            authed.get_historical_prices('GOLD')

    def test_a_null_bid_raises_too(self, authed, transport):
        row = price_row()
        row['closePrice'] = {'bid': None, 'ask': 4105.3}
        transport.push(make_response(200, {'prices': [row]}))
        with pytest.raises(TypeError):
            authed.get_historical_prices('GOLD')

    def test_unlike_the_db_writer_there_is_no_ask_fallback(self, authed, transport):
        """`fetch_data.parse_candle` falls back bid -> ask; this does not.  The
        divergence is deliberate on this side — substituting an ask for a bid
        shifts the candle by the spread, which is the same corruption
        `parse_candle`'s own comment warns against for mid prices.  Pinned, not
        aligned, because the two functions fail in opposite directions on the
        same row and only one of them can be right."""
        row = price_row()
        row['closePrice'] = {'ask': 4105.3}
        transport.push(make_response(200, {'prices': [row]}))
        assert authed.get_historical_prices('GOLD')[0]['close'] == 0.0


class TestHistoricalPricesEmptyAndErrors:

    def test_no_prices_returns_an_empty_list_without_raising(self, authed, transport):
        transport.push(make_response(200, {'prices': []}))
        assert authed.get_historical_prices('GOLD') == []

    def test_a_missing_prices_key_is_also_an_empty_list(self, authed, transport):
        transport.push(make_response(200, {}))
        assert authed.get_historical_prices('GOLD') == []

    def test_an_empty_result_is_a_WARNING_not_an_error(self, authed, transport, caplog):
        """This is the exact signature of gotcha 29: `bar_updater` logged
        "no new candles" at WARNING every 15 minutes for two quarters and
        nobody saw it, because an empty fetch is indistinguishable from a
        closed market at this layer."""
        transport.push(make_response(200, {'prices': []}))
        with caplog.at_level('WARNING'):
            authed.get_historical_prices('GOLD')
        assert 'No historical data returned' in caplog.text
        assert not [r for r in caplog.records if r.levelname == 'ERROR']

    def test_a_404_names_the_epic_and_re_raises(self, authed, transport, caplog):
        transport.push(make_response(404, reason='Not Found'))
        with caplog.at_level('ERROR'):
            with pytest.raises(requests.exceptions.HTTPError):
                authed.get_historical_prices('NOSUCH')
        assert "Epic 'NOSUCH' not found" in caplog.text

    def test_other_http_errors_take_the_generic_branch_and_re_raise(self, authed,
                                                                   transport, caplog):
        transport.push(make_response(500, reason='Internal Server Error'))
        with caplog.at_level('ERROR'):
            with pytest.raises(requests.exceptions.HTTPError):
                authed.get_historical_prices('GOLD')
        assert 'Failed to fetch historical prices' in caplog.text

    def test_a_429_surfaces_as_a_rate_limit_not_a_404(self, authed, transport):
        transport.push(rate_limited())
        with pytest.raises(Exception, match='Rate limit exceeded on /api/v1/prices/GOLD'):
            authed.get_historical_prices('GOLD')

    def test_transport_errors_take_the_generic_branch_and_re_raise(self, authed,
                                                                  transport, caplog):
        transport.push(requests.exceptions.ConnectionError('dns failure'))
        with caplog.at_level('ERROR'):
            with pytest.raises(requests.exceptions.ConnectionError):
                authed.get_historical_prices('GOLD')
        assert 'Error fetching historical prices' in caplog.text


# ────────────────────────────────────────────────────────────────────────────
#  The two functions that swallow failures, and why each is the way it is
# ────────────────────────────────────────────────────────────────────────────

class TestGetActivitySwallowsFailures:
    """
    `get_activity` returns `[]` on any exception, so a transient network error
    is **indistinguishable from "nothing happened"**.

    That is precisely the shape of gotcha 22: for ~3 months this function
    returned `[]` for a different reason (the `status==EXECUTED` filter matched
    nothing), and because an empty list is a legitimate answer, nothing anywhere
    noticed.  The consequence chain was P&L recorded as 0.0, SL/TP cooldowns
    that never fired, every trade scored a win, and `max_daily_loss_usd` pinned
    at zero.

    Kept swallowing deliberately — this is polled every 10s from
    `_poll_positions` and raising would take the loop down — but pinned here so
    the blind spot is documented rather than rediscovered.
    """

    @pytest.mark.parametrize('queued', [
        make_response(400, reason='Bad Request'),
        make_response(500, reason='Internal Server Error'),
        requests.exceptions.ConnectionError('dns failure'),
        requests.exceptions.Timeout('read timed out'),
    ])
    def test_every_failure_mode_returns_an_empty_list(self, authed, transport, queued):
        transport.push(queued)
        assert authed.get_activity() == []

    def test_a_429_is_also_swallowed(self, authed, transport):
        transport.push(rate_limited())
        assert authed.get_activity() == []

    def test_failure_is_indistinguishable_from_a_quiet_market(self, authed, transport):
        transport.push(make_response(200, {'activities': []}))
        quiet = authed.get_activity()
        transport.push(requests.exceptions.ConnectionError('dns failure'))
        broken = authed.get_activity()
        assert quiet == broken == []

    def test_the_failure_is_logged_at_ERROR_so_it_is_at_least_greppable(self, authed,
                                                                       transport, caplog):
        transport.push(requests.exceptions.ConnectionError('dns failure'))
        with caplog.at_level('ERROR'):
            authed.get_activity()
        assert 'Failed to get activity' in caplog.text

    def test_the_default_lookback_is_120_seconds(self, authed, transport):
        transport.push(make_response(200, {'activities': []}))
        authed.get_activity()
        assert transport.call(0).params['lastPeriod'] == 120


class TestRealisedPnlUnknownStaysUnknown:
    """
    `None` means "unknown" and must never become `0.0`.

    Coercing it is the shared root cause of gotcha 22 (every trade scored a win
    because `is_loss = pnl < 0` with `pnl == 0.0`) and gotcha 49a (the reverse
    close invented `pnl=0.0`, leaving the daily-loss accumulator at zero and the
    consecutive-loss breaker untripped through four straight losses).
    """

    def test_a_failed_lookup_returns_None_not_zero(self, authed, transport):
        transport.push(requests.exceptions.ConnectionError('dns failure'))
        out = authed.get_realised_pnl('D1')
        assert out is None
        assert out != 0.0

    @pytest.mark.parametrize('queued', [
        make_response(400, reason='Bad Request'),
        make_response(500, reason='Internal Server Error'),
    ])
    def test_http_errors_also_return_None(self, authed, transport, queued):
        transport.push(queued)
        assert authed.get_realised_pnl('D1') is None

    def test_the_failure_is_logged_at_WARNING(self, authed, transport, caplog):
        transport.push(requests.exceptions.Timeout('read timed out'))
        with caplog.at_level('WARNING'):
            authed.get_realised_pnl('D1')
        assert 'Could not fetch realised P&L' in caplog.text

    @pytest.mark.parametrize('size', ['', 'n/a', None, {}, 'EUR 12.50'])
    def test_a_non_numeric_pnl_is_unknown_not_zero(self, authed, transport, size):
        transport.push(make_response(200, {'transactions': [
            {'dealId': 'D1', 'transactionType': 'TRADE', 'size': size}]}))
        assert authed.get_realised_pnl('D1') is None

    def test_a_non_numeric_pnl_warns_so_it_is_not_silent(self, authed, transport, caplog):
        transport.push(make_response(200, {'transactions': [
            {'dealId': 'D1', 'transactionType': 'TRADE', 'size': 'n/a'}]}))
        with caplog.at_level('WARNING'):
            authed.get_realised_pnl('D1')
        assert 'Non-numeric P&L' in caplog.text

    def test_a_genuine_break_even_stays_zero_and_is_NOT_None(self, authed, transport):
        """The distinction that matters: the broker really can report 0.00.
        `0.0` is a fact, `None` is an absence, and the risk breakers treat them
        differently (gotcha 38)."""
        transport.push(make_response(200, {'transactions': [
            {'dealId': 'D1', 'transactionType': 'TRADE', 'size': '0.00'}]}))
        out = authed.get_realised_pnl('D1')
        assert out == 0.0
        assert out is not None

    def test_a_negative_pnl_is_read_as_a_loss(self, authed, transport):
        transport.push(make_response(200, {'transactions': [
            {'dealId': 'D1', 'transactionType': 'TRADE', 'size': '-45.30'}]}))
        assert authed.get_realised_pnl('D1') == -45.30

    def test_the_first_matching_trade_row_wins(self, authed, transport):
        transport.push(make_response(200, {'transactions': [
            {'dealId': 'D1', 'transactionType': 'TRADE', 'size': '10.0'},
            {'dealId': 'D1', 'transactionType': 'TRADE', 'size': '99.0'}]}))
        assert authed.get_realised_pnl('D1') == 10.0

    def test_lastperiod_is_capped_at_the_api_maximum(self, authed, transport):
        transport.push(make_response(200, {'transactions': []}))
        authed.get_realised_pnl('D1', last_period_seconds=7 * 24 * 3600)
        assert transport.call(0).params == {'lastPeriod': 86400}

    def test_a_float_lookback_is_coerced_to_int(self, authed, transport):
        transport.push(make_response(200, {'transactions': []}))
        authed.get_realised_pnl('D1', last_period_seconds=120.9)
        assert transport.call(0).params == {'lastPeriod': 120}

    def test_only_the_upper_bound_is_clamped(self, authed, transport):
        """`min(x, 86400)` caps the top and nothing guards the bottom, so a
        nonsensical negative window is forwarded as-is for the API to reject."""
        transport.push(make_response(200, {'transactions': []}))
        authed.get_realised_pnl('D1', last_period_seconds=-5)
        assert transport.call(0).params == {'lastPeriod': -5}


# ────────────────────────────────────────────────────────────────────────────
#  __init__ — credential and environment wiring
# ────────────────────────────────────────────────────────────────────────────

class TestInit:

    def test_explicit_arguments_win_over_the_environment(self, monkeypatch):
        monkeypatch.setenv('CAPITAL_USERNAME', 'env@example.com')
        monkeypatch.setenv('CAPITAL_PASSWORD', 'env-pw')
        monkeypatch.setenv('CAPITAL_API_KEY', 'env-key')
        c = CapitalAPIClient(username='arg@example.com', password='arg-pw',
                             api_key='arg-key')
        assert (c.username, c.password, c.api_key) == ('arg@example.com',
                                                       'arg-pw', 'arg-key')

    def test_CAPITAL_IDENTIFIER_is_preferred_over_CAPITAL_USERNAME(self, clean_env,
                                                                  monkeypatch):
        monkeypatch.setenv('CAPITAL_IDENTIFIER', 'identifier@example.com')
        monkeypatch.setenv('CAPITAL_USERNAME', 'username@example.com')
        assert CapitalAPIClient().username == 'identifier@example.com'

    def test_CAPITAL_USERNAME_is_the_fallback(self, clean_env, monkeypatch):
        monkeypatch.setenv('CAPITAL_USERNAME', 'username@example.com')
        assert CapitalAPIClient().username == 'username@example.com'

    def test_password_and_key_come_from_the_environment(self, clean_env, monkeypatch):
        monkeypatch.setenv('CAPITAL_PASSWORD', 'env-pw')
        monkeypatch.setenv('CAPITAL_API_KEY', 'env-key')
        c = CapitalAPIClient()
        assert (c.password, c.api_key) == ('env-pw', 'env-key')

    def test_absent_credentials_are_None_not_an_error(self, clean_env):
        """Construction never validates; the failure surfaces at
        `create_session` instead."""
        c = CapitalAPIClient()
        assert (c.username, c.password, c.api_key) == (None, None, None)

    def test_a_fresh_client_holds_no_session(self, client):
        assert client.cst is None
        assert client.security_token is None
        assert 'valid' not in client._token_cache

    @pytest.mark.parametrize('env,expected', [
        ('demo', DEMO_URL), ('live', LIVE_URL),
        ('LIVE', LIVE_URL), ('Demo', DEMO_URL),
    ])
    def test_environment_selects_the_base_url_case_insensitively(self, clean_env,
                                                                 env, expected):
        assert CapitalAPIClient(environment=env).base_url == expected

    @pytest.mark.parametrize('env', ['liv', 'production', 'LIVE ', 'real'])
    def test_an_unrecognised_environment_falls_back_to_DEMO(self, clean_env, env):
        """Only the exact string 'live' selects the live endpoint, so a typo
        fails safe towards demo rather than towards real money."""
        assert CapitalAPIClient(environment=env).base_url == DEMO_URL


class TestCapitalEnvironmentEnvVarIsShadowed:
    """
    `CAPITAL_ENVIRONMENT` is documented in CLAUDE.md as the env var that selects
    demo vs live, but the signature default is the non-empty string `'demo'`:

        self.environment = (environment or os.getenv('CAPITAL_ENVIRONMENT', 'demo')).lower()

    `'demo' or ...` short-circuits, so the env var is only consulted when a
    caller explicitly passes a falsy `environment`.  Setting
    `CAPITAL_ENVIRONMENT=live` in `.env` therefore does **nothing** for any
    caller that omits the argument.

    Pinned, not fixed, and the direction matters: the shadowing fails towards
    **demo**, so honouring the env var would make it newly possible to send real
    orders by editing a dotenv file.  That is a deliberate decision to make, not
    a bug to quietly correct inside a coverage session.
    """

    def test_the_env_var_is_ignored_when_environment_is_defaulted(self, clean_env,
                                                                  monkeypatch):
        monkeypatch.setenv('CAPITAL_ENVIRONMENT', 'live')
        assert CapitalAPIClient().base_url == DEMO_URL
        assert CapitalAPIClient().environment == 'demo'

    @pytest.mark.parametrize('falsy', [None, ''])
    def test_the_env_var_is_honoured_only_when_environment_is_falsy(self, clean_env,
                                                                    monkeypatch, falsy):
        monkeypatch.setenv('CAPITAL_ENVIRONMENT', 'live')
        assert CapitalAPIClient(environment=falsy).base_url == LIVE_URL

    def test_with_no_env_var_a_falsy_environment_still_means_demo(self, clean_env):
        assert CapitalAPIClient(environment=None).base_url == DEMO_URL

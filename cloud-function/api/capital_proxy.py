"""
Capital.com API proxy — authenticates once and proxies trading requests.

Credentials come from env vars (set in .env or docker-compose):
  CAPITAL_API_KEY, CAPITAL_IDENTIFIER, CAPITAL_PASSWORD
  CAPITAL_ENV = demo | live   (default: demo)
"""

import os
import time
import logging
import requests
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

CAPITAL_URLS = {
    "demo": "https://demo-api-capital.backend-capital.com",
    "live": "https://api-capital.backend-capital.com",
}

_session_cache: Dict[str, Any] = {}   # {env: {token, account_id, expires_at}}


def _base_url() -> str:
    env = os.getenv("CAPITAL_ENV", "demo").lower()
    return CAPITAL_URLS.get(env, CAPITAL_URLS["demo"])


def _credentials():
    return {
        "apiKey": os.environ["CAPITAL_API_KEY"],
        "identifier": os.environ["CAPITAL_IDENTIFIER"],
        "password": os.environ["CAPITAL_PASSWORD"],
    }


def _get_session(force: bool = False) -> tuple[str, str]:
    """Return (CST token, X-SECURITY-TOKEN). Re-authenticates if expired."""
    env = os.getenv("CAPITAL_ENV", "demo")
    cached = _session_cache.get(env, {})

    if not force and cached.get("expires_at", 0) > time.time() + 60:
        return cached["cst"], cached["security"]

    base = _base_url()
    creds = _credentials()
    resp = requests.post(
        f"{base}/api/v1/session",
        json=creds,
        headers={"X-CAP-API-KEY": creds["apiKey"]},
        timeout=10,
    )
    resp.raise_for_status()

    cst = resp.headers.get("CST", "")
    security = resp.headers.get("X-SECURITY-TOKEN", "")

    _session_cache[env] = {
        "cst": cst,
        "security": security,
        "expires_at": time.time() + 3600,  # tokens last ~10h but refresh hourly
    }
    logger.info("Capital.com session refreshed")
    return cst, security


def _headers() -> Dict[str, str]:
    cst, security = _get_session()
    return {
        "X-CAP-API-KEY": _credentials()["apiKey"],
        "CST": cst,
        "X-SECURITY-TOKEN": security,
        "Content-Type": "application/json",
    }


def _request(method: str, path: str, **kwargs) -> Any:
    """Make an authenticated request; retry once on 401."""
    base = _base_url()
    try:
        resp = requests.request(
            method,
            f"{base}{path}",
            headers=_headers(),
            timeout=15,
            **kwargs,
        )
        if resp.status_code == 401:
            _get_session(force=True)
            resp = requests.request(
                method,
                f"{base}{path}",
                headers=_headers(),
                timeout=15,
                **kwargs,
            )
        resp.raise_for_status()
        return resp.json()
    except requests.HTTPError as e:
        try:
            detail = e.response.json()
        except Exception:
            detail = str(e)
        raise CapitalError(e.response.status_code, detail) from e


class CapitalError(Exception):
    def __init__(self, status_code: int, detail: Any):
        self.status_code = status_code
        self.detail = detail
        super().__init__(str(detail))


# ── Public proxy functions ────────────────────────────────────────────────────

def get_positions() -> Dict:
    return _request("GET", "/api/v1/positions")


def create_position(payload: Dict) -> Dict:
    return _request("POST", "/api/v1/positions", json=payload)


def update_position(deal_id: str, payload: Dict) -> Dict:
    return _request("PUT", f"/api/v1/positions/{deal_id}", json=payload)


def close_position(deal_id: str) -> Dict:
    return _request("DELETE", f"/api/v1/positions/{deal_id}")


def get_market(epic: str) -> Dict:
    return _request("GET", f"/api/v1/markets/{epic}")


def get_prices(epic: str, resolution: str = "HOUR", max_points: int = 50,
               from_ts: Optional[str] = None, to_ts: Optional[str] = None) -> Dict:
    params: Dict[str, Any] = {"resolution": resolution, "max": max_points}
    if from_ts:
        params["from"] = from_ts
    if to_ts:
        params["to"] = to_ts
    return _request("GET", f"/api/v1/prices/{epic}", params=params)


def get_markets(search_term: Optional[str] = None) -> Dict:
    params = {}
    if search_term:
        params["searchTerm"] = search_term
    return _request("GET", "/api/v1/markets", params=params)

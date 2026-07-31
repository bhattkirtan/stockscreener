"""
Broker-side stop management — breakeven + trailing stop.

Unlike the tick exit in AnalysisSkill (which closes the whole position at
market when the Supertrend band is crossed), this module *amends the stop
order held at the broker* via PUT /api/v1/positions/{dealId}.

Why that matters: the tick exit only works while the WebSocket quote stream
is alive.  A stop that lives at the broker survives a dropped connection, a
bot crash, or a container restart.

Both features are opt-in and default OFF — with `enabled: false` this module
never issues a single REST call.

Config (`risk.stop_management`):

    stop_management:
      enabled: true
      check_interval_sec: 5      # min seconds between amends for one position
      min_step_pips: 1.0         # ignore improvements smaller than this
      breakeven:
        enabled: true
        trigger_pips: 20         # profit needed to arm breakeven
        offset_pips: 2           # stop = entry ± offset (positive = locks in profit)
      trailing:
        enabled: true
        start_pips: 25           # profit needed before trailing begins
        distance_pips: 15        # stop stays this far behind the best price

Invariants:
  - A stop is only ever moved in the protective direction (up for BUY, down
    for SELL).  It is never widened, so a spurious price spike cannot
    increase risk.
  - Trailing is driven off the best price seen since entry, not the current
    price, so the stop does not retreat when price pulls back.
  - A candidate stop that is already through the current price is skipped —
    the broker would reject it, and it would amount to a market close.
"""

import asyncio
import logging
import time
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class StopManager:
    """
    Tracks open positions and ratchets their broker-side stop loss.

    Wiring (see orchestrator/main.py):
      - `sync_positions()` is called by the position poller with the current
        broker position map, so entry price / direction / stop stay accurate.
      - `on_price()` is called from the live quote stream on every tick.
    """

    def __init__(self, capital_client, config: Dict, pip_size: float = 1.0):
        cfg = (config or {}).get('stop_management', {}) or {}
        self.capital = capital_client
        self.enabled = bool(cfg.get('enabled', False))

        self.check_interval_sec = float(cfg.get('check_interval_sec', 5))
        self.min_step_pips = float(cfg.get('min_step_pips', 1.0))
        self.pip_size = float(pip_size or 1.0)

        be = cfg.get('breakeven', {}) or {}
        self.be_enabled = bool(be.get('enabled', False))
        self.be_trigger_pips = float(be.get('trigger_pips', 20))
        self.be_offset_pips = float(be.get('offset_pips', 0))

        tr = cfg.get('trailing', {}) or {}
        self.trail_enabled = bool(tr.get('enabled', False))
        self.trail_start_pips = float(tr.get('start_pips', 25))
        self.trail_distance_pips = float(tr.get('distance_pips', 15))

        # deal_id -> {direction, entry, stop, best_price, last_amend_ts}
        self._positions: Dict[str, Dict] = {}
        self._lock = asyncio.Lock()

        if self.enabled:
            logger.info(
                f"🛡️ StopManager active (pip={self.pip_size}): "
                f"breakeven={'ON @' + str(self.be_trigger_pips) + 'p→+' + str(self.be_offset_pips) + 'p' if self.be_enabled else 'OFF'}, "
                f"trailing={'ON @' + str(self.trail_start_pips) + 'p, dist ' + str(self.trail_distance_pips) + 'p' if self.trail_enabled else 'OFF'}"
            )
        else:
            logger.info("🛡️ StopManager disabled (risk.stop_management.enabled: false)")

    # ── Position bookkeeping ─────────────────────────────────────────────────

    def sync_positions(self, positions: Dict[str, Dict]) -> None:
        """
        Reconcile tracked state against the broker's open positions.

        `positions` maps deal_id -> raw broker position dict (the same shape
        `_poll_positions` keeps in its `known` map).
        """
        if not self.enabled:
            return

        for deal_id, pos in positions.items():
            entry = float(pos.get('level') or pos.get('entry_price') or 0.0)
            direction = (pos.get('direction') or 'BUY').upper()
            stop_raw = pos.get('stopLevel', pos.get('stop_loss'))
            stop = float(stop_raw) if stop_raw not in (None, '') else None

            existing = self._positions.get(deal_id)
            if existing is None:
                self._positions[deal_id] = {
                    'direction': direction,
                    'entry': entry,
                    'stop': stop,
                    'best_price': entry,
                    'last_amend_ts': 0.0,
                }
            else:
                existing['direction'] = direction
                if entry:
                    existing['entry'] = entry
                # Trust the broker's stop — it is the source of truth, and it
                # may have been changed outside this process.
                if stop is not None:
                    existing['stop'] = stop

        # Drop positions the broker no longer reports
        for deal_id in list(self._positions):
            if deal_id not in positions:
                self._positions.pop(deal_id, None)

    def forget(self, deal_id: str) -> None:
        """Stop tracking a closed position."""
        self._positions.pop(deal_id, None)

    # ── Stop calculation ─────────────────────────────────────────────────────

    def _desired_stop(self, state: Dict, price: float) -> Optional[float]:
        """
        Return the tightest armed stop for this position, or None if no rule
        has triggered yet.
        """
        direction = state['direction']
        entry = state['entry']
        if not entry:
            return None

        sign = 1.0 if direction == 'BUY' else -1.0
        pip = self.pip_size

        # Profit measured against the best price seen, so a pullback does not
        # disarm a rule that has already triggered.
        best = state['best_price']
        profit_pips = (best - entry) * sign / pip

        candidates = []

        if self.be_enabled and profit_pips >= self.be_trigger_pips:
            candidates.append(entry + sign * self.be_offset_pips * pip)

        if self.trail_enabled and profit_pips >= self.trail_start_pips:
            candidates.append(best - sign * self.trail_distance_pips * pip)

        if not candidates:
            return None

        # Most protective candidate: highest for BUY, lowest for SELL
        return max(candidates) if direction == 'BUY' else min(candidates)

    def _is_improvement(self, state: Dict, new_stop: float, price: float) -> bool:
        direction = state['direction']
        sign = 1.0 if direction == 'BUY' else -1.0
        pip = self.pip_size

        # Never place a stop on the wrong side of the market — the broker
        # would reject it, and it would effectively be a market close.
        if (direction == 'BUY' and new_stop >= price) or (direction == 'SELL' and new_stop <= price):
            return False

        current = state.get('stop')
        if current is None:
            return True

        # Only tighten, and only by a meaningful amount
        improvement_pips = (new_stop - current) * sign / pip
        return improvement_pips >= self.min_step_pips

    # ── Tick handler ─────────────────────────────────────────────────────────

    async def on_price(self, price: float) -> None:
        """Called from the live quote stream. Cheap no-op when disabled."""
        if not self.enabled or not price or not self._positions:
            return

        now = time.monotonic()

        async with self._lock:
            for deal_id, state in list(self._positions.items()):
                sign = 1.0 if state['direction'] == 'BUY' else -1.0

                # Ratchet the best price seen since entry
                if (price - state['best_price']) * sign > 0:
                    state['best_price'] = price

                if (now - state['last_amend_ts']) < self.check_interval_sec:
                    continue

                new_stop = self._desired_stop(state, price)
                if new_stop is None or not self._is_improvement(state, new_stop, price):
                    continue

                # Reserve the slot before awaiting so concurrent ticks cannot
                # queue a second amend for the same position.
                state['last_amend_ts'] = now
                old_stop = state.get('stop')

                try:
                    await asyncio.to_thread(
                        self.capital.update_position,
                        deal_id=deal_id,
                        stop_level=round(new_stop, 5),
                    )
                except Exception as e:
                    logger.warning(f"⚠️ Stop amend failed for {deal_id}: {e}")
                    continue

                state['stop'] = new_stop
                logger.info(
                    f"🛡️ Stop moved {deal_id} ({state['direction']}): "
                    f"{old_stop} → {new_stop:.5f} "
                    f"(entry={state['entry']}, price={price}, best={state['best_price']})"
                )

#!/usr/bin/env python3
"""
verify_bots.py — Post-restart health check for all trading bots.

Run after the 21:00 UTC daily restart (or any restart) to confirm:
  1. All expected bot processes are running
  2. Each bot has received a real candle recently (not just session pings)
  3. Each bot's WebSocket is subscribed and active
  4. No runaway errors in the last 30 minutes
  5. Daily restart actually fired (for post-21:00 runs)

Usage:
  python3 /opt/stockscreener/verify_bots.py
  python3 /opt/stockscreener/verify_bots.py --container stockscreener-trading-bot-1
"""

import argparse
import json
import re
import subprocess
import sys
import urllib.request
from datetime import datetime, timedelta

# ── Config ─────────────────────────────────────────────────────────────────────

BOT_CONTROL_URL = "http://172.19.0.2:8020"
CONTAINER = "stockscreener-trading-bot-1"
LOG_DIR   = "/data"
EXPECTED_BOTS   = ["gold_m5_bot", "btcusd_m5_bot", "ethusd_m5_bot", "eurusd_m5_bot"]

# A bot is considered "live" if it logged something real within this window
CANDLE_STALE_MINUTES = 20

# Lines matching these patterns are NOT real candle/signal activity
NOISE_PATTERNS = re.compile(
    r"Session created successfully|"
    r"Saving position to Firestore|"
    r"Position saved|"
    r"sqlite_api"
)

# ── Helpers ────────────────────────────────────────────────────────────────────

GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
RESET  = "\033[0m"
BOLD   = "\033[1m"

def ok(msg):   print(f"  {GREEN}✓{RESET} {msg}")
def fail(msg): print(f"  {RED}✗{RESET} {msg}")
def warn(msg): print(f"  {YELLOW}!{RESET} {msg}")

def _api(path):
    try:
        with urllib.request.urlopen(f"{BOT_CONTROL_URL}{path}", timeout=5) as r:
            return json.loads(r.read())
    except Exception as e:
        return {"error": str(e)}

def _docker_tail(container, path, lines=200):
    try:
        result = subprocess.run(
            ["docker", "exec", container, "tail", f"-{lines}", path],
            capture_output=True, text=True, timeout=10
        )
        return result.stdout.splitlines()
    except Exception:
        return []

def _parse_ts(line):
    """Extract datetime from a log line like '2026-04-29 08:41:17 INFO ...'"""
    try:
        return datetime.strptime(line[:19], "%Y-%m-%d %H:%M:%S")
    except Exception:
        return None

# ── Checks ─────────────────────────────────────────────────────────────────────

def check_processes():
    """Check all expected bots are running via bot_control_api."""
    print(f"\n{BOLD}1. Process status{RESET}")
    data = _api("/process")
    if "error" in data:
        fail(f"bot_control_api unreachable: {data['error']}")
        return {}

    running = {b["bot_id"]: b for b in data.get("bots", []) if b.get("running")}
    results = {}
    for bot_id in EXPECTED_BOTS:
        if bot_id in running:
            started = running[bot_id].get("started_at", "?")
            ok(f"{bot_id}  pid={running[bot_id]['pid']}  started={started[:19]}")
            results[bot_id] = True
        else:
            fail(f"{bot_id}  NOT running")
            results[bot_id] = False

    extra = [b for b in running if b not in EXPECTED_BOTS]
    for b in extra:
        warn(f"unexpected bot running: {b}")

    return results


def check_candle_activity(bot_id):
    """Confirm the bot logged real candle/signal/trade activity recently."""
    log_path = f"{LOG_DIR}/{bot_id}.log"
    lines = _docker_tail(CONTAINER, log_path, lines=500)
    if not lines:
        return None, "log unreadable"

    now = datetime.utcnow()
    cutoff = now - timedelta(minutes=CANDLE_STALE_MINUTES)

    last_real_ts = None
    last_real_line = ""
    for line in reversed(lines):
        if NOISE_PATTERNS.search(line):
            continue
        ts = _parse_ts(line)
        if ts:
            last_real_ts = ts
            last_real_line = line[24:80].strip()  # snippet after timestamp+level
            break

    if last_real_ts is None:
        return False, "no real activity found in last 500 lines"
    if last_real_ts < cutoff:
        age = int((now - last_real_ts).total_seconds() / 60)
        return False, f"last real activity {age} min ago: {last_real_line}"
    age = int((now - last_real_ts).total_seconds() / 60)
    return True, f"{age} min ago — {last_real_line}"


def check_websocket(bot_id):
    """
    Infer WebSocket health from recent candle flow and absence of unrecovered errors.
    The connection message is only in the log at startup so we can't rely on it for
    long-running bots — flowing candles are the definitive proof the socket is alive.
    """
    log_path = f"{LOG_DIR}/{bot_id}.log"
    lines = _docker_tail(CONTAINER, log_path, lines=500)
    if not lines:
        return False, "log unreadable"

    now = datetime.utcnow()
    cutoff_candle = now - timedelta(minutes=CANDLE_STALE_MINUTES)
    cutoff_err    = now - timedelta(minutes=30)

    last_candle_ts = None
    watchdog_fired = False
    ws_errors_recent = 0

    for line in reversed(lines):
        if NOISE_PATTERNS.search(line):
            continue
        ts = _parse_ts(line)
        if not ts:
            continue
        if last_candle_ts is None and ("🕯️" in line or "MINUTE_5" in line or "CANDLE" in line.upper()):
            last_candle_ts = ts
        if "Candle watchdog" in line and "forcing WS reconnect" in line:
            watchdog_fired = True
        if ("WebSocket error" in line or "connection failed" in line.lower()) and ts > cutoff_err:
            ws_errors_recent += 1

    if last_candle_ts is None or last_candle_ts < cutoff_candle:
        return False, "no recent candles — WebSocket likely stale"

    notes = []
    if watchdog_fired:
        notes.append("watchdog triggered a reconnect (self-healed)")
    if ws_errors_recent:
        notes.append(f"{ws_errors_recent} WS error(s) in last 30 min")
    return True, ", ".join(notes) if notes else "active"


def check_daily_restart():
    """Check if the daily restart fired in the last 24 hours."""
    print(f"\n{BOLD}4. Daily restart{RESET}")
    now = datetime.utcnow()
    since = now - timedelta(hours=24)

    try:
        result = subprocess.run(
            ["docker", "logs", CONTAINER, "--since", since.strftime("%Y-%m-%dT%H:%M:%S")],
            capture_output=True, text=True, timeout=10
        )
        output = result.stdout + result.stderr
    except Exception:
        output = ""

    if "Daily restart at" in output:
        # Pull the exact line for the timestamp
        for line in output.splitlines():
            if "Daily restart at" in line:
                ok(f"Fired: {line.strip()}")
                return
    # Fallback: check gold log for a warm-up after 21:00
    gold_lines = _docker_tail(CONTAINER, f"{LOG_DIR}/gold_m5_bot.log", lines=500)
    for line in reversed(gold_lines):
        if "Warm-up done" in line:
            ts = _parse_ts(line)
            if ts and ts.hour >= 21:
                ok(f"Bot restarted at 21:00+ (warm-up at {ts.strftime('%Y-%m-%d %H:%M UTC')})")
                return
            break
    next_fire = now.replace(hour=21, minute=0, second=0, microsecond=0)
    if now.hour >= 21:
        next_fire += timedelta(days=1)
    mins = int((next_fire - now).total_seconds() / 60)
    warn(f"Not fired yet — next restart in ~{mins} min (at 21:00 UTC)")


def check_recent_errors():
    """Summarise unique error types across all bots in the last 30 min."""
    print(f"\n{BOLD}5. Recent errors (last 30 min){RESET}")
    cutoff = datetime.utcnow() - timedelta(minutes=30)
    found_any = False
    for bot_id in EXPECTED_BOTS:
        log_path = f"{LOG_DIR}/{bot_id}.log"
        lines = _docker_tail(CONTAINER, log_path, lines=300)
        errors = []
        for line in lines:
            if "ERROR" not in line and "❌" not in line:
                continue
            ts = _parse_ts(line)
            if ts and ts > cutoff:
                errors.append(line[24:100].strip())
        if errors:
            found_any = True
            fail(f"{bot_id}: {len(errors)} error(s)")
            for e in errors[:3]:
                print(f"       {e}")
            if len(errors) > 3:
                print(f"       ... and {len(errors)-3} more")
    if not found_any:
        ok("No errors in the last 30 minutes")


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    global CONTAINER, BOT_CONTROL_URL
    parser = argparse.ArgumentParser(description="Verify trading bot health post-restart")
    parser.add_argument("--container", default=CONTAINER, help="Docker container name")
    parser.add_argument("--url", default=BOT_CONTROL_URL, help="bot_control_api base URL")
    args = parser.parse_args()
    CONTAINER       = args.container
    BOT_CONTROL_URL = args.url

    now = datetime.utcnow()
    print(f"\n{BOLD}{'='*55}{RESET}")
    print(f"{BOLD}  Bot Health Verification  —  {now.strftime('%Y-%m-%d %H:%M UTC')}{RESET}")
    print(f"{BOLD}{'='*55}{RESET}")

    # 1. Processes
    running = check_processes()

    # 2. Candle activity + 3. WebSocket — per bot
    print(f"\n{BOLD}2. Candle activity  (stale = >{CANDLE_STALE_MINUTES} min){RESET}")
    candle_ok = {}
    for bot_id in EXPECTED_BOTS:
        live, msg = check_candle_activity(bot_id)
        if live is None:
            warn(f"{bot_id}: {msg}")
            candle_ok[bot_id] = False
        elif live:
            ok(f"{bot_id}: {msg}")
            candle_ok[bot_id] = True
        else:
            fail(f"{bot_id}: {msg}")
            candle_ok[bot_id] = False

    print(f"\n{BOLD}3. WebSocket status{RESET}")
    ws_ok = {}
    for bot_id in EXPECTED_BOTS:
        connected, msg = check_websocket(bot_id)
        if connected:
            ok(f"{bot_id}: {msg}")
            ws_ok[bot_id] = True
        else:
            fail(f"{bot_id}: {msg}")
            ws_ok[bot_id] = False

    check_daily_restart()
    check_recent_errors()

    # ── Summary ──────────────────────────────────────────────────────────────
    total = len(EXPECTED_BOTS)
    proc_pass    = sum(1 for v in running.values()   if v)
    candle_pass  = sum(1 for v in candle_ok.values() if v)
    ws_pass      = sum(1 for v in ws_ok.values()     if v)

    print(f"\n{BOLD}{'='*55}{RESET}")
    print(f"{BOLD}  Summary{RESET}")
    print(f"  Processes running : {proc_pass}/{total}")
    print(f"  Candles flowing   : {candle_pass}/{total}")
    print(f"  WebSocket active  : {ws_pass}/{total}")

    all_ok = proc_pass == total and candle_pass == total and ws_pass == total
    if all_ok:
        print(f"\n  {GREEN}{BOLD}ALL CLEAR — cleanup successful{RESET}")
    else:
        print(f"\n  {RED}{BOLD}ISSUES FOUND — review above{RESET}")
    print(f"{BOLD}{'='*55}{RESET}\n")

    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Report what is ACTUALLY deployed, by measuring the running containers.

Why this exists
---------------
On 2026-10-22 a deploy was carried out on a premise taken from CLAUDE.md:
"the live bots run code where get_activity() returns [], so every close records
pnl = 0.0".  That was false — the fix had shipped the previous day and the live
bots had been recording real P&L for 24 hours.  Nothing in the docs was lying
on purpose; a deploy simply happened without a doc update, and prose cannot
know what a container holds.

So: never infer deployment state from documentation, including CLAUDE.md gotcha
55 which records this.  Run this instead.

    python3 check_deployed.py            # human-readable report
    python3 check_deployed.py --quiet    # only the drift, for CI / a hook

Read-only: it inspects containers and reads YAML. It places no orders, creates
no broker session, and writes nothing.

Exit codes
    0  every tracked marker present in every container that should have it
    1  at least one container is BEHIND the host tree
    2  a container or docker itself is unreachable
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

# (symbol, path-relative-to-/app, which gotcha it belongs to)
# A marker is a symbol introduced by a specific fix, so its presence in the
# image is proof that fix shipped. Add a row whenever you land a live-path fix.
MARKERS = [
    ('status==ACCEPTED',      'clients/capital_api.py',                  '22  activity filter / live P&L'),
    ('get_realised_pnl',      'clients/capital_api.py',                  '38  realised P&L join'),
    ("get('snapshotTimeUTC') or", 'clients/capital_api.py',             '54  UTC warm-up timestamps'),
    ('_evaluate_entry_gates', 'skills/risk/risk_skill.py',               '41  unified gate chain'),
    ('startup_flip_gate',     'skills/risk/risk_skill.py',               '41  startup-gate opt-out key'),
    ('_is_duplicate_candle',  'skills/market_data/market_data_skill.py', '42  bounded candle dedup'),
    ('_run_skill',            'orchestrator/trading_orchestrator.py',    '49  skill error wrapper'),
    ('TimeBasedFlatten',      'core/time_exits.py',                      '51  time-based flatten'),
    ('_norm_ts',              'fetch_data.py',                           '29  bar_updater date filter'),
]

# Which markers each container is expected to carry. backtest-runner is
# knowingly stale (gotcha 25 / prompt 6) — listed so the drift is reported
# rather than forgotten.
CONTAINERS = {
    'stockscreener-trading-bot-1':     'live bots',
    'stockscreener-bar-updater-1':     'bar sync',
    'stockscreener-backtest-runner-1': 'UI backtests (known stale — prompt 6)',
}


def sh(*args, check=False):
    r = subprocess.run(args, capture_output=True, text=True)
    if check and r.returncode:
        raise RuntimeError(' '.join(args) + ': ' + r.stderr.strip())
    return r.stdout.strip(), r.returncode


def container_markers(container):
    """{label: True | False | None} for every marker. None = file absent.

    One python call, not a shell pipeline: `grep -c` exits 1 on zero matches,
    so the obvious `test -f x && grep -c s x || echo NOFILE` reports NOFILE for
    a file that exists but lacks the symbol — conflating "not deployed" with
    "file missing". Both are drift, but they are different diagnoses.
    """
    payload = json.dumps([[sym, path, label] for sym, path, label in MARKERS])
    code = (
        "import json, os, sys\n"
        "out = {}\n"
        "for sym, path, label in json.loads(sys.argv[1]):\n"
        "    f = '/app/' + path\n"
        "    if not os.path.exists(f):\n"
        "        out[label] = None\n"
        "    else:\n"
        "        out[label] = sym in open(f, encoding='utf-8', errors='replace').read()\n"
        "print(json.dumps(out))\n"
    )
    out, rc = sh('docker', 'exec', container, 'python3', '-c', code, payload)
    for line in out.splitlines():
        if line.startswith('{'):
            return json.loads(line)
    return {}


def host_has(symbol, path):
    f = HERE / path
    return f.exists() and symbol in f.read_text()


def running_bots(container):
    """[(instrument, quantity_or_None)] read from /proc — `ps` is NOT installed.

    Skips its OWN pid. Any string-based exclusion fails here: this function
    ships its filter text to the container, so the inspector's cmdline contains
    whatever tokens the filter looks for ('main.py', '--bot-id', ...). Worse, a
    `-c` cmdline contains newlines, so printing it split one phantom match into
    six rows and the count read 9 bots instead of 3. os.getpid() is the only
    filter that cannot match itself by construction.
    """
    code = (
        "import os\n"
        "me = str(os.getpid())\n"
        "for p in sorted(os.listdir('/proc')):\n"
        "    if not p.isdigit() or p == me: continue\n"
        "    try: cl = open('/proc/' + p + '/cmdline').read().replace(chr(0), ' ').strip()\n"
        "    except Exception: continue\n"
        "    if '--bot-id' in cl and 'main.py' in cl: print(' '.join(cl.split()))\n"
    )
    out, _ = sh('docker', 'exec', container, 'python3', '-c', code)
    bots = []
    for line in out.splitlines():
        t = line.split()
        instr = t[t.index('--instrument') + 1] if '--instrument' in t else '?'
        qty = t[t.index('--quantity') + 1] if '--quantity' in t else None
        bots.append((instr, qty))
    return bots


def effective_risk(container, instrument):
    code = (
        "import yaml,json\n"
        "b=yaml.safe_load(open('/app/config/trading_config.yaml'))\n"
        f"d=yaml.safe_load(open('/app/config/instruments/{instrument}.yaml'))\n"
        "r=dict(b.get('risk',{})); r.update(d.get('risk',{}))\n"
        "e=dict(b.get('execution',{})); e.update(d.get('execution',{}))\n"
        "print(json.dumps({'sl':r.get('stop_loss_pips'),'tp':r.get('take_profit_pips'),\n"
        "  'daily_loss':r.get('max_daily_loss_usd',0),'consec':r.get('max_consecutive_losses',0),\n"
        "  'flatten':(r.get('time_exits') or {}).get('enabled'),\n"
        "  'risk_ps':r.get('position_size'),'exec_ps':e.get('position_size'),\n"
        "  'root_ps':d.get('position_size')}))"
    )
    out, rc = sh('docker', 'exec', container, 'python3', '-c', code)
    for line in out.splitlines():
        if line.startswith('{'):
            return json.loads(line)
    return None


def bar_freshness(container):
    code = (
        "import sqlite3\n"
        "c=sqlite3.connect('/data/trading.db')\n"
        "for r in c.execute(\"SELECT epic,COUNT(*),MAX(timestamp) FROM candles \"\n"
        "                   \"WHERE timeframe='M5' GROUP BY epic\"): print('%s|%s|%s' % r)\n"
    )
    out, _ = sh('docker', 'exec', container, 'python3', '-c', code)
    return [l.split('|') for l in out.splitlines() if l.count('|') == 2]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--quiet', action='store_true', help='print only drift')
    args = ap.parse_args()

    _, rc = sh('docker', 'ps')
    if rc:
        print('docker unreachable — are you on the server?', file=sys.stderr)
        return 2

    drift = []
    for container, role in CONTAINERS.items():
        out, rc = sh('docker', 'inspect', container, '--format', '{{.Image}} {{.State.Status}}')
        if rc:
            print(f'{container}: NOT RUNNING ({role})')
            drift.append((container, 'not running'))
            continue
        image, status = (out.split() + ['?'])[:2]
        if not args.quiet:
            print(f'\n{container}  [{role}]')
            print(f'  image {image[:26]}…  status {status}')

        found = container_markers(container)
        for symbol, path, label in MARKERS:
            c, h = found.get(label), host_has(symbol, path)
            if c is h:
                mark, note = '  ok', ''
            elif h and not c:
                mark, note = 'BEHIND', '  <- host has it, container does not'
                drift.append((container, label))
            else:
                mark, note = ' ahead', '  <- container has it, host does not (!)'
                drift.append((container, label + ' (container ahead of host)'))
            if not args.quiet or mark != '  ok':
                shown = 'FILE ABSENT' if c is None else ('yes' if c else 'no')
                print(f'  {mark}  {label:36} container={shown:12}{note}')

    tb = 'stockscreener-trading-bot-1'
    if not args.quiet:
        bots = running_bots(tb)
        print(f'\nrunning bots ({len(bots)}):')
        for instr, qty in bots:
            r = effective_risk(tb, instr) or {}
            # --quantity wins: main.py:909 writes it straight into
            # execution.position_size. Nothing propagates risk -> execution, so
            # US100's `risk.position_size: 1` reaches the broker only via this
            # flag (CLAUDE.md gotcha 55). Omit it and the broker gets 0.5.
            if qty is not None:
                eff, why = qty, '--quantity'
            elif r.get('exec_ps') is not None:
                eff, why = r['exec_ps'], 'execution.position_size'
            else:
                eff, why = '0.5', 'execution_skill.py:51 default'
            print(f'  {instr:8} quantity={qty if qty is not None else "(none)"}')
            if r:
                print(f'           SL={r["sl"]} TP={r["tp"]} daily_loss={r["daily_loss"]} '
                      f'consec={r["consec"]} flatten={r["flatten"]}')
                print(f'           position_size root={r["root_ps"]} risk={r["risk_ps"]} '
                      f'execution={r["exec_ps"]}')
                print(f'           -> broker gets {eff}  (from {why})')

        print('\nM5 bar freshness in the live volume:')
        for epic, n, latest in bar_freshness(tb):
            print(f'  {epic:8} bars={int(n):,}  latest={latest}')

    print()
    if drift:
        print(f'DRIFT: {len(drift)} marker(s) behind the host tree:')
        for c, label in drift:
            print(f'  {c}: {label}')
        print('\nA rebuild bakes in EVERYTHING in ./trading-bot-skills, committed or not')
        print('(CLAUDE.md gotcha 10) — run `git status` before:')
        print('  docker compose build <service> && docker compose up -d <service>')
        return 1

    print('No drift: every tracked marker matches the host tree.')
    return 0


if __name__ == '__main__':
    sys.exit(main())

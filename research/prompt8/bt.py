"""Run run_skills_backtest.main() against the frozen snapshot DB, with no bar fetching."""
import os, sys
os.environ['DB_PATH'] = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'snap.db')
sys.path.insert(0, '/opt/stockscreener/trading-bot-skills')
os.chdir('/opt/stockscreener/trading-bot-skills')
import run_skills_backtest as r
r._ensure_candles_in_db = lambda *a, **k: None
sys.argv = ['run_skills_backtest.py'] + sys.argv[1:]
r.main()

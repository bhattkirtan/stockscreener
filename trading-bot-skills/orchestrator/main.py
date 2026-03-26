"""
Trading Bot Main Entry Point
Starts the skill-based trading bot with configuration.
"""
import asyncio
import argparse
import sys
import os
from pathlib import Path

# Add parent directory to path
sys.path.append(str(Path(__file__).parent.parent))

from orchestrator.trading_orchestrator import TradingOrchestrator
from skills.risk.risk_skill import RiskSkill
from skills.market_data import MarketDataSkill
from skills.analysis import AnalysisSkill
from skills.execution import ExecutionSkill
from skills.storage import StorageSkill
from skills.monitoring import MonitoringSkill
from skills.alerting import AlertingSkill
from skills.backtesting import BacktestingSkill
from skills.reporting import ReportingSkill
import yaml


def load_config(config_path: str) -> dict:
    """Load configuration from YAML file"""
    with open(config_path, 'r') as f:
        return yaml.safe_load(f)


async def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description='Trading Bot - Skill-Based Architecture')
    parser.add_argument(
        '--config', 
        default='config/trading_config.yaml',
        help='Path to configuration file'
    )
    parser.add_argument(
        '--mode',
        choices=['live', 'backtest', 'demo'],
        default='live',
        help='Bot mode: live (production), backtest (historical), demo (paper trading)'
    )
    parser.add_argument(
        '--data',
        help='Path to historical data file (for backtest mode)'
    )
    
    args = parser.parse_args()
    
    # Load configuration
    print(f"📄 Loading configuration from {args.config}")
    config = load_config(args.config)
    
    # Create orchestrator
    orchestrator = TradingOrchestrator(config)
    
    # Register skills
    print("🔧 Registering skills...")
    
    # 1. Market Data Skill - Manages incoming candles and history
    if config.get('market_data', {}).get('enabled', True):
        market_data_skill = MarketDataSkill(config)
        orchestrator.register_skill('market_data', market_data_skill)
    
    # 2. Analysis Skill - Calculates indicators and generates signals
    if config.get('indicators', {}).get('enabled', True):
        analysis_skill = AnalysisSkill(config)
        orchestrator.register_skill('analysis', analysis_skill)
    
    # 3. Risk Skill - Validates signals and enforces cooldowns
    if config.get('risk', {}).get('enabled', True):
        risk_skill = RiskSkill(config)
        orchestrator.register_skill('risk', risk_skill)
    
    # 4. Execution Skill - Places orders via Capital.com API
    if config.get('execution', {}).get('enabled', True):
        execution_skill = ExecutionSkill(config)
        orchestrator.register_skill('execution', execution_skill)
    
    # 5. Storage Skill - Persists data to Firestore
    if config.get('storage', {}).get('enabled', True):
        storage_skill = StorageSkill(config)
        orchestrator.register_skill('storage', storage_skill)
    
    # 6. Monitoring Skill - Tracks performance metrics
    if config.get('monitoring', {}).get('enabled', True):
        monitoring_skill = MonitoringSkill(config)
        orchestrator.register_skill('monitoring', monitoring_skill)
    
    # 7. Alerting Skill - Sends Telegram notifications
    if config.get('alerting', {}).get('enabled', True):
        alerting_skill = AlertingSkill(config)
        orchestrator.register_skill('alerting', alerting_skill)
    
    # 8. Backtesting Skill - Simulates strategy on historical data
    if args.mode == 'backtest' and config.get('backtesting', {}).get('enabled', True):
        backtesting_skill = BacktestingSkill(config)
        orchestrator.register_skill('backtesting', backtesting_skill)
    
    # 9. Reporting Skill - Generates performance reports
    if config.get('reporting', {}).get('enabled', True):
        reporting_skill = ReportingSkill(config)
        orchestrator.register_skill('reporting', reporting_skill)
    
    print(f"✅ Registered {len(orchestrator.skills)} skills")
    
    # Start orchestrator
    print(f"\n🚀 Starting bot in {args.mode.upper()} mode...")
    await orchestrator.start()
    
    if args.mode == 'backtest':
        if not args.data:
            print("❌ Error: --data required for backtest mode")
            return
        
        print(f"📊 Running backtest on {args.data}")
        # TODO: Implement backtest logic
        print("⚠️ Backtest not yet implemented")
    
    elif args.mode == 'demo':
        print("📝 Running in DEMO mode (paper trading)")
        # TODO: Connect to demo account
        print("⚠️ Demo mode not yet implemented")
    
    else:  # live mode
        print("💰 Running in LIVE mode")
        print("⚠️ Live trading not fully implemented yet")
        
        # Keep running until interrupted
        try:
            while orchestrator.running:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            print("\n⏸️ Shutting down...")
    
    # Stop orchestrator
    await orchestrator.stop()
    print("✅ Bot stopped successfully")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Goodbye!")
    except Exception as e:
        print(f"❌ Fatal error: {e}")
        sys.exit(1)

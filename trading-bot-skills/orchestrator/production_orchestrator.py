"""
Production-Ready Trading Orchestrator
Integrates event-driven architecture, position state management, circuit breakers, and operational monitoring.
"""
import asyncio
from typing import Dict, List, Optional
from datetime import datetime, timedelta
import sys
import os

# Add project directories to path
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from skills.base_skill import Skill
from core.event_bus import EventBus, Event, EventType, create_candle_closed_event, create_bot_error_event
from core.position_state import PositionStateManager, Position, PositionStatus
from core.idempotency import IdempotencyManager, RetryPolicy
from core.circuit_breakers import CircuitBreaker, TradingSessionFilter, SpreadSlippageFilter, NewsEventKillSwitch
from core.operational_monitoring import OperationalMonitor


class IntraDayTimeExit:
    """Force close positions that exceed max holding time (matches backtester)"""
    
    def __init__(self, max_hours: int = 4, enabled: bool = True):
        self.max_hours = max_hours
        self.enabled = enabled
    
    def should_close_time(self, position: Position, current_time: datetime) -> bool:
        """Returns True if position should be closed due to time"""
        if not self.enabled:
            return False
        hours_open = (current_time - position.opened_at).total_seconds() / 3600
        return hours_open >= self.max_hours


class EndOfDayClose:
    """Force close all positions at EOD hour (matches backtester)"""
    
    def __init__(self, close_hour: int = 16, enabled: bool = True):
        """
        Args:
            close_hour: Hour (0-23) to close all positions (default: 16 = 4 PM UTC)
            enabled: Whether EOD close is active
        """
        self.close_hour = close_hour
        self.enabled = enabled
    
    def should_close_eod(self, current_time: datetime) -> bool:
        """Returns True if we've hit EOD close hour"""
        if not self.enabled:
            return False
        return current_time.hour >= self.close_hour


class ProductionOrchestrator:
    """
    Production-grade orchestrator with:
    - Event-driven architecture (decoupled skills)
    - Startup reconciliation with broker
    - Position state management
    - Execution idempotency
    - Circuit breakers
    - Operational monitoring
    
    Responsibilities:
    - Lifecycle management (start, stop, restart)
    - Startup recovery and reconciliation
    - Event bus wiring
    - Health monitoring
    - Error handling and circuit breaking
    
    NOT responsible for:
    - Trading logic (belongs in skills)
    - Risk decisions (belongs in Risk Skill)
    - Signal generation (belongs in Analysis Skill)
    """
    
    def __init__(self, config: Dict, capital_api=None, firestore_client=None, telegram_client=None):
        """
        Initialize production orchestrator.
        
        Args:
            config: Complete bot configuration
            capital_api: Capital.com API client (optional for reconciliation)
            firestore_client: Firestore client (optional for persistence)
            telegram_client: Telegram client (optional for alerts)
        """
        self.config = config
        self.running = False
        self.start_time: Optional[datetime] = None
        
        # API clients
        self.capital_api = capital_api
        self.firestore = firestore_client
        self.telegram = telegram_client
        
        # ========== Core Components ==========
        
        # Event bus for skill communication
        self.event_bus = EventBus(history_size=config.get('event_history_size', 1000))
        
        # Position state manager (canonical source of truth)
        self.position_manager = PositionStateManager(
            storage_skill=None,  # Will be set after skill registration
            capital_api=capital_api
        )
        
        # Execution idempotency
        self.idempotency = IdempotencyManager(
            ttl_hours=config.get('idempotency_ttl_hours', 24)
        )
        
        # Retry policy
        self.retry_policy = RetryPolicy(
            max_attempts=config.get('max_retry_attempts', 3),
            base_delay_seconds=config.get('retry_base_delay', 1.0),
            timeout_seconds=config.get('operation_timeout', 30.0)
        )
        
        # Circuit breakers
        self.circuit_breaker = CircuitBreaker(config.get('circuit_breaker', {}))
        
        # Trading session filter
        self.session_filter = TradingSessionFilter(config.get('trading_sessions', {}))
        
        # Spread/slippage filter
        self.spread_filter = SpreadSlippageFilter(config.get('spread_filter', {}))
        
        # News kill switch
        self.news_killswitch = NewsEventKillSwitch(config.get('news_killswitch', {}))
        
        # Operational monitoring
        self.op_monitor = OperationalMonitor(config.get('monitoring', {}))
        
        # Time-based exit filters (NEW - Critical for Gold trading)
        time_exit_config = config.get('time_based_exits', {})
        self.intraday_time_exit = IntraDayTimeExit(
            max_hours=time_exit_config.get('max_hours', 4),
            enabled=time_exit_config.get('intraday_enabled', True)
        )
        self.eod_close = EndOfDayClose(
            close_hour=time_exit_config.get('eod_hour', 16),
            enabled=time_exit_config.get('eod_enabled', True)
        )
        
        # Skills registry
        self.skills: Dict[str, Skill] = {}
        
        # Metrics
        self.stats = {
            'events_published': 0,
            'signals_generated': 0,
            'trades_executed': 0,
            'reconciliations': 0,
            'errors': 0
        }
    
    # ========== Lifecycle Management ==========
    
    async def start(self) -> bool:
        """
        Start orchestrator with full recovery.
        
        Steps:
        1. Load persisted state
        2. Reconcile with broker
        3. Auto-heal inconsistencies
        4. Wire event subscriptions
        5. Start skills
        6. Begin event loop
        
        Returns:
            True if started successfully
        """
        self.start_time = datetime.now()
        print(f"\n{'='*60}")
        print(f"🚀 PRODUCTION ORCHESTRATOR STARTING")
        print(f"{'='*60}\n")
        
        try:
            # Step 1: Load persisted state
            print("📂 Step 1/6: Loading persisted state...")
            await self.position_manager.load_snapshot()
            
            # Step 2: Reconcile with broker
            print("\n🔄 Step 2/6: Reconciling with broker...")
            if self.capital_api:
                result = await self.position_manager.reconcile_with_broker()
                self.stats['reconciliations'] += 1
                
                # Step 3: Auto-heal if needed
                if result.has_issues():
                    print("\n🔧 Step 3/6: Auto-healing inconsistencies...")
                    await self.position_manager.auto_heal_from_reconciliation(result)
                    
                    # Send alert about reconciliation issues
                    if self.telegram:
                        await self._send_reconciliation_alert(result)
                else:
                    print("\n✅ Step 3/6: No inconsistencies found")
            else:
                print("⚠️ Step 2-3: Skipped (no Capital.com API client)")
            
            # Step 4: Wire event subscriptions
            print("\n🔗 Step 4/6: Wiring event subscriptions...")
            self._wire_event_subscriptions()
            
            # Step 5: Validate configuration
            print("\n✔️ Step 5/6: Validating configuration...")
            self._validate_configuration()
            
            # Step 6: Start operational monitoring
            print("\n📊 Step 6/6: Starting operational monitoring...")
            asyncio.create_task(self._monitoring_loop())
            
            self.running = True
            
            # Publish BOT_STARTED event
            await self.event_bus.publish(Event(
                event_type=EventType.BOT_STARTED,
                source='orchestrator',
                payload={'start_time': self.start_time.isoformat()}
            ))
            
            print(f"\n{'='*60}")
            print(f"✅ ORCHESTRATOR READY")
            print(f"{'='*60}\n")
            print(f"📋 Registered skills: {list(self.skills.keys())}")
            print(f"📊 Open positions: {self.position_manager.get_position_count()}")
            print(f"🔄 Circuit breaker: {self.circuit_breaker.status.value}")
            print(f"💊 Health status: {self.op_monitor.get_overall_status()}\n")
            
            return True
        
        except Exception as e:
            print(f"\n❌ ORCHESTRATOR START FAILED: {e}")
            self.stats['errors'] += 1
            
            # Publish error event
            await self.event_bus.publish(create_bot_error_event(
                error_message=str(e),
                location='orchestrator.start'
            ))
            
            return False
    
    async def stop(self) -> None:
        """Stop orchestrator gracefully"""
        print(f"\n{'='*60}")
        print(f"🛑 ORCHESTRATOR STOPPING")
        print(f"{'='*60}\n")
        
        self.running = False
        
        # Save final state snapshot
        print("💾 Saving final state snapshot...")
        await self.position_manager.save_snapshot()
        
        # Publish BOT_STOPPED event
        await self.event_bus.publish(Event(
            event_type=EventType.BOT_STOPPED,
            source='orchestrator',
            payload={'stop_time': datetime.now().isoformat()}
        ))
        
        # Print final stats
        runtime = (datetime.now() - self.start_time).total_seconds() / 60
        print(f"\n📊 SESSION SUMMARY:")
        print(f"  Runtime: {runtime:.1f} minutes")
        print(f"  Events published: {self.stats['events_published']}")
        print(f"  Signals generated: {self.stats['signals_generated']}")
        print(f"  Trades executed: {self.stats['trades_executed']}")
        print(f"  Reconciliations: {self.stats['reconciliations']}")
        print(f"  Errors: {self.stats['errors']}")
        print(f"\n💊 Final health: {self.op_monitor.get_overall_status()}")
        print(f"🔄 Circuit breaker: {self.circuit_breaker.status.value}")
        print(f"📊 Position state: {self.position_manager.get_position_count()} open positions\n")
    
    # ========== Skill Registration ==========
    
    def register_skill(self, name: str, skill: Skill) -> None:
        """
        Register a skill with the orchestrator.
        
        Args:
            name: Skill name
            skill: Skill instance
        """
        if not skill.validate_config():
            raise ValueError(f"Invalid configuration for skill: {name}")
        
        self.skills[name] = skill
        print(f"✅ Registered skill: {name}")
        
        # Wire storage skill to position manager
        if name == 'storage':
            self.position_manager.storage = skill
    
    def get_skill(self, name: str) -> Optional[Skill]:
        """Get skill by name"""
        return self.skills.get(name)
    
    # ========== Event Subscriptions ==========
    
    def _wire_event_subscriptions(self) -> None:
        """
        Wire event-driven communication between skills.
        
        WIRE ONLY - No trading logic here.
        Skills handle events directly, orchestrator just connects them.
        """
        # Market Data -> Analysis (skill handles it)
        if 'analysis' in self.skills:
            self.event_bus.subscribe(
                EventType.CANDLE_CLOSED,
                self.skills['analysis'].on_candle_closed
            )
        
        # Analysis -> Risk (skill handles it)
        if 'risk' in self.skills:
            self.event_bus.subscribe(
                EventType.SIGNAL_GENERATED,
                self.skills['risk'].on_signal_generated
            )
        
        # Risk -> Execution (skill handles it)
        if 'execution' in self.skills:
            self.event_bus.subscribe(
                EventType.RISK_APPROVED,
                self.skills['execution'].on_risk_approved
            )
        
        # Position state management (orchestrator owns position state)
        self.event_bus.subscribe(
            EventType.ORDER_FILLED,
            self._on_order_filled_update_state
        )
        
        self.event_bus.subscribe(
            EventType.POSITION_CLOSED,
            self._on_position_closed_update_state
        )
        
        # Errors -> Alerting (skill handles it)
        if 'alerting' in self.skills:
            self.event_bus.subscribe(
                EventType.BOT_ERROR,
                self.skills['alerting'].on_error
            )
            self.event_bus.subscribe(
                EventType.BOT_ERROR,
                self._on_error_for_alerting
            )
        
        # Circuit breaker events -> Alerting
        self.event_bus.subscribe(
            EventType.CIRCUIT_BREAKER_OPENED,
            self._on_circuit_breaker_alert
        )
        
        # Reverse signal monitoring (close positions on opposite signal)
        self.event_bus.subscribe(
            EventType.SIGNAL_GENERATED,
            self._check_reverse_signals
        )
        
        print(f"✅ Wired event subscriptions: {len(self.event_bus.subscribers)} event types")
    
    # ========== Event Handlers (STATE MANAGEMENT ONLY) ==========
    
    async def _on_order_filled_update_state(self, event: Event) -> None:
        """Handle order filled -> update position state and storage"""
        # Create position in state manager (with transaction costs)
        position = Position(
            deal_id=event.payload['deal_id'],
            instrument=event.instrument,
            direction=event.payload['direction'],
            entry_price=event.payload['entry_price'],
            size=event.payload['size'],
            stop_loss=event.payload.get('stop_loss', 0),
            take_profit=event.payload.get('take_profit', 0),
            status=PositionStatus.OPEN,
            opened_at=event.timestamp,
            signal_timestamp=event.timestamp,
            spread_cost=event.payload.get('spread_cost', 0.0),
            slippage_cost=event.payload.get('slippage_cost', 0.0)
        )
        
        self.position_manager.add_position(position)
        self.stats['trades_executed'] += 1
        
        # Save to storage
        await self.position_manager.save_snapshot()
    
    async def _on_position_closed_update_state(self, event: Event) -> None:
        """Handle position closed -> update state and circuit breaker (STATE ONLY)"""
        # Close in position manager
        position = self.position_manager.close_position(
            deal_id=event.payload['deal_id'],
            close_price=event.payload['close_price'],
            close_reason=event.payload['close_reason']
        )
        
        if position:
            # Record trade for circuit breaker
            self.circuit_breaker.record_trade(position.realized_pnl)
            
            # Save snapshot   
            await self.position_manager.save_snapshot()
    
    async def _check_reverse_signals(self, event: Event) -> None:
        """
        Check if any open positions should be closed due to reverse signal.
        Matches backtester behavior: closes opposite positions when new signal fires.
        """
        try:
            from core.signal_engine import check_reverse_signal, create_market_state
            
            # Get signal from event
            new_signal = event.payload.get('signal')
            indicators = event.payload.get('indicators', {})
            
            if not new_signal or new_signal not in ['BUY', 'SELL']:
                return
            
            # Create market state from indicators
            market_state = create_market_state(
                close=indicators.get('current_price', 0),
                supertrend_direction=indicators.get('supertrend_direction', 0),
                ema=indicators.get('ema', 0),
                sma_fast=indicators.get('sma_fast', 0),
                sma_slow=indicators.get('sma_slow', 0),
                timestamp=str(event.timestamp)
            )
            
            # Get all open positions
            open_positions = self.position_manager.get_open_positions()
            
            if not open_positions:
                return
            
            # Check each open position for reverse signal
            for position in open_positions:
                # Check if this signal is opposite to the position
                if check_reverse_signal(position.direction, market_state):
                    print(f"🔄 Reverse signal detected: {new_signal} signal while holding {position.direction}")
                    print(f"   Closing position {position.deal_id} at current price")
                    
                    # Close position via execution skill
                    if 'execution' in self.skills:
                        execution_skill = self.skills['execution']
                        success = await execution_skill.close_position(position.deal_id)
                        
                        if success:
                            # Publish POSITION_CLOSED event
                            await self.event_bus.publish(Event(
                                event_type=EventType.POSITION_CLOSED,
                                source='orchestrator',
                                instrument=position.instrument,
                                timestamp=datetime.now(),
                                payload={
                                    'deal_id': position.deal_id,
                                    'close_price': indicators.get('current_price', 0),
                                    'close_reason': 'Reverse Signal'
                                }
                            ))
                            print(f"✅ Position {position.deal_id} closed on reverse signal")
                        else:
                            print(f"❌ Failed to close position {position.deal_id}")
                    
        except Exception as e:
            print(f"⚠️ Error checking reverse signals: {e}")
            # Don't propagate error - this is advisory logic
    
    async def _check_time_based_exits(self) -> None:
        """
        Check if any open positions should be closed due to time limits.
        Called periodically by monitoring loop.
        
        Two checks:
        1. IntraDayTimeExit: Close positions open > max_hours (e.g., 4 hours)
        2. EndOfDayClose: Close all positions at EOD hour (e.g., 4 PM UTC)
        
        Matches backtester behavior in cloud-function/src/core/backtester.py
        """
        try:
            current_time = datetime.now()
            open_positions = self.position_manager.get_open_positions()
            
            if not open_positions:
                return
            
            # Check 1: End-of-Day close (takes priority)
            if self.eod_close.should_close_eod(current_time):
                print(f"⏰ EOD close triggered: {self.eod_close.close_hour}:00 UTC")
                for position in open_positions:
                    await self._close_position_time_exit(
                        position,
                        'EOD_CLOSE',
                        f"End of day close ({self.eod_close.close_hour}:00 UTC)"
                    )
                return  # All positions closed, done
            
            # Check 2: Intraday time exit (individual positions)
            for position in open_positions:
                if self.intraday_time_exit.should_close_time(position, current_time):
                    hours_open = (current_time - position.opened_at).total_seconds() / 3600
                    print(f"⏰ Intraday time exit: {position.deal_id} open {hours_open:.1f} hours (max: {self.intraday_time_exit.max_hours})")
                    await self._close_position_time_exit(
                        position,
                        'TIME_EXIT',
                        f"Exceeded max holding time ({self.intraday_time_exit.max_hours} hours)"
                    )
        
        except Exception as e:
            print(f"⚠️ Error checking time-based exits: {e}")
            # Don't propagate error - this is advisory logic
    
    async def _close_position_time_exit(self, position: Position, exit_type: str, reason: str) -> None:
        """
        Close position due to time-based exit.
        
        Args:
            position: Position to close
            exit_type: 'EOD_CLOSE' or 'TIME_EXIT'
            reason: Human-readable reason
        """
        try:
            # Close position via execution skill
            if 'execution' in self.skills:
                execution_skill = self.skills['execution']
                success = await execution_skill.close_position(position.deal_id)
                
                if success:
                    # Publish POSITION_CLOSED event
                    await self.event_bus.publish(Event(
                        event_type=EventType.POSITION_CLOSED,
                        source='orchestrator',
                        instrument=position.instrument,
                        timestamp=datetime.now(),
                        payload={
                            'deal_id': position.deal_id,
                            'close_price': 0.0,  # Would need live price
                            'close_reason': exit_type
                        }
                    ))
                    print(f"✅ {exit_type}: {position.deal_id} closed ({reason})")
                else:
                    print(f"❌ Failed to close {position.deal_id} ({exit_type})")
            else:
                print(f"⚠️ Execution skill not available to close {position.deal_id}")
        
        except Exception as e:
            print(f"❌ Error closing position {position.deal_id}: {e}")
    
    async def _on_error_for_alerting(self, event: Event) -> None:
        """Handle errors -> send alerts"""
        alerting_skill = self.skills.get('alerting')
        if alerting_skill and self.telegram:
            # Send error alert
            pass
    
    async def _on_circuit_breaker_alert(self, event: Event) -> None:
        """Handle circuit breaker opened -> send critical alert"""
        if self.telegram:
            # Send critical alert
            pass
    
    # ========== Monitoring Loop ==========
    
    async def _monitoring_loop(self) -> None:
        """Periodic monitoring and health checks"""
        while self.running:
            try:
                # Run health checks
                health_checks = await self.op_monitor.run_health_checks()
                
                # Check for unhealthy components
                unhealthy = [c for c in health_checks if c.status == 'UNHEALTHY']
                if unhealthy:
                    print(f"⚠️ Unhealthy components: {[c.component for c in unhealthy]}")
                    # Send alert
                
                # Cleanup expired idempotency keys
                await self.idempotency.cleanup_expired()
                
                # ========== NEW: Time-Based Exit Checks ==========
                await self._check_time_based_exits()
                # ================================================
                
                # Save periodic snapshot
                await self.position_manager.save_snapshot()
                
                # Sleep for interval
                await asyncio.sleep(self.config.get('monitoring_interval_seconds', 60))
            
            except Exception as e:
                print(f"❌ Monitoring loop error: {e}")
                await asyncio.sleep(10)
    
    # ========== Helper Methods ==========
    
    def _validate_configuration(self) -> None:
        """Validate configuration at startup"""
        required = ['instrument', 'timeframe', 'initial_capital']
        for key in required:
            if key not in self.config:
                raise ValueError(f"Missing required config: {key}")
        
        print(f"✅ Configuration validated")
    
    async def _send_reconciliation_alert(self, result) -> None:
        """Send alert about reconciliation issues"""
        message = f"🔧 Reconciliation Issues Found:\n"
        message += f"  Missing local: {len(result.missing_local)}\n"
        message += f"  Missing broker: {len(result.missing_broker)}\n"
        message += f"  Mismatched: {len(result.mismatched)}"
        
        # TODO: Send via telegram
        print(message)

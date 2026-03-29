"""
Execution Skill
Executes trades via Capital.com API.

EVENT-DRIVEN:
- Subscribes to: RISK_APPROVED
- Publishes: ORDER_FILLED or ORDER_REJECTED
"""
from typing import Dict, Optional, TYPE_CHECKING
from datetime import datetime
import sys
import os
import logging

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from skills.base_skill import Skill, SkillExecutionError
from clients.capital_api import CapitalAPIClient

if TYPE_CHECKING:
    from core.event_bus import EventBus, Event
    from core.idempotency import IdempotencyManager, OrderRequest, RetryPolicy

logger = logging.getLogger(__name__)


class ExecutionSkill(Skill):
    """
    Execution skill that places and manages orders via Capital.com API.
    
    EVENT-DRIVEN HANDLERS:
    - on_risk_approved(event): Place order with idempotency and retry
    
    Responsibilities:
    - Place market orders (BUY/SELL) with idempotency
    - Retry failed orders with exponential backoff
    - Publish ORDER_FILLED or ORDER_REJECTED events
    - Track open positions
    """
    
    def __init__(self, config: Dict, event_bus: Optional['EventBus'] = None,
                 idempotency_manager=None, retry_policy=None):
        super().__init__(config, event_bus)
        
        # I dempotency and retry (from Phase 15)
        self.idempotency = idempotency_manager
        self.retry_policy = retry_policy
        
        self.broker = config.get('broker', 'capital_com')
        self.sl_pips = config.get('sl_pips', 20)
        self.tp_pips = config.get('tp_pips', 40)
        self.position_size = config.get('position_size', 0.5)
        self.epic = config.get('epic', 'CS.D.CFDGOLD.CFD.IP')  # Default: GOLD
        
        # Initialize Capital.com API client
        capital_config = config.get('capital_com', {})
        self.mock_mode = config.get('mock_mode', False)
        
        # Transaction cost tracking
        self._last_transaction_costs = None
        
        if not self.mock_mode and capital_config:
            try:
                self.rest_client = CapitalAPIClient(
                    username=capital_config.get('username'),
                    password=capital_config.get('password'),
                    api_key=capital_config.get('api_key'),
                    environment=capital_config.get('environment', 'demo')
                )
                logger.info("✅ Capital.com API client initialized")
            except Exception as e:
                logger.error(f"❌ Failed to initialize Capital.com client: {e}")
                logger.warning("⚠️ Falling back to mock mode")
    
    async def on_risk_approved(self, event: 'Event') -> None:
        """
        Handle RISK_APPROVED event - place order with idempotency.
        
        Args:
            event: Event with risk-approved signal and parameters
        """
        # Extract order parameters from event
        signal = event.payload.get('signal')
        position_size = event.payload.get('position_size')
        entry_price = event.payload.get('entry_price')
        stop_loss = event.payload.get('stop_loss')
        take_profit = event.payload.get('take_profit')
        
        # Calculate transaction costs (matches backtester)
        from core.cost_calculator import calculate_position_costs, GOLD_COST_CONFIG
        transaction_costs = calculate_position_costs(entry_price, position_size, GOLD_COST_CONFIG)
        logger.info(f"💰 Transaction costs: Spread=${transaction_costs.spread_cost:.2f}, "
                   f"Slippage=${transaction_costs.slippage_cost:.2f}, "
                   f"Total=${transaction_costs.total_cost:.2f}")
        
        # Store costs for later use in ORDER_FILLED event
        self._last_transaction_costs = transaction_costs
        
        # Validate signal
        if not signal or signal not in ['BUY', 'SELL']:
            logger.warning(f"⚠️ Invalid signal: {signal}")
            return
        
        # Create order request with idempotency
        if self.idempotency:
            from core.idempotency import OrderRequest
            order = OrderRequest.create(
                instrument=event.instrument,
                direction=signal,
                size=position_size,
                stop_loss=stop_loss,
                take_profit=take_profit,
                signal_timestamp=event.timestamp
            )
            
            # Check for duplicate
            if self.idempotency.is_duplicate(order.idempotency_key):
                cached = self.idempotency.get_cached_result(order.idempotency_key)
                print(f"⚠️ Duplicate order detected: {order.idempotency_key}")
                # Publish cached result
                await self._publish_cached_fill(cached, event.correlation_id)
                return
            
            # Register submission
            self.idempotency.register_submission(order)
        
        # Execute order with retry
        try:
            if self.retry_policy:
                result = await self.retry_policy.execute_with_retry(
                    self._place_order_api,
                    signal, position_size, entry_price, stop_loss, take_profit
                )
            else:
                result = await self._place_order_api(signal, position_size, entry_price, stop_loss, take_profit)
            
            # Register fill
            if self.idempotency and result:
                self.idempotency.register_fill(order.idempotency_key, result['deal_id'])
            
            # Publish ORDER_FILLED event
            await self._publish_order_filled(event, result, signal, position_size, stop_loss, take_profit, transaction_costs)
            
        except Exception as e:
            # Register rejection
            if self.idempotency:
                self.idempotency.register_rejection(order.idempotency_key, str(e))
            
            # Publish ORDER_REJECTED event
            await self._publish_order_rejected(event, str(e))
    
    async def _publish_order_filled(self, event: 'Event', result: Dict, 
                                    signal: str, size: float, stop_loss: float, take_profit: float,
                                    transaction_costs=None):
        """Publish ORDER_FILLED event with transaction costs"""
        if not self.event_bus:
            return
        
        from core.event_bus import create_order_filled_event
        
        # Build event payload with costs
        event_payload = {
            'deal_id': result.get('deal_id'),
            'instrument': event.instrument,
            'direction': signal,
            'entry_price': result.get('entry_price', 0),
            'size': size,
            'stop_loss': stop_loss,
            'take_profit': take_profit,
            'correlation_id': event.correlation_id
        }
        
        # Add transaction costs if available
        if transaction_costs:
            event_payload['spread_cost'] = transaction_costs.spread_cost
            event_payload['slippage_cost'] = transaction_costs.slippage_cost
        
        await self.event_bus.publish(
            create_order_filled_event(**event_payload)
        )
        print(f"✅ Order filled: {result.get('deal_id')}")
    
    async def _publish_order_rejected(self, event: 'Event', reason: str):
        """Publish ORDER_REJECTED event"""
        if not self.event_bus:
            return
        
        from core.event_bus import create_order_rejected_event
        await self.event_bus.publish(
            create_order_rejected_event(
                instrument=event.instrument,
                reason=reason,
                correlation_id=event.correlation_id
            )
        )
        print(f"❌ Order rejected: {reason}")
    
    async def _publish_cached_fill(self, cached_result: Dict, correlation_id: str):
        """Publish cached order result"""
        # Use cached deal_id without re-executing
        print(f"↩️  Using cached order: {cached_result.get('deal_id')}")
    
    async def _place_order_api(
        self,
        direction: str,
        size: float,
        entry_price: float,
        stop_loss: float,
        take_profit: float
    ) -> Optional[Dict]:
        """
        Place market order via Capital.com API (wrapped by retry policy)
        
        Returns:
            dict with deal_id and entry_price if successful, None otherwise
        """
        if self.mock_mode or not self.rest_client:
            # Mock mode - return fake order result
            deal_id = f"DEAL{int(datetime.now().timestamp())}"
            logger.info(f"📤 [MOCK] Order placed: {direction} {size} @ {entry_price:.2f}")
            return {
                'deal_id': deal_id,
                'entry_price': entry_price,
                'direction': direction,
                'size': size
            }
        
        try:
            # Place real order via Capital.com API
            result = self.rest_client.place_order(
                epic=self.epic,
                direction=direction,
                size=size,
                stop_level=stop_loss,
                profit_level=take_profit,
                guaranteed_stop=False
            )
            
            # Extract deal_id from result
            deal_reference = result.get('dealReference')
            
            # Note: Capital.com returns dealReference immediately
            # The actual dealId may need to be fetched later
            # For now, use dealReference as the identifier
            logger.info(f"✅ Order placed: {direction} {size} {self.epic} (ref: {deal_reference})")
            
            return {
                'deal_id': deal_reference,
                'entry_price': entry_price,  # Would need to fetch actual fill price
                'direction': direction,
                'size': size
            }
        
        except Exception as e:
            logger.error(f"❌ Failed to place order: {e}")
            return None
    
    async def close_position(self, deal_id: str) -> bool:
        """
        Close position via Capital.com API
        
        Args:
            deal_id: Position deal ID
            
        Returns:
            True if successful, False otherwise
        """
        logger.info(f"🔚 Closing position: {deal_id}")
        
        if self.mock_mode or not self.rest_client:
            logger.info(f"🔚 [MOCK] Position closed: {deal_id}")
            return True
        
        try:
            result = self.rest_client.close_position(deal_id=deal_id)
            logger.info(f"✅ Position closed: {deal_id}")
            return True
        
        except Exception as e:
            logger.error(f"❌ Failed to close position {deal_id}: {e}")
            return False
    
    def validate_config(self) -> bool:
        """Validate execution configuration"""
        if self.sl_pips <= 0 or self.tp_pips <= 0:
            raise SkillExecutionError("SL/TP pips must be > 0")
        if self.position_size <= 0:
            raise SkillExecutionError("Position size must be > 0")
        return True


# Example usage
if __name__ == "__main__":
    import asyncio
    
    config = {
        'broker': 'capital_com',
        'sl_pips': 20,
        'tp_pips': 40,
        'position_size': 0.5
    }
    
    skill = ExecutionSkill(config)
    
    async def test():
        # Mock validated BUY signal
        context = Context(
            signal='BUY',
            is_allowed=True,
            current_candle={
                'timestamp': '2024-01-15T10:00:00',
                'open': 2650.0,
                'high': 2652.0,
                'low': 2649.0,
                'close': 2651.0,
                'volume': 1000
            }
        )
        
        context = await skill.execute(context)
        print(f"\nDeal ID: {context.deal_id}")
        print(f"Position: {context.current_position}")
    
    asyncio.run(test())

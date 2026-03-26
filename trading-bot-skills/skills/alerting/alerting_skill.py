"""
Alerting Skill
Sends notifications on important events.
"""
from typing import Dict, Optional
from datetime import datetime
import sys
import os
import logging

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from skills.base_skill import Skill, Context, SkillExecutionError
from clients.telegram_api import TelegramAPIClient

logger = logging.getLogger(__name__)


class AlertingSkill(Skill):
    """
    Alerting skill that sends notifications.
    
    Responsibilities:
    - Send trade notifications (opened, closed)
    - Send error alerts
    - Send drawdown warnings
    - Send daily performance summary
    """
    
    def __init__(self, config: Dict):
        super().__init__(config)
        
        # Telegram settings
        telegram_config = config.get('telegram', {})
        self.telegram_enabled = telegram_config.get('enabled', False)
        self.telegram_token = telegram_config.get('token')
        self.telegram_chat_id = telegram_config.get('chat_id')
        
        # Alert settings
        self.alert_on_trade_opened = telegram_config.get('trade_opened', True)
        self.alert_on_trade_closed = telegram_config.get('trade_closed', True)
        self.alert_on_sl_hit = telegram_config.get('sl_hit', True)
        self.alert_on_tp_hit = telegram_config.get('tp_hit', True)
        self.alert_on_error = telegram_config.get('error', True)
        
        # Initialize Telegram client
        self.mock_mode = config.get('mock_mode', False)
        
        if not self.mock_mode and self.telegram_enabled:
            try:
                self.telegram_client = TelegramAPIClient(
                    bot_token=self.telegram_token,
                    chat_id=self.telegram_chat_id,
                    mock_mode=False
                )
                logger.info("✅ Telegram client initialized")
            except Exception as e:
                logger.error(f"❌ Failed to initialize Telegram client: {e}")
                logger.warning("⚠️ Falling back to mock mode")
                self.mock_mode = True
                self.telegram_client = TelegramAPIClient(mock_mode=True)
        else:
            self.telegram_client = TelegramAPIClient(mock_mode=True)
            logger.warning("⚠️ Alerting Skill running in MOCK MODE")
        
        print(f"📢 Alerting Skill initialized: telegram={self.telegram_enabled}")
    
    async def execute(self, context: Context) -> Context:
        """
        Send alerts based on context events
        
        Args:
            context: Context with event data
            
        Returns:
            Updated context
        """
        # Alert on new position
        if context.deal_id and context.current_position and self.alert_on_trade_opened:
            await self._send_trade_opened_alert(context)
        
        # Alert on errors
        if context.errors and self.alert_on_error:
            await self._send_error_alert(context)
        
        return context
    
    async def _send_trade_opened_alert(self, context: Context):
        """
        Send alert when trade is opened
        
        Args:
            context: Context with position data
        """
        if not self.alert_on_trade_opened:
            return
        
        position = context.current_position
        direction = position.get('direction', 'UNKNOWN')
        entry_price = position.get('entry_price', 0)
        stop_loss = position.get('stop_loss', 0)
        take_profit = position.get('take_profit', 0)
        size = position.get('size', 0)
        deal_id = position.get('deal_id', 'UNKNOWN')
        timestamp = position.get('entry_time', datetime.now())
        
        # Send via Telegram client
        success = self.telegram_client.send_trade_opened(
            direction=direction,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            size=size,
            deal_id=deal_id,
            timestamp=timestamp
        )
        
        if success:
            logger.info(f"✅ Trade opened alert sent")
        else:
            logger.error(f"❌ Failed to send trade opened alert")
    
    async def send_trade_closed_alert(
        self,
        direction: str,
        entry_price: float,
        close_price: float,
        close_reason: str,
        pnl: float,
        pnl_percent: float = 0.0,
        duration: str = "0m",
        deal_id: str = "UNKNOWN"
    ):
        """
        Send alert when trade is closed
        
        Args:
            direction: BUY or SELL
            entry_price: Entry price
            close_price: Close price
            close_reason: SL_HIT, TP_HIT, or SIGNAL
            pnl: Realized P&L
            pnl_percent: P&L percentage
            duration: Trade duration string
            deal_id: Deal ID
        """
        if not self.alert_on_trade_closed:
            return
        
        # Send via Telegram client
        success = self.telegram_client.send_trade_closed(
            direction=direction,
            entry_price=entry_price,
            close_price=close_price,
            close_reason=close_reason,
            pnl=pnl,
            pnl_percent=pnl_percent,
            duration=duration,
            deal_id=deal_id
        )
        
        if success:
            logger.info(f"✅ Trade closed alert sent")
        else:
            logger.error(f"❌ Failed to send trade closed alert")
    
    async def _send_error_alert(self, context: Context):
        """
        Send alert for errors
        
        Args:
            context: Context with errors
        """
        if not self.alert_on_error:
            return
        
        errors = context.errors[-3:]  # Last 3 errors
        
        for error in errors:
            error_type = error.get('type', 'UNKNOWN_ERROR')
            error_message = error.get('error', 'Unknown error occurred')
            
            success = self.telegram_client.send_error_alert(
                error_type=error_type,
                error_message=error_message,
                context=error.get('context')
            )
            
            if not success:
                logger.error(f"❌ Failed to send error alert")
    
    async def _send_telegram(self, message: str):
        """
        Send raw message to Telegram (for backward compatibility)
        
        Args:
            message: Message text
        """
        success = self.telegram_client.send_message(message)
        
        if not success:
            logger.error("❌ Failed to send Telegram message")
    
    def validate_config(self) -> bool:
        """Validate alerting configuration"""
        if self.telegram_enabled and (not self.telegram_token or not self.telegram_chat_id):
            raise SkillExecutionError("Telegram token and chat_id required when telegram enabled")
        return True


# Example usage
if __name__ == "__main__":
    import asyncio
    
    config = {
        'telegram': {
            'enabled': True,
            'token': 'YOUR_BOT_TOKEN',
            'chat_id': 'YOUR_CHAT_ID',
            'trade_opened': True,
            'trade_closed': True,
            'sl_hit': True,
            'tp_hit': True,
            'error': True
        }
    }
    
    skill = AlertingSkill(config)
    
    async def test():
        # Mock trade opened
        context = Context(
            deal_id='DEAL123',
            current_position={
                'deal_id': 'DEAL123',
                'direction': 'BUY',
                'entry_price': 2650.0,
                'stop_loss': 2630.0,
                'take_profit': 2690.0
            }
        )
        
        await skill.execute(context)
        
        # Mock trade closed
        await skill.send_trade_closed_alert(
            direction='BUY',
            entry_price=2650.0,
            close_price=2690.0,
            close_reason='TP_HIT',
            pnl=20.0
        )
    
    asyncio.run(test())

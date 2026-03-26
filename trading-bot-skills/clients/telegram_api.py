"""
Telegram Bot API Client Wrapper

Handles sending notifications via Telegram Bot API.
"""
import requests
import logging
from typing import Dict, Optional, List
from datetime import datetime

logger = logging.getLogger(__name__)


class TelegramAPIClient:
    """
    Telegram Bot API client for sending notifications
    
    Features:
    - Send text messages with Markdown formatting
    - Send trade alerts with emojis
    - Error handling and rate limiting
    - Mock mode for testing
    """
    
    def __init__(
        self,
        bot_token: Optional[str] = None,
        chat_id: Optional[str] = None,
        mock_mode: bool = False
    ):
        """
        Initialize Telegram Bot API client
        
        Args:
            bot_token: Telegram bot token from @BotFather (or set TELEGRAM_BOT_TOKEN env var)
            chat_id: Telegram chat ID to send messages to (or set TELEGRAM_CHAT_ID env var)
            mock_mode: Use mock mode for testing (default: False)
        """
        import os
        
        # Use env vars as fallback
        self.bot_token = bot_token or os.getenv('TELEGRAM_BOT_TOKEN')
        self.chat_id = chat_id or os.getenv('TELEGRAM_CHAT_ID')
        self.mock_mode = mock_mode or not self.bot_token or not self.chat_id
        
        if self.mock_mode:
            logger.warning("⚠️ TelegramAPIClient running in MOCK MODE - messages will be logged only")
        else:
            self.base_url = f"https://api.telegram.org/bot{self.bot_token}"
            logger.info("✅ Telegram client initialized")
    
    def send_message(
        self,
        text: str,
        parse_mode: str = 'Markdown',
        disable_notification: bool = False
    ) -> bool:
        """
        Send a text message
        
        Args:
            text: Message text (supports Markdown/HTML)
            parse_mode: 'Markdown', 'MarkdownV2', or 'HTML' (default: Markdown)
            disable_notification: Send silently (default: False)
            
        Returns:
            bool indicating success
        """
        if self.mock_mode:
            logger.info(f"📢 [MOCK] Telegram message:\n{text}")
            return True
        
        try:
            url = f"{self.base_url}/sendMessage"
            payload = {
                'chat_id': self.chat_id,
                'text': text,
                'parse_mode': parse_mode,
                'disable_notification': disable_notification
            }
            
            response = requests.post(url, json=payload, timeout=10)
            
            if response.status_code == 429:
                logger.error("❌ Telegram rate limit hit")
                return False
            
            response.raise_for_status()
            
            logger.info("✅ Telegram message sent")
            return True
        
        except Exception as e:
            logger.error(f"❌ Failed to send Telegram message: {e}")
            return False
    
    def send_trade_opened(
        self,
        direction: str,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
        size: float,
        deal_id: str,
        timestamp: Optional[datetime] = None
    ) -> bool:
        """
        Send trade opened notification
        
        Args:
            direction: 'BUY' or 'SELL'
            entry_price: Entry price
            stop_loss: Stop loss price
            take_profit: Take profit price
            size: Position size
            deal_id: Deal ID
            timestamp: Trade timestamp (optional)
            
        Returns:
            bool indicating success
        """
        emoji = '🟢' if direction == 'BUY' else '🔴'
        time_str = (timestamp or datetime.now()).strftime('%Y-%m-%d %H:%M:%S')
        
        # Calculate SL/TP pips
        if direction == 'BUY':
            sl_pips = entry_price - stop_loss
            tp_pips = take_profit - entry_price
        else:
            sl_pips = stop_loss - entry_price
            tp_pips = entry_price - take_profit
        
        message = f"""
{emoji} *Trade Opened*

*Direction:* {direction}
*Size:* {size}
*Entry:* ${entry_price:.2f}
*SL:* ${stop_loss:.2f} ({sl_pips:.1f} pips)
*TP:* ${take_profit:.2f} ({tp_pips:.1f} pips)
*Deal ID:* `{deal_id}`
*Time:* {time_str}
"""
        
        return self.send_message(message)
    
    def send_trade_closed(
        self,
        direction: str,
        entry_price: float,
        close_price: float,
        close_reason: str,
        pnl: float,
        pnl_percent: float,
        duration: str,
        deal_id: str,
        timestamp: Optional[datetime] = None
    ) -> bool:
        """
        Send trade closed notification
        
        Args:
            direction: 'BUY' or 'SELL'
            entry_price: Entry price
            close_price: Close price
            close_reason: Reason for close (SL_HIT, TP_HIT, MANUAL, etc.)
            pnl: Profit/loss amount
            pnl_percent: P&L percentage
            duration: Trade duration string
            deal_id: Deal ID
            timestamp: Close timestamp (optional)
            
        Returns:
            bool indicating success
        """
        # Emoji based on P&L
        if pnl > 0:
            emoji = '✅'
            pnl_sign = '+'
        elif pnl < 0:
            emoji = '❌'
            pnl_sign = ''
        else:
            emoji = '⚪'
            pnl_sign = ''
        
        # Format close reason
        reason_emoji = {
            'SL_HIT': '🛑',
            'TP_HIT': '🎯',
            'MANUAL': '✋',
            'SIGNAL_CLOSE': '📊',
            'EOD': '🌅'
        }.get(close_reason, '🔄')
        
        time_str = (timestamp or datetime.now()).strftime('%Y-%m-%d %H:%M:%S')
        
        message = f"""
{emoji} *Trade Closed*

*Direction:* {direction}
*Entry:* ${entry_price:.2f}
*Exit:* ${close_price:.2f}
*P&L:* {pnl_sign}${abs(pnl):.2f} ({pnl_sign}{abs(pnl_percent):.2f}%)
*Reason:* {reason_emoji} {close_reason.replace('_', ' ')}
*Duration:* {duration}
*Deal ID:* `{deal_id}`
*Time:* {time_str}
"""
        
        return self.send_message(message)
    
    def send_error_alert(
        self,
        error_type: str,
        error_message: str,
        context: Optional[str] = None
    ) -> bool:
        """
        Send error alert
        
        Args:
            error_type: Type of error (e.g., 'API_ERROR', 'EXECUTION_ERROR')
            error_message: Error message
            context: Optional context information
            
        Returns:
            bool indicating success
        """
        message = f"""
⚠️ *Error Alert*

*Type:* {error_type}
*Message:* {error_message}
"""
        
        if context:
            message += f"*Context:* {context}\n"
        
        message += f"*Time:* {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        
        return self.send_message(message)
    
    def send_daily_summary(
        self,
        date: str,
        trades_count: int,
        wins: int,
        losses: int,
        total_pnl: float,
        win_rate: float,
        best_trade: float,
        worst_trade: float
    ) -> bool:
        """
        Send daily performance summary
        
        Args:
            date: Date string
            trades_count: Total number of trades
            wins: Number of winning trades
            losses: Number of losing trades
            total_pnl: Total P&L for the day
            win_rate: Win rate percentage
            best_trade: Best trade P&L
            worst_trade: Worst trade P&L
            
        Returns:
            bool indicating success
        """
        emoji = '📈' if total_pnl > 0 else '📉' if total_pnl < 0 else '➡️'
        pnl_sign = '+' if total_pnl > 0 else ''
        
        message = f"""
{emoji} *Daily Summary - {date}*

*Trades:* {trades_count} ({wins}W / {losses}L)
*Win Rate:* {win_rate:.1f}%
*Total P&L:* {pnl_sign}${total_pnl:.2f}
*Best Trade:* +${best_trade:.2f}
*Worst Trade:* -${abs(worst_trade):.2f}
"""
        
        return self.send_message(message)
    
    def send_cooldown_alert(
        self,
        cooldown_type: str,
        duration: str,
        reason: str
    ) -> bool:
        """
        Send cooldown notification
        
        Args:
            cooldown_type: 'SL' or 'TP'
            duration: Cooldown duration string
            reason: Reason for cooldown
            
        Returns:
            bool indicating success
        """
        emoji = '🛑' if cooldown_type == 'SL' else '🎯'
        
        message = f"""
{emoji} *Cooldown Active*

*Type:* {cooldown_type} Cooldown
*Duration:* {duration}
*Reason:* {reason}
*Time:* {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
        
        return self.send_message(message, disable_notification=True)
    
    def send_heartbeat(
        self,
        bot_status: str,
        uptime: str,
        open_positions: int,
        daily_pnl: float
    ) -> bool:
        """
        Send bot heartbeat status
        
        Args:
            bot_status: Bot status (RUNNING, PAUSED, etc.)
            uptime: Uptime string
            open_positions: Number of open positions
            daily_pnl: Daily P&L
            
        Returns:
            bool indicating success
        """
        emoji = '💚' if bot_status == 'RUNNING' else '💛'
        pnl_sign = '+' if daily_pnl > 0 else ''
        
        message = f"""
{emoji} *Bot Heartbeat*

*Status:* {bot_status}
*Uptime:* {uptime}
*Open Positions:* {open_positions}
*Daily P&L:* {pnl_sign}${daily_pnl:.2f}
*Time:* {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
        
        return self.send_message(message, disable_notification=True)

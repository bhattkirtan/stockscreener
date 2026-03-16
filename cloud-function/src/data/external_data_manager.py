"""
External Data Manager

Unified interface for all 4 external data feeds:
1. Capital.com (price/execution) - already integrated in strategy
2. Trading Economics (scheduled events calendar)
3. FRED (macro regime indicators)
4. NewsAPI (unscheduled headline monitoring)

Reference: strategy.md Section 6.6 (External Data Feeds Architecture)
"""

from typing import Optional, Dict, List
from dataclasses import dataclass
from datetime import datetime, timedelta
import logging

from ..data.trading_economics_adapter import TradingEconomicsAdapter
from ..data.fred_adapter import FREDAdapter, MacroContext, MacroRegime
from ..data.news_adapter import NewsAPIAdapter
from ..core.event_blocker import EventBlocker

logger = logging.getLogger(__name__)


@dataclass
class ExternalDataContext:
    """
    Complete external data context for strategy
    
    Includes macro regime, event blocking status, and news safety
    """
    timestamp: datetime
    
    # Feed 3: Macro regime (FRED)
    macro_regime: MacroRegime
    macro_context: Optional[MacroContext] = None
    position_size_multiplier: float = 1.0
    
    # Feed 2 + 4: Event/News blocking
    is_blocked: bool = False
    block_reason: Optional[str] = None
    minutes_to_next_event: Optional[int] = None
    minutes_since_last_news: Optional[int] = None
    
    def is_safe_to_trade(self) -> bool:
        """Check if all conditions are safe for trading"""
        return not self.is_blocked
    
    def to_dict(self) -> Dict:
        """Convert to dictionary"""
        return {
            'timestamp': self.timestamp.isoformat(),
            'macro_regime': self.macro_regime.value,
            'position_size_multiplier': self.position_size_multiplier,
            'is_blocked': self.is_blocked,
            'block_reason': self.block_reason,
            'minutes_to_next_event': self.minutes_to_next_event,
            'minutes_since_last_news': self.minutes_since_last_news,
            'macro_context': self.macro_context.to_dict() if self.macro_context else None
        }


class ExternalDataManager:
    """
    Unified manager for all external data feeds
    
    From strategy.md Section 6.6:
    - Feed 1: Capital.com (handled separately by strategy)
    - Feed 2: Trading Economics calendar
    - Feed 3: FRED macro series
    - Feed 4: NewsAPI headlines
    
    Provides simple interface for:
    - Checking if trading is blocked
    - Getting macro regime for position sizing
    - Retrieving minutes to next event for trade scoring
    """
    
    def __init__(
        self,
        # Feed 2: Trading Economics
        trading_econ_api_key: Optional[str] = None,
        enable_calendar: bool = True,
        
        # Feed 3: FRED
        fred_api_key: Optional[str] = None,
        enable_macro: bool = True,
        
        # Feed 4: NewsAPI
        news_api_key: Optional[str] = None,
        enable_news: bool = True,
        
        # Blocking parameters
        event_pre_window_minutes: int = 15,
        event_post_window_minutes: int = 15,
        news_block_duration_minutes: int = 10
    ):
        """
        Initialize external data manager
        
        Args:
            trading_econ_api_key: Trading Economics API key
            enable_calendar: Enable calendar event blocking
            fred_api_key: FRED API key
            enable_macro: Enable macro regime detection
            news_api_key: NewsAPI key
            enable_news: Enable news headline blocking
            event_pre_window_minutes: Block before events (15 min)
            event_post_window_minutes: Block after events (15 min)
            news_block_duration_minutes: Block after news (10 min)
        """
        self.enable_calendar = enable_calendar
        self.enable_macro = enable_macro
        self.enable_news = enable_news
        
        # Feed 2: Trading Economics calendar
        self.calendar_adapter = None
        if enable_calendar:
            self.calendar_adapter = TradingEconomicsAdapter(
                api_key=trading_econ_api_key,
                refresh_interval_hours=4,
                cache_ttl_hours=48
            )
            logger.info("📅 Trading Economics calendar: Enabled")
        
        # Feed 3: FRED macro
        self.fred_adapter = None
        if enable_macro:
            self.fred_adapter = FREDAdapter(
                api_key=fred_api_key,
                update_interval_hours=24,
                cache_ttl_hours=24
            )
            logger.info("📊 FRED macro regime: Enabled")
        
        # Feed 4: NewsAPI
        self.news_adapter = None
        if enable_news:
            self.news_adapter = NewsAPIAdapter(
                api_key=news_api_key,
                refresh_interval_minutes=5,
                block_duration_minutes=news_block_duration_minutes
            )
            logger.info("📰 NewsAPI headlines: Enabled")
        
        # Event blocker (combines calendar + news)
        self.event_blocker = None
        if enable_calendar and self.calendar_adapter:
            self.event_blocker = EventBlocker(
                calendar_adapter=self.calendar_adapter,
                news_adapter=self.news_adapter if enable_news else None,
                pre_event_minutes=event_pre_window_minutes,
                post_event_minutes=event_post_window_minutes
            )
            logger.info(
                f"🚫 Event blocker: Enabled "
                f"(±{event_pre_window_minutes}min calendar, "
                f"{news_block_duration_minutes}min news)"
            )
    
    def get_external_data_context(
        self,
        current_time: Optional[datetime] = None,
        current_atr: Optional[float] = None,
        normal_atr: Optional[float] = None
    ) -> ExternalDataContext:
        """
        Get complete external data context
        
        Args:
            current_time: Current timestamp (default: now)
            current_atr: Current ATR (for stabilization check)
            normal_atr: Normal ATR (for stabilization check)
        
        Returns:
            ExternalDataContext with all feed data
        """
        if current_time is None:
            current_time = datetime.utcnow()
        
        # Default context
        context = ExternalDataContext(
            timestamp=current_time,
            macro_regime=MacroRegime.UNKNOWN,
            position_size_multiplier=1.0,
            is_blocked=False,
            block_reason=None,
            minutes_to_next_event=None,
            minutes_since_last_news=None
        )
        
        # Feed 3: Get macro regime
        if self.enable_macro and self.fred_adapter:
            try:
                macro_context = self.fred_adapter.get_current_regime()
                context.macro_regime = macro_context.regime
                context.macro_context = macro_context
                context.position_size_multiplier = macro_context.get_position_size_multiplier()
            except Exception as e:
                logger.error(f"Failed to get macro regime: {e}")
        
        # Feed 2 + 4: Check event blocking
        if self.event_blocker:
            try:
                is_allowed, block_reason = self.event_blocker.is_trading_allowed(
                    current_time,
                    current_atr=current_atr,
                    normal_atr=normal_atr
                )
                
                context.is_blocked = not is_allowed
                context.block_reason = block_reason
                
                # Get minutes to next event (for trade scoring)
                if self.calendar_adapter:
                    context.minutes_to_next_event = self.calendar_adapter.get_minutes_to_next_event(
                        current_time
                    )
                
                # Get minutes since last news
                if self.news_adapter:
                    context.minutes_since_last_news = self.news_adapter.get_minutes_since_last_alert(
                        current_time
                    )
            
            except Exception as e:
                logger.error(f"Failed to check event blocking: {e}")
        
        return context
    
    def is_trading_allowed(
        self,
        current_time: Optional[datetime] = None,
        current_atr: Optional[float] = None,
        normal_atr: Optional[float] = None
    ) -> tuple[bool, Optional[str]]:
        """
        Simple check: Is trading allowed right now?
        
        Args:
            current_time: Current timestamp
            current_atr: Current ATR
            normal_atr: Normal ATR
        
        Returns:
            Tuple of (is_allowed, block_reason)
        """
        if current_time is None:
            current_time = datetime.utcnow()
        
        if self.event_blocker:
            return self.event_blocker.is_trading_allowed(
                current_time,
                current_atr=current_atr,
                normal_atr=normal_atr
            )
        
        return True, None
    
    def get_position_size_multiplier(
        self,
        force_refresh: bool = False
    ) -> float:
        """
        Get position size multiplier from macro regime
        
        Args:
            force_refresh: Force refresh from FRED
        
        Returns:
            Multiplier (0.5 to 1.0)
        """
        if not self.enable_macro or not self.fred_adapter:
            return 1.0
        
        try:
            macro_context = self.fred_adapter.get_current_regime(
                force_refresh=force_refresh
            )
            return macro_context.get_position_size_multiplier()
        except Exception as e:
            logger.error(f"Failed to get position size multiplier: {e}")
            return 1.0
    
    def get_minutes_to_next_event(
        self,
        current_time: Optional[datetime] = None
    ) -> Optional[int]:
        """
        Get minutes until next high-impact event
        
        Used by trade scorer for news-safety score.
        
        Args:
            current_time: Current timestamp
        
        Returns:
            Minutes to next event or None
        """
        if not self.enable_calendar or not self.calendar_adapter:
            return None
        
        if current_time is None:
            current_time = datetime.utcnow()
        
        try:
            return self.calendar_adapter.get_minutes_to_next_event(current_time)
        except Exception as e:
            logger.error(f"Failed to get minutes to next event: {e}")
            return None
    
    def get_status_summary(
        self,
        current_time: Optional[datetime] = None
    ) -> Dict:
        """
        Get comprehensive status summary of all feeds
        
        Args:
            current_time: Current timestamp
        
        Returns:
            Dictionary with feed statuses
        """
        if current_time is None:
            current_time = datetime.utcnow()
        
        context = self.get_external_data_context(current_time)
        
        summary = {
            'timestamp': current_time.isoformat(),
            'feeds_enabled': {
                'calendar': self.enable_calendar,
                'macro': self.enable_macro,
                'news': self.enable_news
            },
            'trading_allowed': not context.is_blocked,
            'block_reason': context.block_reason,
            'macro_regime': context.macro_regime.value,
            'position_size_multiplier': context.position_size_multiplier,
            'minutes_to_next_event': context.minutes_to_next_event,
            'minutes_since_last_news': context.minutes_since_last_news
        }
        
        # Add macro details if available
        if context.macro_context:
            summary['macro_details'] = {
                'fed_funds_rate': context.macro_context.fed_funds_rate,
                'treasury_10y': context.macro_context.treasury_10y,
                'yield_curve': context.macro_context.yield_curve,
                'cpi_yoy': context.macro_context.cpi_yoy,
                'unemployment_rate': context.macro_context.unemployment_rate,
                'gdp_growth': context.macro_context.gdp_growth,
                'confidence': context.macro_context.confidence
            }
        
        return summary

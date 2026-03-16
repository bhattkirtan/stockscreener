"""
Federal Reserve Economic Data (FRED) API Adapter

Fetches macro indicators for regime detection and position sizing.

Reference: strategy.md Section 6.6.3 (Feed 3: FRED Macro Series)
"""

import pandas as pd
import numpy as np
from typing import Optional, Dict, List
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
import logging
import requests

logger = logging.getLogger(__name__)


class MacroRegime(Enum):
    """
    Macro regime classification
    
    From strategy.md Section 6.6.3:
    - EXPANSION: Growth accelerating, inflation controlled
    - SLOWDOWN: Growth decelerating, inflation rising
    - RECESSION: Negative growth, high unemployment
    - RECOVERY: Growth resuming, unemployment falling
    - STAGFLATION: Stagnant growth + high inflation
    """
    EXPANSION = "expansion"
    SLOWDOWN = "slowdown"
    RECESSION = "recession"
    RECOVERY = "recovery"
    STAGFLATION = "stagflation"
    UNKNOWN = "unknown"


@dataclass
class MacroContext:
    """
    Current macro regime context
    
    Contains all FRED indicators and derived regime
    """
    regime: MacroRegime
    timestamp: datetime
    
    # Interest rates
    fed_funds_rate: Optional[float] = None  # DFF
    treasury_10y: Optional[float] = None    # DGS10
    yield_curve: Optional[float] = None     # T10Y2Y (10Y-2Y spread)
    
    # Currency
    dollar_index: Optional[float] = None    # DTWEXBGS
    
    # Inflation & employment
    cpi_yoy: Optional[float] = None         # CPI year-over-year
    unemployment_rate: Optional[float] = None  # UNRATE
    
    # Growth
    gdp_growth: Optional[float] = None      # GDP quarter-over-quarter
    
    # Recession indicator
    recession_probability: Optional[float] = None  # USREC (0 or 1)
    
    # Confidence score for regime (0.0 to 1.0)
    confidence: float = 0.5
    
    def is_risk_on(self) -> bool:
        """Check if regime is risk-on (favorable for trading)"""
        return self.regime in [MacroRegime.EXPANSION, MacroRegime.RECOVERY]
    
    def is_risk_off(self) -> bool:
        """Check if regime is risk-off (defensive)"""
        return self.regime in [MacroRegime.RECESSION, MacroRegime.STAGFLATION]
    
    def get_position_size_multiplier(self) -> float:
        """
        Get position size adjustment based on regime
        
        From strategy.md Section 6.6.3:
        - Expansion: 1.0x (normal)
        - Recovery: 1.0x (normal)
        - Slowdown: 0.75x (reduce risk)
        - Recession: 0.5x (defensive)
        - Stagflation: 0.5x (defensive)
        
        Returns:
            Multiplier (0.5 to 1.0)
        """
        if self.regime == MacroRegime.EXPANSION:
            return 1.0
        elif self.regime == MacroRegime.RECOVERY:
            return 1.0
        elif self.regime == MacroRegime.SLOWDOWN:
            return 0.75
        elif self.regime == MacroRegime.RECESSION:
            return 0.5
        elif self.regime == MacroRegime.STAGFLATION:
            return 0.5
        else:
            return 0.75  # Unknown = cautious
    
    def to_dict(self) -> Dict:
        """Convert to dictionary"""
        return {
            'regime': self.regime.value,
            'timestamp': self.timestamp.isoformat(),
            'fed_funds_rate': self.fed_funds_rate,
            'treasury_10y': self.treasury_10y,
            'yield_curve': self.yield_curve,
            'dollar_index': self.dollar_index,
            'cpi_yoy': self.cpi_yoy,
            'unemployment_rate': self.unemployment_rate,
            'gdp_growth': self.gdp_growth,
            'recession_probability': self.recession_probability,
            'confidence': self.confidence,
            'position_size_multiplier': self.get_position_size_multiplier()
        }


class FREDAdapter:
    """
    Adapter for FRED (Federal Reserve Economic Data) API
    
    From strategy.md Section 6.6.3:
    - 8 indicators: DFF, DGS10, T10Y2Y, DTWEXBGS, CPI, UNRATE, GDP, USREC
    - Update frequency: Daily
    - Cache: 24-hour TTL
    - Regime detection: 5 states
    
    Configuration:
    - FRED_UPDATE_INTERVAL: 24 hours
    - FRED_CACHE_TTL: 24 hours
    - FRED_SERIES: 8 series IDs
    """
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        update_interval_hours: int = 24,
        cache_ttl_hours: int = 24,
        use_fallback: bool = True
    ):
        """
        Initialize FRED adapter
        
        Args:
            api_key: FRED API key (free from https://fred.stlouisfed.org)
            update_interval_hours: Update interval (24 hours)
            cache_ttl_hours: Cache TTL (24 hours)
            use_fallback: Use manual fallback if API fails
        """
        self.api_key = api_key
        self.update_interval = timedelta(hours=update_interval_hours)
        self.cache_ttl = timedelta(hours=cache_ttl_hours)
        self.use_fallback = use_fallback
        
        # FRED series IDs (strategy.md Section 6.6.3)
        self.series_ids = {
            'DFF': 'fed_funds_rate',        # Federal Funds Rate
            'DGS10': 'treasury_10y',        # 10-Year Treasury
            'T10Y2Y': 'yield_curve',        # 10Y-2Y Spread
            'DTWEXBGS': 'dollar_index',     # Dollar Index (Broad)
            'CPIAUCSL': 'cpi',              # CPI (All Urban Consumers)
            'UNRATE': 'unemployment_rate',  # Unemployment Rate
            'GDP': 'gdp',                   # GDP
            'USREC': 'recession'            # Recession Indicator
        }
        
        # Cache
        self.cached_data: Dict[str, pd.DataFrame] = {}
        self.last_refresh: Optional[datetime] = None
        self.cached_regime: Optional[MacroContext] = None
        
        # API endpoint
        self.base_url = "https://api.stlouisfed.org/fred"
    
    def needs_refresh(self, current_time: datetime) -> bool:
        """Check if cache needs refresh"""
        if self.last_refresh is None:
            return True
        
        time_since_refresh = current_time - self.last_refresh
        return time_since_refresh >= self.update_interval
    
    def fetch_series_from_api(
        self,
        series_id: str,
        start_date: datetime,
        end_date: datetime
    ) -> Optional[pd.DataFrame]:
        """
        Fetch single series from FRED API
        
        API endpoint: GET /series/observations
        
        Args:
            series_id: FRED series ID (e.g., 'DFF')
            start_date: Start date
            end_date: End date
        
        Returns:
            DataFrame with date and value columns
        """
        if not self.api_key:
            logger.warning("No FRED API key configured")
            return None
        
        try:
            # Format dates
            from_date = start_date.strftime('%Y-%m-%d')
            to_date = end_date.strftime('%Y-%m-%d')
            
            # Build URL
            url = f"{self.base_url}/series/observations"
            params = {
                'series_id': series_id,
                'api_key': self.api_key,
                'file_type': 'json',
                'observation_start': from_date,
                'observation_end': to_date
            }
            
            # Make request
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            
            # Parse response
            data = response.json()
            observations = data.get('observations', [])
            
            if not observations:
                return None
            
            # Convert to DataFrame
            df = pd.DataFrame(observations)
            df['date'] = pd.to_datetime(df['date'])
            df['value'] = pd.to_numeric(df['value'], errors='coerce')
            
            # Filter out missing values
            df = df[df['value'].notna()]
            
            if df.empty:
                return None
            
            df = df[['date', 'value']].set_index('date')
            
            logger.debug(f"Fetched {len(df)} observations for {series_id}")
            return df
        
        except Exception as e:
            logger.error(f"Failed to fetch {series_id} from FRED API: {e}")
            return None
    
    def fetch_all_series(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        force_refresh: bool = False
    ) -> Dict[str, pd.DataFrame]:
        """
        Fetch all FRED series
        
        Args:
            start_date: Start date (default: 1 year ago)
            end_date: End date (default: today)
            force_refresh: Force refresh even if cache valid
        
        Returns:
            Dictionary of series DataFrames
        """
        current_time = datetime.utcnow()
        
        # Default date range: last 1 year
        if end_date is None:
            end_date = current_time
        if start_date is None:
            start_date = end_date - timedelta(days=365)
        
        # Check if refresh needed
        if not force_refresh and not self.needs_refresh(current_time):
            logger.debug("Using cached FRED data")
            return self.cached_data
        
        # Fetch each series
        series_data = {}
        for series_id, field_name in self.series_ids.items():
            df = self.fetch_series_from_api(series_id, start_date, end_date)
            
            if df is not None:
                series_data[field_name] = df
        
        # Update cache
        if series_data:
            self.cached_data = series_data
            self.last_refresh = current_time
            logger.info(f"Fetched {len(series_data)} FRED series")
        
        return series_data
    
    def calculate_cpi_yoy(self, cpi_series: pd.DataFrame) -> Optional[float]:
        """Calculate CPI year-over-year change"""
        if len(cpi_series) < 252:  # Need ~1 year of data
            return None
        
        current_cpi = cpi_series['value'].iloc[-1]
        year_ago_cpi = cpi_series['value'].iloc[-252]
        
        yoy_change = ((current_cpi - year_ago_cpi) / year_ago_cpi) * 100
        return yoy_change
    
    def calculate_gdp_growth(self, gdp_series: pd.DataFrame) -> Optional[float]:
        """Calculate GDP quarter-over-quarter growth"""
        if len(gdp_series) < 2:
            return None
        
        current_gdp = gdp_series['value'].iloc[-1]
        prev_gdp = gdp_series['value'].iloc[-2]
        
        qoq_growth = ((current_gdp - prev_gdp) / prev_gdp) * 100
        return qoq_growth
    
    def detect_regime(
        self,
        series_data: Optional[Dict[str, pd.DataFrame]] = None
    ) -> MacroContext:
        """
        Detect macro regime from FRED indicators
        
        Regime logic from strategy.md Section 6.6.3:
        - EXPANSION: GDP > 2%, Unemployment < 5%, CPI < 3%, Yield curve > 0
        - SLOWDOWN: GDP < 2%, Yield curve < 0 (inverted)
        - RECESSION: USREC = 1 OR Unemployment > 6% AND GDP < 0
        - RECOVERY: GDP > 0%, Unemployment falling
        - STAGFLATION: GDP < 1% AND CPI > 4%
        
        Args:
            series_data: Dictionary of FRED series (optional)
        
        Returns:
            MacroContext with regime classification
        """
        current_time = datetime.utcnow()
        
        # Fetch data if not provided
        if series_data is None:
            series_data = self.fetch_all_series()
        
        # Extract latest values
        fed_funds = None
        treasury_10y = None
        yield_curve = None
        dollar_index = None
        cpi_yoy = None
        unemployment = None
        gdp_growth = None
        recession = None
        
        if 'fed_funds_rate' in series_data:
            fed_funds = series_data['fed_funds_rate']['value'].iloc[-1]
        
        if 'treasury_10y' in series_data:
            treasury_10y = series_data['treasury_10y']['value'].iloc[-1]
        
        if 'yield_curve' in series_data:
            yield_curve = series_data['yield_curve']['value'].iloc[-1]
        
        if 'dollar_index' in series_data:
            dollar_index = series_data['dollar_index']['value'].iloc[-1]
        
        if 'cpi' in series_data:
            cpi_yoy = self.calculate_cpi_yoy(series_data['cpi'])
        
        if 'unemployment_rate' in series_data:
            unemployment = series_data['unemployment_rate']['value'].iloc[-1]
        
        if 'gdp' in series_data:
            gdp_growth = self.calculate_gdp_growth(series_data['gdp'])
        
        if 'recession' in series_data:
            recession = series_data['recession']['value'].iloc[-1]
        
        # Detect regime
        regime = MacroRegime.UNKNOWN
        confidence = 0.5
        
        # Check recession first
        if recession is not None and recession >= 0.5:
            regime = MacroRegime.RECESSION
            confidence = 0.9
        
        # Check stagflation
        elif (gdp_growth is not None and cpi_yoy is not None and
              gdp_growth < 1.0 and cpi_yoy > 4.0):
            regime = MacroRegime.STAGFLATION
            confidence = 0.8
        
        # Check expansion
        elif (gdp_growth is not None and unemployment is not None and
              cpi_yoy is not None and yield_curve is not None and
              gdp_growth > 2.0 and unemployment < 5.0 and
              cpi_yoy < 3.0 and yield_curve > 0):
            regime = MacroRegime.EXPANSION
            confidence = 0.85
        
        # Check slowdown
        elif (gdp_growth is not None and yield_curve is not None and
              gdp_growth < 2.0 and yield_curve < 0):
            regime = MacroRegime.SLOWDOWN
            confidence = 0.75
        
        # Check recovery
        elif (gdp_growth is not None and unemployment is not None and
              gdp_growth > 0 and unemployment < 6.0):
            regime = MacroRegime.RECOVERY
            confidence = 0.7
        
        # Create macro context
        macro_context = MacroContext(
            regime=regime,
            timestamp=current_time,
            fed_funds_rate=fed_funds,
            treasury_10y=treasury_10y,
            yield_curve=yield_curve,
            dollar_index=dollar_index,
            cpi_yoy=cpi_yoy,
            unemployment_rate=unemployment,
            gdp_growth=gdp_growth,
            recession_probability=recession,
            confidence=confidence
        )
        
        # Cache regime
        self.cached_regime = macro_context
        
        logger.info(
            f"Macro regime: {regime.value} "
            f"(confidence: {confidence:.2f}, "
            f"position multiplier: {macro_context.get_position_size_multiplier():.2f}x)"
        )
        
        return macro_context
    
    def get_current_regime(
        self,
        force_refresh: bool = False
    ) -> MacroContext:
        """
        Get current macro regime
        
        Args:
            force_refresh: Force refresh from API
        
        Returns:
            MacroContext with current regime
        """
        current_time = datetime.utcnow()
        
        # Use cache if valid
        if (not force_refresh and 
            self.cached_regime is not None and 
            not self.needs_refresh(current_time)):
            return self.cached_regime
        
        # Fetch and detect regime
        return self.detect_regime()

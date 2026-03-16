"""
Wrapper for Cloud Functions entry points
Re-exports functions from functions/main.py for Cloud Functions deployment
"""

from functions.main import (
    hello_http,
    scheduler_control
)
from functions.main_data_updater import update_market_data
from functions.main_api import optimize_api

# Re-export all functions so Cloud Functions can find them
__all__ = [
    'hello_http',
    'scheduler_control',
    'update_market_data',
    'optimize_api'
]

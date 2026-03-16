"""
Wrapper for Data Updater entry point
Re-exports update_market_data from functions/main_data_updater.py for Cloud Functions deployment
"""

from functions.main_data_updater import update_market_data

# Re-export so Cloud Functions can find it
__all__ = ['update_market_data']

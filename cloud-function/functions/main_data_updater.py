"""
Entry point for data updater Cloud Function
"""

from src.data_updater import update_market_data

# Re-export the function for Cloud Functions
__all__ = ['update_market_data']

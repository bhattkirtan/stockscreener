"""
Wrapper for Optimization API entry point
Re-exports optimize_api from functions/main_api.py for Cloud Functions deployment
"""

from functions.main_api import optimize_api

# Re-export so Cloud Functions can find it
__all__ = ['optimize_api']

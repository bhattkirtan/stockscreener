"""
Wrapper for Read-only API entry point
Re-exports readonly functions from functions/main_readonly.py for Cloud Functions deployment
"""

from functions.main_readonly import readonly_api

# Re-export so Cloud Functions can find it
__all__ = ['readonly_api']

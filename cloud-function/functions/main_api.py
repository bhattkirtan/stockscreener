"""
Main entry point for Cloud Functions
Routes to the enhanced optimization API
"""

from src.api_functions_enhanced import optimize_api

# Export the main function
__all__ = ['optimize_api']

#!/usr/bin/env python3
"""
Cloud Function Adapter - Lightweight Read-Only API
Deploys to Google Cloud Functions for viewing results only
Run optimizations locally, store results in Cloud Storage
"""

import functions_framework
from flask import jsonify, request
import json
from pathlib import Path
from google.cloud import storage
import pandas as pd
from typing import Optional

# Initialize Cloud Storage client
storage_client = storage.Client()
BUCKET_NAME = "your-optimization-results-bucket"  # Configure this


def load_results_from_gcs(run_id: str = "latest") -> Optional[dict]:
    """Load results from Cloud Storage"""
    try:
        bucket = storage_client.bucket(BUCKET_NAME)
        
        # Load summary JSON
        blob = bucket.blob(f"{run_id}/FINAL_SUMMARY.json")
        summary = json.loads(blob.download_as_text())
        
        # Load CSV
        blob = bucket.blob(f"{run_id}/GOLD_M5_all_strategies.csv")
        csv_data = blob.download_as_text()
        df = pd.read_csv(pd.io.common.StringIO(csv_data))
        
        return {"summary": summary, "df": df}
    except Exception as e:
        print(f"Error loading from GCS: {e}")
        return None


@functions_framework.http
def optimize_api(request):
    """
    Cloud Function HTTP entry point
    Handles read-only API endpoints
    """
    
    # CORS headers
    if request.method == 'OPTIONS':
        headers = {
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
            'Access-Control-Allow-Headers': 'Content-Type',
            'Access-Control-Max-Age': '3600'
        }
        return ('', 204, headers)
    
    headers = {
        'Access-Control-Allow-Origin': '*',
        'Content-Type': 'application/json'
    }
    
    # Route handling
    path = request.path
    method = request.method
    
    try:
        # Health check
        if path == '/health':
            return jsonify({
                "status": "healthy",
                "service": "optimization-api-readonly",
                "note": "Read-only Cloud Function. Run optimizations locally."
            }), 200, headers
        
        # Get latest analysis
        if path == '/api/analyze/latest' and method == 'GET':
            data = load_results_from_gcs("latest")
            if not data:
                return jsonify({"error": "No results available"}), 404, headers
            
            df = data["df"]
            summary = data["summary"]
            
            # Build analysis response
            best_row = df.iloc[0]
            
            # pip_value analysis
            pip_analysis = {}
            for pv in sorted(df['pip_value'].unique()):
                subset = df[df['pip_value'] == pv]
                profitable = len(subset[subset['total_pnl'] > 0])
                pip_analysis[str(pv)] = {
                    "count": len(subset),
                    "profitable": profitable,
                    "profitable_pct": round(100 * profitable / len(subset), 1),
                    "avg_profit": round(subset['total_pnl'].mean(), 2),
                    "max_profit": round(subset['total_pnl'].max(), 2),
                    "best_return": round(subset['return_pct'].max(), 2)
                }
            
            response = {
                "run_id": "latest",
                "date": summary["optimization_run"]["date"],
                "instrument": summary["optimization_run"]["instrument"],
                "timeframe": summary["optimization_run"]["timeframe"],
                "total_combinations": summary["results_overview"]["total_combinations_tested"],
                "best_strategy": {
                    "strategy_name": best_row["strategy_name"],
                    "return_pct": round(best_row["return_pct"], 2),
                    "total_pnl": round(best_row["total_pnl"], 2),
                    "sharpe_ratio": round(best_row["sharpe_ratio"], 2),
                    "win_rate": round(best_row["win_rate"], 2),
                    "total_trades": int(best_row["total_trades"]),
                    "profit_factor": round(best_row["profit_factor"], 2)
                },
                "pip_value_analysis": pip_analysis
            }
            
            return jsonify(response), 200, headers
        
        # Get top strategies
        if path.startswith('/api/optimize/results/') and method == 'GET':
            top_n = int(request.args.get('top_n', 10))
            
            data = load_results_from_gcs("latest")
            if not data:
                return jsonify({"error": "No results available"}), 404, headers
            
            df = data["df"]
            
            top_strategies = []
            for i in range(min(top_n, len(df))):
                row = df.iloc[i]
                top_strategies.append({
                    "rank": i + 1,
                    "strategy_name": row["strategy_name"],
                    "return_pct": round(row["return_pct"], 2),
                    "total_pnl": round(row["total_pnl"], 2),
                    "win_rate": round(row["win_rate"], 2),
                    "total_trades": int(row["total_trades"])
                })
            
            return jsonify({
                "top_strategies": top_strategies,
                "total_strategies": len(df)
            }), 200, headers
        
        # Start optimization - NOT SUPPORTED
        if path == '/api/optimize' and method == 'POST':
            return jsonify({
                "error": "Optimization not supported in Cloud Function",
                "message": "Run optimizations locally and upload results to Cloud Storage",
                "instructions": "Use the API server on Cloud Run or local machine"
            }), 501, headers
        
        # Default - unsupported endpoint
        return jsonify({
            "error": "Endpoint not found",
            "supported_endpoints": [
                "GET /health",
                "GET /api/analyze/latest",
                "GET /api/optimize/results/latest"
            ]
        }), 404, headers
        
    except Exception as e:
        return jsonify({
            "error": str(e)
        }), 500, headers


if __name__ == "__main__":
    # For local testing
    from flask import Flask
    app = Flask(__name__)
    app.route('/', defaults={'path': ''})(optimize_api)
    app.route('/<path:path>', methods=['GET', 'POST', 'OPTIONS'])(optimize_api)
    app.run(host='0.0.0.0', port=8080, debug=True)

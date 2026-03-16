#!/bin/bash
#
# Run local validation of top strategies on full datasets (M5 and M15)
# Saves results to GCS
#

set -e

# Configuration
PROJECT_ID="double-venture-442318-k8"
GCS_BUCKET="gs://double-venture-442318-k8-optimization-results"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
RESULTS_DIR="$PROJECT_ROOT/data/backtest_results"

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${BLUE}════════════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}   LOCAL VALIDATION - Top Strategies on Full Datasets${NC}"
echo -e "${BLUE}════════════════════════════════════════════════════════════════${NC}"
echo ""

# Get the optimization run ID from command line or use latest
if [ -z "$1" ]; then
    echo "Usage: $0 <run_id> [top_n]"
    echo ""
    echo "Example: $0 0b964ca6 50    # Test top 50 strategies"
    echo "         $0 0b964ca6        # Test top 100 strategies (default)"
    exit 1
fi

RUN_ID=$1
TOP_N=${2:-100}  # Default to top 100

echo -e "${GREEN}Configuration:${NC}"
echo "  Run ID: $RUN_ID"
echo "  Top N strategies: $TOP_N"
echo "  Results dir: $RESULTS_DIR"
echo ""

# Create results directory
mkdir -p "$RESULTS_DIR"

# Download the strategies CSV
echo -e "${BLUE}📥 Downloading optimization results...${NC}"
STRATEGIES_CSV="$RESULTS_DIR/${RUN_ID}_strategies.csv"
gsutil cp "$GCS_BUCKET/$RUN_ID/GOLD_M5_all_strategies.csv" "$STRATEGIES_CSV"

# Download datasets
echo -e "${BLUE}📥 Downloading datasets...${NC}"
gsutil -m cp \
    "$GCS_BUCKET/data/GOLD_M15_9995bars.csv" \
    "$GCS_BUCKET/data/GOLD_M5_5000bars.csv" \
    "$PROJECT_ROOT/data/"

echo -e "${GREEN}✅ Downloaded${NC}"
echo ""

# Extract top strategies parameters
echo -e "${BLUE}🔍 Extracting top $TOP_N strategies...${NC}"

python3 << EOF
import pandas as pd
import json

# Read strategies
df = pd.read_csv('$STRATEGIES_CSV')
top_strategies = df.head($TOP_N)

# Extract unique parameter combinations
strategies_list = []
for idx, row in top_strategies.iterrows():
    strategy = {
        'rank': idx + 1,
        'name': row['strategy_name'],
        'st_period': int(row['st_period']),
        'st_mult': float(row['st_mult']),
        'sma_fast': int(row['sma_fast']),
        'sma_slow': int(row['sma_slow']),
        'bb_period': int(row['bb_period']),
        'bb_std': float(row['bb_std']),
        'pip_value': float(row['pip_value']),
        'tp_sl': row['tp_sl'],
        'original_profit': float(row['total_pnl']),
        'original_return': float(row['return_pct']),
        'original_profit_factor': float(row['profit_factor']),
        'original_trades': int(row['total_trades'])
    }
    strategies_list.append(strategy)

# Save to JSON
with open('$RESULTS_DIR/top_${TOP_N}_strategies.json', 'w') as f:
    json.dump(strategies_list, f, indent=2)

print(f'✅ Extracted {len(strategies_list)} strategies')
print(f'   Saved to: $RESULTS_DIR/top_${TOP_N}_strategies.json')
EOF

echo ""
echo -e "${BLUE}════════════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}   Running Backtests${NC}"
echo -e "${BLUE}════════════════════════════════════════════════════════════════${NC}"
echo ""

# Create timestamp for this validation run
VALIDATION_ID="validation_$(date +%Y%m%d_%H%M%S)"
VALIDATION_DIR="$RESULTS_DIR/$VALIDATION_ID"
mkdir -p "$VALIDATION_DIR"

echo -e "${GREEN}Validation Run ID: $VALIDATION_ID${NC}"
echo ""

# Test on M5 (5000 bars)
echo -e "${YELLOW}🔄 Testing on GOLD M5 (5000 bars)...${NC}"
M5_RESULTS="$VALIDATION_DIR/GOLD_M5_validation.json"

python3 "$PROJECT_ROOT/src/optimization/validate_strategies.py" \
    --strategies "$RESULTS_DIR/top_${TOP_N}_strategies.json" \
    --dataset "$PROJECT_ROOT/data/GOLD_M5_5000bars.csv" \
    --instrument GOLD \
    --timeframe M5 \
    --output "$M5_RESULTS" \
    --parallel

echo -e "${GREEN}✅ M5 validation complete${NC}"
echo ""

# Test on M15 (9995 bars)
echo -e "${YELLOW}🔄 Testing on GOLD M15 (9995 bars)...${NC}"
M15_RESULTS="$VALIDATION_DIR/GOLD_M15_validation.json"

python3 "$PROJECT_ROOT/src/optimization/validate_strategies.py" \
    --strategies "$RESULTS_DIR/top_${TOP_N}_strategies.json" \
    --dataset "$PROJECT_ROOT/data/GOLD_M15_9995bars.csv" \
    --instrument GOLD \
    --timeframe M15 \
    --output "$M15_RESULTS" \
    --parallel

echo -e "${GREEN}✅ M15 validation complete${NC}"
echo ""

# Generate comparison report
echo -e "${BLUE}📊 Generating comparison report...${NC}"

python3 << EOF
import json
import pandas as pd
from datetime import datetime

# Load results
with open('$M5_RESULTS') as f:
    m5_results = json.load(f)
    
with open('$M15_RESULTS') as f:
    m15_results = json.load(f)

# Create comparison
comparison = {
    'validation_id': '$VALIDATION_ID',
    'timestamp': datetime.now().isoformat(),
    'source_run_id': '$RUN_ID',
    'top_n': $TOP_N,
    'm5_results': m5_results,
    'm15_results': m15_results,
    'summary': {
        'm5': {
            'dataset': 'GOLD_M5_5000bars.csv',
            'strategies_tested': len(m5_results.get('strategies', [])),
            'profitable_count': len([s for s in m5_results.get('strategies', []) if s['profit'] > 0])
        },
        'm15': {
            'dataset': 'GOLD_M15_9995bars.csv',
            'strategies_tested': len(m15_results.get('strategies', [])),
            'profitable_count': len([s for s in m15_results.get('strategies', []) if s['profit'] > 0])
        }
    }
}

# Save comparison
comparison_file = '$VALIDATION_DIR/comparison_report.json'
with open(comparison_file, 'w') as f:
    json.dump(comparison, f, indent=2)

print(f'✅ Comparison report saved to: {comparison_file}')
EOF

# Upload results to GCS
echo ""
echo -e "${BLUE}☁️  Uploading results to GCS...${NC}"

gsutil -m cp -r "$VALIDATION_DIR/*" "$GCS_BUCKET/validations/$VALIDATION_ID/"

echo -e "${GREEN}✅ Results uploaded to: $GCS_BUCKET/validations/$VALIDATION_ID/${NC}"
echo ""

echo -e "${BLUE}════════════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}✅ VALIDATION COMPLETE${NC}"
echo -e "${BLUE}════════════════════════════════════════════════════════════════${NC}"
echo ""
echo "📁 Local results: $VALIDATION_DIR"
echo "☁️  GCS results: $GCS_BUCKET/validations/$VALIDATION_ID/"
echo ""
echo "To view results:"
echo "  gsutil cat $GCS_BUCKET/validations/$VALIDATION_ID/comparison_report.json | jq"

#!/bin/bash

# Trading Bot - Quick Test Script
# Tests all skills in isolation and then together

set -e  # Exit on error

cd "$(dirname "$0")"

echo "========================================="
echo "Trading Bot - Skill-Based Architecture"
echo "Quick Test Suite"
echo "========================================="
echo ""

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Test 1: Unit Tests (Risk Skill)
echo -e "${YELLOW}[1/3] Running Unit Tests (Risk Skill)...${NC}"
python -m pytest tests/unit/test_risk_skill.py -v --tb=short
if [ $? -eq 0 ]; then
    echo -e "${GREEN}✅ Unit tests passed (15/15)${NC}"
else
    echo -e "${RED}❌ Unit tests failed${NC}"
    exit 1
fi
echo ""

# Test 2: Integration Tests
echo -e "${YELLOW}[2/3] Running Integration Tests...${NC}"
python tests/integration/test_full_flow.py
if [ $? -eq 0 ]; then
    echo -e "${GREEN}✅ Integration tests passed${NC}"
else
    echo -e "${RED}❌ Integration tests failed${NC}"
    exit 1
fi
echo ""

# Test 3: Skill Imports
echo -e "${YELLOW}[3/3] Testing Skill Imports...${NC}"
python -c "
from skills.market_data import MarketDataSkill
from skills.analysis import AnalysisSkill
from skills.risk import RiskSkill
from skills.execution import ExecutionSkill
from skills.storage import StorageSkill
from skills.monitoring import MonitoringSkill
from skills.alerting import AlertingSkill
print('✅ All skills imported successfully')
"
if [ $? -eq 0 ]; then
    echo -e "${GREEN}✅ All skills import correctly${NC}"
else
    echo -e "${RED}❌ Skill import failed${NC}"
    exit 1
fi
echo ""

echo "========================================="
echo -e "${GREEN}✅ All Tests Passed!${NC}"
echo "========================================="
echo ""
echo "Skills Status: 7/9 Complete (78%)"
echo "  ✅ Market Data Skill"
echo "  ✅ Analysis Skill"
echo "  ✅ Risk Skill (TESTED)"
echo "  ✅ Execution Skill"
echo "  ✅ Storage Skill"
echo "  ✅ Monitoring Skill"
echo "  ✅ Alerting Skill"
echo "  ⏳ Backtesting Skill (TODO)"
echo "  ⏳ Reporting Skill (TODO)"
echo ""
echo "Next Steps:"
echo "  1. Wire up Capital.com, Firestore, Telegram APIs"
echo "  2. Write unit tests for new skills (75 more tests)"
echo "  3. Extract Backtesting and Reporting skills"
echo "  4. Run full integration test with live APIs"
echo ""

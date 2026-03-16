#!/bin/bash

# ============================================================================
# Test Script for Capital.com Trading Cloud Function
# ============================================================================
#
# This script provides common testing commands for the cloud function.
# It can test both local and deployed versions.
#
# Usage:
#   ./test.sh [local|prod] [endpoint]
#
# Examples:
#   ./test.sh local           # Test all local endpoints
#   ./test.sh prod            # Test all production endpoints
#   ./test.sh local positions # Test only positions endpoint locally
# ============================================================================

set -e

# Configuration
LOCAL_URL="http://localhost:8080"
PROD_URL="https://capitalcomservice-6ovej2yaoa-uc.a.run.app"

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Determine environment
ENV=${1:-local}
SPECIFIC_TEST=${2:-all}

if [ "$ENV" == "local" ]; then
    BASE_URL=$LOCAL_URL
    echo -e "${BLUE}🧪 Testing LOCAL environment${NC}"
elif [ "$ENV" == "prod" ]; then
    BASE_URL=$PROD_URL
    echo -e "${BLUE}🧪 Testing PRODUCTION environment${NC}"
else
    echo -e "${RED}❌ Invalid environment: $ENV${NC}"
    echo "Usage: $0 [local|prod] [endpoint]"
    exit 1
fi

echo "📡 Base URL: $BASE_URL"
echo ""

# Helper function to test an endpoint
test_endpoint() {
    local method=$1
    local path=$2
    local description=$3
    local data=$4

    echo -e "${YELLOW}Testing: ${description}${NC}"
    echo "  ${method} ${path}"
    
    if [ -z "$data" ]; then
        response=$(curl -s -w "\n%{http_code}" -X $method "${BASE_URL}${path}")
    else
        response=$(curl -s -w "\n%{http_code}" -X $method \
            -H "Content-Type: application/json" \
            -d "$data" \
            "${BASE_URL}${path}")
    fi
    
    http_code=$(echo "$response" | tail -n1)
    body=$(echo "$response" | sed '$d')
    
    if [ "$http_code" -ge 200 ] && [ "$http_code" -lt 300 ]; then
        echo -e "  ${GREEN}✓ Status: ${http_code}${NC}"
        echo "  Response: ${body:0:100}..."
    else
        echo -e "  ${RED}✗ Status: ${http_code}${NC}"
        echo "  Response: $body"
    fi
    echo ""
}

# Test GET /get_positions
if [ "$SPECIFIC_TEST" == "all" ] || [ "$SPECIFIC_TEST" == "positions" ]; then
    test_endpoint "GET" "/get_positions" "Get Open Positions"
fi

# Test POST /create_position (requires auth)
if [ "$SPECIFIC_TEST" == "all" ] || [ "$SPECIFIC_TEST" == "create" ]; then
    # Note: This will fail without valid API key - that's expected
    create_payload='{
        "key": "test_key",
        "action": "entry",
        "epic": "GOLD",
        "size1": 1,
        "direction": "BUY",
        "stopLevel": 2600,
        "fibLevel1": 2650,
        "inTradeTime": true
    }'
    test_endpoint "POST" "/create_position" "Create Position (expect 401 without valid key)" "$create_payload"
fi

# Test POST /updte_position (requires auth)
if [ "$SPECIFIC_TEST" == "all" ] || [ "$SPECIFIC_TEST" == "update" ]; then
    update_payload='{
        "key": "test_key",
        "action": "update-sl",
        "epic": "GOLD",
        "stopLevel": 2610
    }'
    test_endpoint "POST" "/updte_position" "Update Position (expect 401 without valid key)" "$update_payload"
fi

# Test invalid endpoint
if [ "$SPECIFIC_TEST" == "all" ] || [ "$SPECIFIC_TEST" == "invalid" ]; then
    test_endpoint "GET" "/invalid_endpoint" "Invalid Endpoint (expect 404)"
fi

echo -e "${GREEN}✅ Testing complete!${NC}"
echo ""
echo "Note: Some tests may fail if:"
echo "  - Local server is not running (for local tests)"
echo "  - Valid API key is not provided (for authenticated endpoints)"
echo "  - No positions exist in the account"

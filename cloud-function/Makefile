# ============================================================================
# Makefile for Capital.com Trading Cloud Function
# ============================================================================
#
# Common commands for development, testing, and deployment
#
# Usage:
#   make <target>
#
# Examples:
#   make install    - Install dependencies locally
#   make run        - Run function locally
#   make deploy     - Deploy to Google Cloud
#   make logs       - View recent logs
#   make status     - Check function status
# ============================================================================

.PHONY: help install run test deploy logs logs-tail status describe clean deploy-with-bot-monitoring show-new-endpoints test-bot-status test-bot-positions test-bot-logs

# Default target
help:
	@echo "Capital.com Trading Cloud Function - Available Commands"
	@echo "========================================================="
	@echo ""
	@echo "Development:"
	@echo "  make install      Install Python dependencies locally"
	@echo "  make run          Run function locally on port 8080"
	@echo "  make test         Test function locally"
	@echo ""
	@echo "Deployment:"
	@echo "  make deploy       Deploy/Update Capital.com function"
	@echo "  make deploy-fast  Deploy without confirmation prompt"
	@echo "  make deploy-with-bot-monitoring  Update function with bot monitoring endpoints"
	@echo ""
	@echo "Bot Monitoring - Testing (after deploy-with-bot-monitoring):"
	@echo "  make test-bot-status      Test /bot/status endpoint"
	@echo "  make test-bot-positions   Test /bot/positions endpoint"
	@echo "  make test-bot-logs        Test /logs/dates endpoint"
	@echo "  make show-new-endpoints   List all available endpoints"
	@echo ""
	@echo "Monitoring:"
	@echo "  make logs         View recent function logs (50 entries)"
	@echo "  make logs-tail    Follow logs in real-time"
	@echo "  make status       Check function status"
	@echo "  make describe     Show detailed function configuration"
	@echo ""
	@echo "Utilities:"
	@echo "  make clean        Clean Python cache files"
	@echo "  make env          Create .env from .env.example"
	@echo "  make urls         Show function URLs"
	@echo ""

# Development targets
install:
	@echo "📦 Installing dependencies..."
	pip install -r requirements.txt

run:
	@echo "🚀 Starting function locally on port 8080..."
	@echo "📡 Function will be available at: http://localhost:8080"
	@echo ""
	functions-framework --target=hello_http --port=8080 --debug

test:
	@echo "🧪 Testing function endpoints..."
	@echo ""
	@echo "Testing GET /get_positions..."
	@curl -s http://localhost:8080/get_positions | jq . || echo "Function not running or jq not installed"

# Deployment targets
deploy:
	@echo "🚀 Deploying function to Google Cloud..."
	./scripts/deploy.sh

deploy-fast:
	@echo "⚡ Fast deploying function (skipping confirmation)..."
	./scripts/deploy.sh --confirm-overwrite

# Monitoring targets
logs:
	@echo "📊 Fetching recent logs..."
	gcloud functions logs read capitalComService \
		--region us-central1 \
		--gen2 \
		--limit 50

logs-tail:
	@echo "📊 Following logs in real-time (Ctrl+C to stop)..."
	gcloud functions logs read capitalComService \
		--region us-central1 \
		--gen2 \
		--tail

status:
	@echo "🔍 Checking function status..."
	@gcloud functions describe capitalComService \
		--region us-central1 \
		--gen2 \
		--format="table(state,updateTime,serviceConfig.availableMemory,serviceConfig.timeoutSeconds)"

describe:
	@echo "📋 Function details:"
	gcloud functions describe capitalComService \
		--region us-central1 \
		--gen2

# Utility targets
clean:
	@echo "🧹 Cleaning Python cache files..."
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.pyo" -delete
	find . -type f -name "*.log" -delete
	@echo "✅ Cleaned!"

env:
	@if [ ! -f .env ]; then \
		echo "📝 Creating .env from .env.example..."; \
		cp .env.example .env; \
		echo "⚠️  Please edit .env and add your credentials"; \
	else \
		echo "⚠️  .env already exists"; \
	fi

urls:
	@echo "📡 Function URLs:"
	@echo ""
	@echo "Primary URL:"
	@gcloud functions describe capitalComService \
		--region us-central1 \
		--gen2 \
		--format="value(serviceConfig.uri)"
	@echo ""
	@echo "Alternative URLs:"
	@gcloud functions describe capitalComService \
		--region us-central1 \
		--gen2 \
		--format="value(serviceConfig.url)"

# Bot monitoring endpoints (adds to existing capitalComService function)
# Note: These endpoints are already added to functions/main.py
# Just redeploy the existing function to activate them
deploy-with-bot-monitoring:
	@echo "🚀 Updating capitalComService with Bot Monitoring endpoints..."
	@echo ""
	@echo "📦 Function: $(FUNCTION_NAME) (existing)"
	@echo "📍 Region: $(REGION)"
	@echo "🆕 New endpoints: /bot/status, /bot/positions, /bot/signals, /logs/get, /logs/dates"
	@echo "♻️  Existing endpoints: /get_positions, /create_position, /markets, /signals (preserved)"
	@echo ""
	@echo "⚠️  This will update your existing function that the frontend is using."
	@echo ""
	./scripts/deploy.sh --confirm-overwrite
	@echo ""
	@echo "✅ Function updated with bot monitoring endpoints!"
	@echo ""
	@$(MAKE) show-new-endpoints

show-new-endpoints:
	@echo "🆕 New Bot Monitoring Endpoints Available:"
	@echo ""
	@URL=$$(gcloud functions describe $(FUNCTION_NAME) --region $(REGION) --gen2 --format="value(serviceConfig.uri)" 2>/dev/null); \
	echo "Bot Status:     $$URL/bot/status"; \
	echo "Bot Positions:  $$URL/bot/positions?status=open"; \
	echo "Bot Signals:    $$URL/bot/signals?epic=GOLD&limit=20"; \
	echo "Bot Logs List:  $$URL/logs/dates"; \
	echo "Bot Logs Get:   $$URL/logs/get?date=2026-03-24"; \
	echo ""; \
	echo "📊 Existing Endpoints (unchanged):"; \
	echo "Positions:      $$URL/get_positions"; \
	echo "Signals:        $$URL/signals?epic=GOLD"; \
	echo "Markets:        $$URL/markets"

test-bot-status:
	@echo "🔍 Testing bot status endpoint..."
	@URL=$$(gcloud functions describe $(FUNCTION_NAME) --region $(REGION) --gen2 --format="value(serviceConfig.uri)" 2>/dev/null); \
	if [ -n "$$URL" ]; then \
		curl -s "$$URL/bot/status" | jq . || curl "$$URL/bot/status"; \
	else \
		echo "❌ Function not deployed"; \
	fi

test-bot-positions:
	@echo "🔍 Testing bot positions endpoint..."
	@URL=$$(gcloud functions describe $(FUNCTION_NAME) --region $(REGION) --gen2 --format="value(serviceConfig.uri)" 2>/dev/null); \
	if [ -n "$$URL" ]; then \
		curl -s "$$URL/bot/positions?status=open" | jq . || curl "$$URL/bot/positions?status=open"; \
	else \
		echo "❌ Function not deployed"; \
	fi

test-bot-logs:
	@echo "🔍 Testing bot logs endpoint..."
	@URL=$$(gcloud functions describe $(FUNCTION_NAME) --region $(REGION) --gen2 --format="value(serviceConfig.uri)" 2>/dev/null); \
	if [ -n "$$URL" ]; then \
		curl -s "$$URL/logs/dates" | jq . || curl "$$URL/logs/dates"; \
	else \
		echo "❌ Function not deployed"; \
	fi

# Project configuration
PROJECT_ID = double-venture-442318-k8
FUNCTION_NAME = capitalComService
REGION = us-central1

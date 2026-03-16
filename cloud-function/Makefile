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

.PHONY: help install run test deploy logs logs-tail status describe clean

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
	@echo "  make deploy       Deploy function to Google Cloud"
	@echo "  make deploy-fast  Deploy without confirmation prompt"
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

# Project configuration
PROJECT_ID = double-venture-442318-k8
FUNCTION_NAME = capitalComService
REGION = us-central1

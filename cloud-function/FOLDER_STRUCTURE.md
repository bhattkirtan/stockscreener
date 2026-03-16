# 📁 Cloud Function Folder Structure

## Overview

This document describes the organized structure of the cloud-function directory after reorganization (March 2026). The structure separates concerns into logical directories for better maintainability.

## Directory Structure

```
cloud-function/
├── README.md                      # Main project documentation
├── requirements.txt               # Python dependencies for deployment
├── requirements-functions.txt     # Minimal dependencies for Cloud Functions
├── .env                          # Local environment variables
├── .env.example                  # Environment template
├── .dockerignore                 # Docker ignore patterns
├── .gcloudignore                 # GCloud deployment ignore patterns
├── Makefile                      # Build and deployment shortcuts
│
├── functions/                    # 🔥 Cloud Function Entry Points
│   ├── main.py                   # Capital.com service + scheduler control
│   ├── main_api.py              # Optimization API entry point
│   ├── main_data_updater.py     # Data updater entry point
│   └── main_readonly.py         # Read-only API entry point
│
├── src/                          # 📦 Core Application Code
│   ├── api_functions.py          # API function implementations
│   ├── api_functions_enhanced.py # Enhanced optimization API (20+ parameters)
│   ├── data_updater.py          # Market data updater with scheduler control
│   ├── optimizer_worker.py      # Optimization worker for Cloud Run
│   ├── api_server.py            # API server implementation
│   │
│   ├── api/                     # API clients and services
│   │   ├── capital_client.py    # Capital.com API client
│   │   └── firestore_client.py  # Firestore database client
│   │
│   ├── core/                    # Core business logic
│   │   └── ...
│   │
│   ├── data/                    # Data processing modules
│   │   └── ...
│   │
│   ├── optimization/            # Optimization algorithms
│   │   └── ...
│   │
│   └── runners/                 # Strategy runners
│       └── ...
│
├── tests/                        # 🧪 Test Files
│   ├── test_api.py              # API tests
│   ├── test_api_client.py       # API client tests
│   ├── test_full_optimizer.py   # Full optimization tests
│   ├── test_optimizer.py        # Optimizer unit tests
│   ├── test_parallel_fix.py     # Parallel processing tests
│   ├── test_parallel_optimizer.py # Parallel optimizer tests
│   ├── test_pip_value.py        # Pip value calculation tests
│   └── PARALLEL_READY.py        # Parallel processing validation
│
├── scripts/                      # 🚀 Deployment & Utility Scripts
│   ├── config.sh                # Deployment configuration
│   ├── deploy-all.sh            # Deploy all services
│   ├── deploy-cloud-run.sh      # Deploy worker to Cloud Run
│   ├── deploy-data-updater.sh   # Deploy data updater function
│   ├── deploy-hybrid.sh         # Deploy hybrid architecture
│   ├── deploy-scheduler-control.sh # Deploy scheduler control API
│   ├── deploy-production.sh     # Production deployment
│   ├── check-status.sh          # Check deployment status
│   ├── setup_local_env.py       # Local environment setup
│   ├── setup_credentials.py     # Credential setup
│   ├── analyze_results.py       # Results analysis utility
│   └── benchmark_parallel.py    # Parallel processing benchmarks
│
├── docker/                       # 🐳 Docker & Build Configuration
│   ├── Dockerfile               # Main application Dockerfile
│   ├── Dockerfile.worker        # Worker service Dockerfile
│   ├── cloudbuild.yaml          # Google Cloud Build configuration
│   └── service.yaml             # Cloud Run service configuration
│
├── docs/                         # 📚 Documentation
│   ├── API_CUSTOMIZATION_GUIDE.md      # API parameter customization guide
│   ├── API_GUIDE.md                    # General API guide
│   ├── API_README.md                   # API overview
│   ├── DATA_UPDATE_ARCHITECTURE.md     # Data update system architecture
│   ├── DEPLOYMENT.md                   # Deployment instructions
│   ├── DEPLOYMENT_COMPLETE.md          # Complete deployment reference
│   ├── DEPLOYMENT_QUICKSTART.md        # Quick deployment guide
│   ├── FRONTEND_INTEGRATION.md         # Frontend integration guide
│   ├── HYBRID_ARCHITECTURE.md          # Hybrid architecture documentation
│   ├── LOVABLE_INTEGRATION.md          # Lovable platform integration
│   ├── OPTIMIZATION_IMPROVEMENTS_V2.md # Optimization improvements log
│   ├── PIP_VALUE_OPTIMIZATION_SUMMARY.md # Pip value optimization details
│   ├── REORGANIZATION_COMPLETE.md      # Previous reorganization notes
│   ├── UI_CONTROL_API.md              # UI control API reference
│   └── UI_INTEGRATION_GUIDE.md        # UI integration patterns
│
├── data/                         # 💾 Data Files
│   └── ...                       # CSV files, market data
│
└── static/                       # 🎨 Static Assets
    └── ...                       # Frontend assets, templates
```

## Key Directories Explained

### `functions/` - Cloud Function Entry Points
Contains Python modules that serve as entry points for Google Cloud Functions. Each file exports functions decorated with `@functions_framework.http`.

**Key Files:**
- `main.py` - Capital.com trading service + scheduler control endpoints
- `main_api.py` - Routes requests to enhanced optimization API
- `main_data_updater.py` - Scheduled market data updates
- `main_readonly.py` - Read-only data access endpoints

**Import Pattern:**
```python
# Entry points import from src/
from src.api_functions_enhanced import optimize_api
from src.data_updater import update_market_data
```

### `src/` - Core Application Code
Contains all business logic, API implementations, data processing, and optimization algorithms. This is the heart of the application.

**Import Pattern:**
```python
# Code in src/ can import from each other
from src.api.capital_client import CapitalClient
from src.optimization.strategy import optimize_parameters
```

### `tests/` - Test Suite
All test files consolidated here for easy test discovery and execution.

**Running Tests:**
```bash
# From cloud-function root
python -m pytest tests/

# Specific test file
python -m pytest tests/test_api.py

# With coverage
python -m pytest tests/ --cov=src --cov-report=html
```

### `scripts/` - Deployment & Utilities
Deployment scripts, setup utilities, and analysis tools.

**Usage:**
```bash
# Run from cloud-function root directory
./scripts/deploy-data-updater.sh
./scripts/deploy-scheduler-control.sh
./scripts/deploy-all.sh

# Check deployment status
./scripts/check-status.sh
```

**Important:** Scripts are designed to be run from the `cloud-function/` root directory, not from within `scripts/`.

### `docker/` - Docker Configuration
Docker and Cloud Build configuration files for containerized deployments.

**Files:**
- `Dockerfile` - Main application container
- `Dockerfile.worker` - Optimization worker container
- `cloudbuild.yaml` - Google Cloud Build steps
- `service.yaml` - Cloud Run service configuration

### `docs/` - Documentation
All markdown documentation files organized in one place.

**Key Documents:**
- `DEPLOYMENT_COMPLETE.md` - Complete deployment reference with all URLs
- `UI_CONTROL_API.md` - API reference for UI integration
- `API_CUSTOMIZATION_GUIDE.md` - 20+ optimization parameters explained
- `HYBRID_ARCHITECTURE.md` - System architecture overview

## Deployment Guide

### Prerequisites
```bash
# Ensure you're in the cloud-function directory
cd /Users/kirtanbhatt/code/stockScreener/cloud-function

# Set up GCP configuration
gcloud config set project double-venture-442318-k8
gcloud config set compute/region us-central1
```

### Deploy Services

**1. Data Updater (Scheduled Market Data Updates)**
```bash
./scripts/deploy-data-updater.sh
```

**2. Scheduler Control (Enable/Disable Data Sync from UI)**
```bash
./scripts/deploy-scheduler-control.sh
```

**3. Optimization API (Enhanced with 20+ Parameters)**
```bash
# Automatically deployed with hybrid architecture
./scripts/deploy-hybrid.sh
```

**4. Deploy Everything**
```bash
./scripts/deploy-all.sh
```

## Import Path Updates

After reorganization, all imports were updated:

**Before:**
```python
# In main.py
from data_updater import update_market_data
from api_functions_enhanced import optimize_api
```

**After:**
```python
# In functions/main.py
from src.data_updater import update_market_data
from src.api_functions_enhanced import optimize_api
```

## Benefits of New Structure

✅ **Clear Separation of Concerns**
- Entry points (`functions/`) separate from business logic (`src/`)
- Tests isolated in dedicated directory
- Scripts and utilities organized together

✅ **Better Maintainability**
- Easy to locate files by purpose
- Reduced clutter in root directory
- Logical grouping of related files

✅ **Improved Testability**
- All tests in one place
- Clear import paths
- Easy test discovery

✅ **Deployment Clarity**
- All deployment scripts together
- Docker files isolated
- Configuration centralized

✅ **Documentation Organization**
- All docs in one searchable location
- Easy to browse and maintain
- No documentation scattered in code directories

## Migration Checklist

If you're updating code after this reorganization:

- [ ] Update imports to use `src.` prefix for core modules
- [ ] Run scripts from `cloud-function/` root, not from `scripts/`
- [ ] Reference Docker files from `docker/` directory
- [ ] Place new tests in `tests/` directory
- [ ] Add new documentation to `docs/` directory
- [ ] Create new entry points in `functions/` directory

## Quick Reference

| Task | Command |
|------|---------|
| Deploy all services | `./scripts/deploy-all.sh` |
| Deploy data updater | `./scripts/deploy-data-updater.sh` |
| Deploy scheduler control | `./scripts/deploy-scheduler-control.sh` |
| Check deployment status | `./scripts/check-status.sh` |
| Run tests | `python -m pytest tests/` |
| Build Docker image | `cd docker && docker build -f Dockerfile.worker ..` |

## Deployed Services

### Production URLs
- **Optimization API**: https://optimize-api-6ovej2yaoa-uc.a.run.app
- **Optimizer Worker**: https://optimizer-worker-6ovej2yaoa-uc.a.run.app
- **Data Updater**: https://data-updater-6ovej2yaoa-uc.a.run.app
- **Scheduler Control**: https://scheduler-control-6ovej2yaoa-uc.a.run.app

### Health Checks
```bash
# Check all services
echo "=== SYSTEM STATUS ===" && \
curl -s https://optimize-api-6ovej2yaoa-uc.a.run.app/health && echo "" && \
curl -s https://optimizer-worker-6ovej2yaoa-uc.a.run.app/health && echo "" && \
curl -s https://scheduler-control-6ovej2yaoa-uc.a.run.app/scheduler/status && echo ""
```

## File Counts

- **Functions**: 4 entry point files
- **Source Code**: 5+ core modules + subdirectories
- **Tests**: 8 test files
- **Scripts**: 14 deployment and utility scripts
- **Docker**: 4 configuration files
- **Documentation**: 15 comprehensive guides

## Questions?

- Architecture questions → See `docs/HYBRID_ARCHITECTURE.md`
- API usage → See `docs/UI_CONTROL_API.md`
- Deployment issues → See `docs/DEPLOYMENT_COMPLETE.md`
- Optimization parameters → See `docs/API_CUSTOMIZATION_GUIDE.md`

---

**Last Updated**: March 5, 2026  
**Reorganization Date**: March 5, 2026

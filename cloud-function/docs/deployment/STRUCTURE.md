# Cloud Function Service Folder Structure

This document describes the complete organization of the Capital.com Trading Cloud Function service.

## 📁 Folder Structure

```
cloud-function/
├── main.py                 # Main Cloud Function entry point (hello_http)
├── requirements.txt       # Python dependencies for deployment
├── Makefile               # Common commands (install, run, deploy, logs)
├── README.md              # Comprehensive documentation
│
├── src/                   # Application source code
│   ├── __init__.py        # Python package marker
│   └── firestore_client.py # Firestore database client wrapper
│
├── scripts/               # Deployment and testing scripts
│   ├── deploy.sh          # Deployment script with production config
│   ├── test.sh            # Testing script for local/production endpoints
│   └── config.sh          # Deployment configuration reference
│
├── docs/                  # Additional documentation
│   ├── STRUCTURE.md       # This file - folder structure explanation
│   └── QUICKSTART.md      # Quick start guide
│
├── .env.example           # Environment variables template for local dev
├── .gcloudignore          # Files to exclude from deployment
├── service.yaml           # Knative/Cloud Run service configuration reference
│
└── [.env]                 # Local environment file (git-ignored, create from .env.example)
```

## 📄 File Descriptions

### Core Application Files

#### `main.py`
- **Purpose**: Main entry point for the Cloud Function
- **Entry Point**: `hello_http` function
- **Responsibilities**:
  - HTTP request routing and handling
  - Capital.com API authentication and session management
  - Position management (create, update, close)
  - Token caching with TTL (55 minutes)
  - Error handling and logging
- **Dependencies**: 
  - functions-framework
  - Flask
  - google-cloud-logging
  - requests
  - cachetools
  - src.firestore_client module

#### `requirements.txt`
- **Purpose**: Python package dependencies
- **Packages**:
  - `functions-framework==3.*` - Cloud Functions runtime
  - `Flask` - HTTP framework
  - `requests` - HTTP client for Capital.com API
  - `google-cloud-firestore` - Firestore database client
  - `google-cloud-logging` - Cloud Logging integration
  - `python-dotenv` - Environment variable management (local dev)
  - `cachetools==5.5.2` - TTL caching for API tokens

### Source Code (src/)

#### `src/__init__.py`
- **Purpose**: Python package marker
- **Content**: Makes the src directory importable as a Python package
- **Note**: Can be used to expose common imports or package metadata

#### `src/firestore_client.py`
- **Purpose**: Firestore database client wrapper
- **Location**: `src/firestore_client.py`
- **Class**: `FirestoreDB`
- **Responsibilities**:
  - Document CRUD operations (add, get, update, set, delete)
  - Collection management
  - Data persistence for trading positions
- **Dependencies**: google-cloud-firestore
- **Usage**: Imported in main.py as `from src.firestore_client import FirestoreDB`

### Deployment Files

#### `scripts/deploy.sh`
- **Purpose**: Automated deployment script
- **Location**: `scripts/deploy.sh`
- **Features**:
  - Production-ready configuration
  - Confirmation prompts
  - Options for skip confirmation and traffic migration
  - Post-deployment URL and logging information
- **Usage**: 
  ```bash
  ./scripts/deploy.sh                    # Deploy with confirmation
  ./scripts/deploy.sh --confirm-overwrite # Skip confirmation
  ```

#### `scripts/config.sh`
- **Purpose**: Central deployment configuration reference
- **Location**: `scripts/config.sh`
- **Contains**:
  - Project and function identifiers
  - Resource allocation settings
  - Service account information
  - Secret Manager configuration
  - URLs and endpoints
  - Required APIs and IAM roles
- **Note**: For documentation purposes; not executed directly

#### `service.yaml`
- **Purpose**: Documents the Knative Service configuration
- **Contains**:
  - Complete service specification
  - Container configuration
  - Resource limits
  - Environment variables and secrets
  - Health check configuration
  - Traffic routing rules
- **Note**: Reference document; actual deployment uses gcloud CLI

### Testing & Development Files

#### `test.sh`
- **Purpose**: Automated endpoint testing
- **Features**:
  - Test local or production environments
  - Test specific or all endpoints
  - Color-coded output
  - HTTP status validation
- **Usage**:
  ```bash
  ./test.sh local           # Test all local endpoints
  ./test.sh prod            # Test all production endpoints
  ./test.sh local positions # Test specific endpoint
  ```

#### `Makefile`
- **Purpose**: Common development and operations tasks
- **Targets**:
  - `make install` - Install dependencies
  - `make run` - Run function locally
  - `make deploy` - Deploy to cloud
  - `make logs` - View function logs
  - `make status` - Check function status
  - `make clean` - Clean cache files
- **Usage**: Run `make help` for full list of commands

#### `.env.example`
- **Purpose**: Template for local environment variables
- **Contains**: Structure for API credentials
- **Usage**: Copy to `.env` and fill in actual credentials
- **Note**: Never commit `.env` to version control

### Configuration Files

#### `.gcloudignore`
- **Purpose**: Exclude files from deployment
- **Excludes**:
  - Python cache (`__pycache__`, `*.pyc`)
  - Virtual environments (`venv/`, `env/`)
  - IDE files (`.vscode/`, `.idea/`)
  - Environment files (`.env`, `*.env`)
  - Documentation (`*.md`, `docs/`)
  - Deployment scripts (`*.sh`)
  - Test files

### Documentation Files

#### `README.md`
- **Purpose**: Comprehensive project documentation
- **Sections**:
  - Architecture overview
  - Prerequisites
  - Secret configuration
  - Deployment instructions
  - API endpoint documentation
  - Local development setup
  - Troubleshooting guide
  - Configuration reference

#### `STRUCTURE.md` (this file)
- **Purpose**: Explain folder organization and file purposes
- **Content**: Detailed description of each file and its role

## 🔄 Typical Workflows

### Initial Setup

```bash
# 1. Navigate to cloud-function folder
cd cloud-function

# 2. Create local environment file
cp .env.example .env
# Edit .env with your credentials

# 3. Install dependencies (for local development)
make install

# 4. Run locally
make run

# 5. Test locally (in another terminal)
./test.sh local
```

### Deployment to Production

```bash
# Option 1: Using deployment script
./deploy.sh

# Option 2: Using Makefile
make deploy

# Option 3: Fast deploy (skip confirmation)
make deploy-fast
```

### Monitoring & Debugging

```bash
# View recent logs
make logs

# Follow logs in real-time
make logs-tail

# Check function status
make status

# Get detailed configuration
make describe

# Test production endpoints
./test.sh prod
```

### Making Changes

```bash
# 1. Edit code (main.py or src/firestore_client.py)

# 2. Test locally
make run
./test.sh local

# 3. Deploy changes
make deploy

# 4. Test production
./test.sh prod

# 5. Monitor logs
make logs-tail
```

## 🔐 Security Notes

### Secret Management
- **Local Development**: Use `.env` file (never commit)
- **Production**: Use Google Cloud Secret Manager
- **Secret Name**: `capitalService`
- **Secret Format**: JSON with apikey, username, password, capkey

### Files to NEVER Commit
- `.env` - Contains actual credentials
- `*.log` - May contain sensitive data
- `__pycache__/` - Compiled Python files
- Any files with real API keys or passwords

## 🏗️ Architecture Overview

```
┌─────────────────┐
│  TradingView    │
│   Webhook       │
└────────┬────────┘
         │ POST /create_position
         ▼
┌─────────────────────────────────┐
│  Google Cloud Function (Gen2)   │
│  ┌───────────────────────────┐  │
│  │   main.py (hello_http)    │  │
│  │   - Route requests        │  │
│  │   - Manage auth tokens    │  │
│  │   - Cache with TTL        │  │
│  └─────────┬─────────────────┘  │
│            │                     │
│  ┌─────────▼─────────────────┐  │
│  │   src/firestore_client.py │  │
│  │   - Firestore operations  │  │
│  └───────────────────────────┘  │
└────────┬───────────┬────────────┘
         │           │
         │           ▼
         │    ┌──────────────┐
         │    │  Firestore   │
         │    │  Database    │
         │    └──────────────┘
         │
         ▼
┌─────────────────┐
│  Capital.com    │
│  Trading API    │
└─────────────────┘
```

## 📊 Service Configuration Summary

| Parameter | Value |
|-----------|-------|
| **Function Name** | capitalComService |
| **Runtime** | Python 3.12 |
| **Region** | us-central1 |
| **Memory** | 256Mi |
| **CPU** | 1 vCPU |
| **Timeout** | 60s |
| **Max Instances** | 100 |
| **Concurrency** | 1 request/container |
| **Project** | double-venture-442318-k8 |

## 🔗 Quick Links

- **Primary URL**: https://us-central1-double-venture-442318-k8.cloudfunctions.net/capitalComService
- **Function URL**: https://us-central1-double-venture-442318-k8.cloudfunctions.net/capitalComService
- **GCP Console**: https://console.cloud.google.com/functions
- **Secret Manager**: https://console.cloud.google.com/security/secret-manager
- **Firestore**: https://console.cloud.google.com/firestore
- **Logs**: https://console.cloud.google.com/logs

## 🛠️ Maintenance Tasks

### Regular Maintenance
- Review logs for errors: `make logs`
- Monitor function status: `make status`
- Check API rate limits in logs
- Review Firestore usage

### Updates
- Update Python packages: Edit `requirements.txt` and redeploy
- Update configuration: Edit `scripts/config.sh` for reference, then update `scripts/deploy.sh`
- Change secrets: Update in Secret Manager (no redeployment needed)
- Modify code: Edit `main.py` or `src/firestore_client.py`, then `make deploy`

### Troubleshooting
1. Check function logs: `make logs-tail`
2. Verify secret access: Check IAM permissions
3. Test endpoints: `./test.sh prod`
4. Check service status: `make status`
5. Review configuration: `make describe`

---

**Last Updated**: March 4, 2026  
**Maintained By**: Cloud Function Team  
**Version**: 1.0.0

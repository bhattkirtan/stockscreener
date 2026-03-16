# Capital.com Trading Service - Google Cloud Function

A production-ready Google Cloud Function (Gen2) that provides trading services for Capital.com API integration with Google Firestore persistence.

## 🏗️ Architecture

This service acts as a **secure backend proxy** for Capital.com API:
- Handles HTTP trading requests (create, update, close positions)
- Integrates with Capital.com demo API
- Stores position data in Google Cloud Firestore
- Uses Secret Manager for secure credential storage
- Implements TTL caching for API tokens and encryption keys
- Provides market data APIs (current prices, historical data, top movers)
- Handles TradingView webhook alerts for automated trading

### 🔒 Security Model: Backend Proxy Pattern

```
┌─────────────┐         ┌─────────────┐         ┌──────────────┐
│   Frontend  │  HTTPS  │   Backend   │  HTTPS  │ Capital.com  │
│  (Lovable)  │────────►│   (Proxy)   │────────►│     API      │
│             │         │ GCP Function│         │              │
└─────────────┘         └─────────────┘         └──────────────┘
```

**⚠️ CRITICAL:** Never call Capital.com API directly from frontend. Always use this backend proxy to:
- Keep API credentials secure (stored in Secret Manager)
- Prevent unauthorized access to trading account
- Enable audit logging and rate limiting
- Add business logic and validation

## 📚 Documentation

- **[Frontend Integration Guide](docs/LOVABLE_INTEGRATION.md)** - Complete guide for building frontend with React/TypeScript
- **[API Reference](docs/API_REFERENCE.md)** - Comprehensive API documentation with examples
- **[OpenAPI Specification](docs/openapi.yaml)** - Swagger/OpenAPI 3.0 spec
- **[TradingView Integration](docs/strategy-with-webhooks.pine)** - Pine Script for automated trading

## 📋 Prerequisites

- Google Cloud SDK (`gcloud` CLI)
- Python 3.12
- Google Cloud Project with:
  - Cloud Functions API enabled
  - Firestore API enabled
  - Secret Manager API enabled
  - Cloud Logging API enabled

## 🔐 Secret Configuration

The function uses Google Secret Manager for API credentials. Create a secret named `capitalService` with the following JSON structure:

Copy the example file and fill in your credentials:

```bash
cp .env.example .env
```

Edit `.env` and add your API credentials in JSON format:

```
apicredentials={"apikey":"your_api_key","username":"your_username","password":"your_password","capkey":"your_capital_api_key"}
```

## Deployment

### Deploy to Google Cloud Functions

```bash
gcloud functions deploy capital-trading \
  --runtime python39 \
  --trigger-http \
  --allow-unauthenticated \
  --entry-point hello_http \

```json
{
  "apikey": "your-tradingview-api-key",
  "username": "your-capital-username",
  "password": "your-capital-password",
  "capkey": "your-capital-api-key"
}
```

### Create the secret:

```bash
# Create the secret
echo '{
  "apikey": "your-api-key",
  "username": "your-username",
  "password": "your-password",
  "capkey": "your-capital-key"
}' | gcloud secrets create capitalService --data-file=-

# Grant access to the compute service account
gcloud secrets add-iam-policy-binding capitalService \
    --member="serviceAccount:361802071308-compute@developer.gserviceaccount.com" \
    --role="roles/secretmanager.secretAccessor"
```

## 🚀 Deployment

### Quick Deploy

```bash
chmod +x scripts/deploy.sh
./scripts/deploy.sh
```

### Deploy with Options

```bash
# Skip confirmation prompt
./scripts/deploy.sh --confirm-overwrite

# Deploy with traffic migration
./scripts/deploy.sh --update-traffic
```

### Manual Deployment

```bash
gcloud functions deploy capitalComService \
    --gen2 \
    --runtime python312 \
    --trigger-http \
    --entry-point hello_http \
    --region us-central1 \
    --memory 256Mi \
    --cpu 1 \
    --timeout 60s \
    --max-instances 100 \
    --concurrency 1 \
    --service-account 361802071308-compute@developer.gserviceaccount.com \
    --set-secrets "apicredentials=capitalService:latest" \
    --allow-unauthenticated
```

## 📚 API Endpoints

### Get Open Positions
```http
GET /get_positions
```

### Create Position
```http
POST /create_position
Content-Type: application/json

{
  "key": "your-api-key",
  "action": "entry",
  "epic": "GOLD",
  "size1": 1,
  "direction": "BUY",
  "stopLevel": 2600,
  "fibLevel1": 2650,
  "inTradeTime": true
}
```

**Actions:**
- `entry` - Create new position
- `update-sl` - Update stop loss
- `exit` - Close position

### Update Position
```http
POST /updte_position
Content-Type: application/json

{
  "key": "your-api-key",
  "action": "update-sl",
  "epic": "GOLD",
  "stopLevel": 2610
}
```

### Close Position
```http
DELETE /close_position/{dealId}
```

## 📊 Current Configuration

| Parameter | Value |
|-----------|-------|
| **Function Name** | capitalComService |
| **Runtime** | Python 3.12 |
| **Region** | us-central1 |
| **Memory** | 256Mi |
| **CPU** | 1 |
| **Timeout** | 60s |
| **Max Instances** | 100 |
| **Concurrency** | 1 |
| **Project** | double-venture-442318-k8 |

## 🔧 Local Development

### Setup

```bash
# Install dependencies
pip install -r requirements.txt

# Create .env file (for local testing)
cp .env.example .env
# Edit .env with your credentials
```

### Run Locally

```bash
# Using Functions Framework
functions-framework --target=hello_http --port=8080
```

### Test Endpoints

```bash
# Get positions
curl http://localhost:8080/get_positions

# Create position
curl -X POST http://localhost:8080/create_position \
  -H "Content-Type: application/json" \
  -d '{
    "key": "your-api-key",
    "action": "entry",
    "epic": "GOLD",
    "size1": 1,
    "direction": "BUY",
    "stopLevel": 2600,
    "fibLevel1": 2650,
    "inTradeTime": true
  }'
```

## 📖 Additional Documentation

- [Quick Start Guide](docs/QUICKSTART.md) - Get up and running in 5 minutes
- [Folder Structure](docs/STRUCTURE.md) - Detailed explanation of the project organization
- [Deployment Config](scripts/config.sh) - Reference configuration parameters
- [Service Spec](service.yaml) - Knative service configuration

## 📝 Files

```
cloud-function/
├── main.py                 # Main function entry point
├── requirements.txt       # Python dependencies
├── Makefile               # Common commands
│
├── src/                   # Application source code
│   ├── __init__.py        # Python package marker
│   └── firestore_client.py # Firestore database client
│
├── scripts/               # Deployment & test scripts
│   ├── deploy.sh          # Deployment script
│   ├── test.sh            # Testing script
│   └── config.sh          # Configuration reference
│
├── docs/                  # Additional documentation
│   ├── QUICKSTART.md      # Quick start guide
│   └── STRUCTURE.md       # Folder structure guide
│
├── .gcloudignore          # Files to exclude from deployment
├── .env.example           # Example environment file
├── service.yaml           # Service configuration reference
└── README.md              # This file
```

## 🐛 Troubleshooting

### View Logs

```bash
# Recent logs
gcloud functions logs read capitalComService --region us-central1 --gen2 --limit 50

# Follow logs in real-time
gcloud functions logs read capitalComService --region us-central1 --gen2 --tail
```

### Check Function Status

```bash
gcloud functions describe capitalComService --region us-central1 --gen2
```

### Common Issues

1. **Rate Limiting (429)**
   - The function implements TTL caching to reduce API calls
   - Cache TTL: 55 minutes for tokens and encryption keys

2. **Authentication Errors**
   - Verify Secret Manager permissions
   - Check secret content format

3. **Firestore Errors**
   - Ensure Firestore API is enabled
   - Verify service account has Firestore permissions

## 🔗 URLs

- **Function URL**: https://capitalcomservice-6ovej2yaoa-uc.a.run.app
- **Alt URL**: https://us-central1-double-venture-442318-k8.cloudfunctions.net/capitalComService
- **Capital.com API**: https://demo-api-capital.backend-capital.com

## 📄 License

Private project - All rights reserved


# Quick Start Guide - Capital.com Trading Service

Get up and running with the Capital.com Trading Cloud Function in minutes.

## ⚡ 5-Minute Setup

### Prerequisites Check
```bash
# Verify you have required tools
gcloud --version     # Google Cloud SDK
python3 --version    # Python 3.12+
```

### 1. Set Up Local Environment (Optional for Testing)

```bash
# Navigate to the service folder
cd cloud-function

# Create environment file from template
cp .env.example .env

# Edit .env with your credentials
nano .env  # or use your preferred editor
```

Add your credentials to `.env`:
```json
apicredentials={"apikey":"your_tv_api_key","username":"your_capital_username","password":"your_capital_password","capkey":"your_capital_api_key"}
```

### 2. Test Locally (Optional)

```bash
# Install dependencies
make install

# Run the function locally
make run

# In another terminal, test it
./test.sh local
```

### 3. Configure Production Secret

```bash
# Set your GCP project
gcloud config set project double-venture-442318-k8

# Create or update the secret
echo '{
  "apikey": "your_tv_api_key",
  "username": "your_capital_username",
  "password": "your_capital_password",
  "capkey": "your_capital_api_key"
}' | gcloud secrets create capitalService --data-file=-

# Or update existing secret
echo '{
  "apikey": "your_tv_api_key",
  "username": "your_capital_username",
  "password": "your_capital_password",
  "capkey": "your_capital_api_key"
}' | gcloud secrets versions add capitalService --data-file=-
```

### 4. Deploy to Production

```bash
# Deploy using the automated script
./scripts/deploy.sh

# Or use make
make deploy
```

### 5. Verify Deployment

```bash
# Check function status
make status

# Test production endpoints
./test.sh prod

# View logs
make logs
```

## 🎯 Common Commands

```bash
# Development
make install      # Install dependencies
make run          # Run locally
make test         # Test local endpoints

# Deployment
make deploy       # Deploy to cloud
make deploy-fast  # Deploy without confirmation

# Monitoring
make logs         # View recent logs
make logs-tail    # Follow logs real-time
make status       # Check function status

# Utilities
make clean        # Clean cache files
make urls         # Show function URLs
```

## 📡 Your Function URLs

After deployment, your function will be available at:

- **Primary**: https://us-central1-double-venture-442318-k8.cloudfunctions.net/capitalComService
- **Alt URL**: https://us-central1-double-venture-442318-k8.cloudfunctions.net/capitalComService

## 🔍 Testing Endpoints

### Get Open Positions
```bash
curl https://us-central1-double-venture-442318-k8.cloudfunctions.net/capitalComService/get_positions
```

### Create Position
```bash
curl -X POST https://us-central1-double-venture-442318-k8.cloudfunctions.net/capitalComService/create_position \
  -H "Content-Type: application/json" \
  -d '{
    "key": "your_api_key",
    "action": "entry",
    "epic": "GOLD",
    "size1": 1,
    "direction": "BUY",
    "stopLevel": 2600,
    "fibLevel1": 2650,
    "inTradeTime": true
  }'
```

## 🆘 Quick Troubleshooting

### Function not deploying?
```bash
# Check if required APIs are enabled
gcloud services list --enabled | grep -E "cloudfunctions|run|secretmanager"

# Enable if needed
gcloud services enable cloudfunctions.googleapis.com run.googleapis.com secretmanager.googleapis.com
```

### Can't access secrets?
```bash
# Grant service account access to secret
gcloud secrets add-iam-policy-binding capitalService \
    --member="serviceAccount:361802071308-compute@developer.gserviceaccount.com" \
    --role="roles/secretmanager.secretAccessor"
```

### Function returns errors?
```bash
# View detailed logs
make logs-tail

# Check function configuration
make describe
```

## 📚 Next Steps

- Read the full [README.md](../README.md) for detailed documentation
- Review [STRUCTURE.md](STRUCTURE.md) to understand the folder organization
- Check [service.yaml](../service.yaml) for current deployment configuration
- Review [config.sh](../scripts/config.sh) for all configuration parameters

## 🔗 Useful Links

- [Google Cloud Functions Documentation](https://cloud.google.com/functions/docs)
- [Capital.com API Documentation](https://capital.com/api-development-guide)
- [GCP Console - Functions](https://console.cloud.google.com/functions)
- [GCP Console - Secret Manager](https://console.cloud.google.com/security/secret-manager)
- [GCP Console - Logs](https://console.cloud.google.com/logs)

---

**Need Help?** Run `make help` for a list of all available commands.

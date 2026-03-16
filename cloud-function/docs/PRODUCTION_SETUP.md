# Production Deployment Guide - Live Trading API

> ⚠️ **WARNING**: This guide sets up a service with **LIVE trading API** where real money is at risk.

---

## Prerequisites

### 1. Live trading Account
- [ ] Active live trading account with Capital.com
- [ ] API access enabled for your live account
- [ ] Live API credentials (X-CAP-API-KEY)
- [ ] Sufficient funds and risk management in place

### 2. Test Thoroughly on Demo First
- [ ] All features tested on demo environment
- [ ] TradingView webhooks tested and validated
- [ ] Position management verified
- [ ] Error handling tested
- [ ] Stop loss and take profit logic validated

---

## Step 1: Get Live API Credentials

1. **Log in to trading Live Account**
   - Go to: https://capital.com/trading/platform/
   - Use your live trading credentials

2. **Enable API Access**
   - Navigate to Account Settings → API
   - Generate API keys for live account
   - **Save these credentials securely!**

You'll need:
- **API Key** (X-CAP-API-KEY): Your live API key
- **Username**: Your trading email
- **Password**: Your trading password  
- **Identifier**: Additional API identifier

---

## Step 2: Create Production Secret in GCP

### Option A: Using Google Cloud Console (Recommended)

1. Go to Secret Manager:
   ```
   https://console.cloud.google.com/security/secret-manager?project=double-venture-442318-k8
   ```

2. Click **"CREATE SECRET"**

3. Configure the secret:
   - **Name**: `marketServiceCredentials`
   - **Secret value**: Paste this JSON (with YOUR live credentials):
   ```json
   {
     "apikey": "YOUR_LIVE_API_KEY",
     "username": "your-email@example.com",
     "password": "YOUR_LIVE_PASSWORD",
     "capkey": "YOUR_LIVE_CAP_KEY"
   }
   ```
   - Click **"CREATE SECRET"**

### Option B: Using gcloud CLI

```bash
# Create the secret with your live credentials
echo '{
  "apikey": "YOUR_LIVE_API_KEY",
  "username": "your-email@example.com",
  "password": "YOUR_LIVE_PASSWORD",
  "capkey": "YOUR_LIVE_CAP_KEY"
}' | gcloud secrets create marketServiceCredentials \
  --data-file=- \
  --project=double-venture-442318-k8
```

---

## Step 3: Deploy Production Service

### Review Configuration

The production service will be deployed with:
- **Function Name**: `marketServiceLive`
- **API Environment**: `LIVE` (real money!)
- **Memory**: 512Mi (more than demo)
- **CPU**: 2 (more than demo)
- **Secret**: `marketServiceCredentials`

### Deploy

```bash
cd /Users/kirtanbhatt/code/stockScreener/cloud-function

# Deploy to production (trading DISABLED by default)
./scripts/deploy-production.sh
```

**⚠️ IMPORTANT: Creating NEW positions is DISABLED by default on production!**

The service is deployed with `ALLOW_LIVE_TRADING=false` for safety. This means:
- ✅ Market data endpoints work (read-only)
- ✅ You can view positions
- ❌ Creating **NEW** positions is **BLOCKED**
- ✅ Updating existing positions is **ALLOWED** (update stop loss, take profit)
- ✅ Closing existing positions is **ALLOWED**

This safety feature prevents opening new positions accidentally while still allowing you to manage and close any existing positions.

---

## Step 4: Enable Trading (When Ready)

### Test Read-Only Access First

```bash
# Get your production URL
gcloud functions describe marketServiceLive \
  --region=us-central1 \
  --project=double-venture-442318-k8 \
  --format='value(serviceConfig.uri)'

# Test read-only endpoints (should work)
curl https://marketservicelive-6ovej2yaoa-uc.a.run.app/get_positions
curl https://marketservicelive-6ovej2yaoa-uc.a.run.app/market/GOLD

# Try to create position (should be blocked with 403)
curl -X POST https://marketservicelive-6ovej2yaoa-uc.a.run.app/create_position \
  -H "Content-Type: application/json" \
  -d '{"epic":"GOLD","direction":"BUY","size":0.01}'

# Expected: {"error": "Creating new positions disabled on live environment"}

# Try to update existing position (should work)
curl -X POST https://marketservicelive-6ovej2yaoa-uc.a.run.app/updte_position \
  -H "Content-Type: application/json" \
  -d '{"action":"update-sl","epic":"GOLD","stopLevel":2000}'

# Expected: 200 OK - updates work even when ALLOW_LIVE_TRADING=false
```

### Enable Creating New Positions

**Only do this when you're absolutely ready to open new positions with real money!**

Note: You can already update and close existing positions. This setting only controls creating NEW positions.

Edit `scripts/deploy-production.sh` and change:
```bash
ALLOW_LIVE_TRADING="false"  # Change to "true"
```

Then redeploy:
```bash
./scripts/deploy-production.sh --confirm-overwrite
```

**Or enable via gcloud command:**
```bash
gcloud functions deploy marketServiceLive \
  --region=us-central1 \
  --update-env-vars=ALLOW_LIVE_TRADING=true \
  --project=double-venture-442318-k8
```

### Verify Trading is Enabled

```bash
# Check logs for confirmation
gcloud functions logs read marketServiceLive \
  --region=us-central1 \
  --limit=5 \
  --project=double-venture-442318-k8

# Should see: "⚡ Capital.com API Environment: LIVE"
# Should NOT see: "🔒 LIVE TRADING DISABLED"
```

---

## Step 5: Test with Minimal Position

You'll be prompted to confirm. Type `yes` to proceed.

---

## Step 4: Verify Deployment

### Check Function Status
```bash
gcloud functions describe marketServiceLive \
  --region us-central1 \
  --gen2 \
  --project double-venture-442318-k8
```

### Get Production URL
```bash
gcloud functions describe marketServiceLive \
  --region us-central1 \
  --gen2 \
  --format="value(serviceConfig.uri)" \
  --project double-venture-442318-k8
```

Expected URL format:
```
https://capitalcomserviceproduction-XXXXX.a.run.app
```

### Test Authentication

```bash
# Test with a safe read-only endpoint
curl "YOUR_PRODUCTION_URL/get_positions"
```

Should return your live positions (or empty array if no positions).

---

## Step 5: Update Frontend Configuration

Update your Lovable frontend to use the production URL:

```typescript
// For production environment
const API_URL = 'https://capitalcomserviceproduction-XXXXX.a.run.app';
```

Or better, use environment variables:

```typescript
const API_URL = import.meta.env.VITE_CAPITAL_API_URL || 
  'https://us-central1-double-venture-442318-k8.cloudfunctions.net/capitalComService';
```

---

## Step 6: Configure TradingView for Production

### Update Webhook URL

In TradingView alerts, update the webhook URL to production:

**Demo URL:**
```
https://us-central1-double-venture-442318-k8.cloudfunctions.net/capitalComService/create_position
```

**Production URL:**
```
https://capitalcomserviceproduction-XXXXX.a.run.app/create_position
```

⚠️ **Test alerts with SMALL position sizes first!**

---

## Monitoring & Safety

### 1. Monitor Logs Continuously

```bash
# Stream live logs
gcloud functions logs read marketServiceLive \
  --region us-central1 \
  --gen2 \
  --limit 50 \
  --project double-venture-442318-k8

# Or tail logs in real-time
gcloud functions logs tail marketServiceLive \
  --region us-central1 \
  --gen2 \
  --project double-venture-442318-k8
```

### 2. Set Up Alerts

Consider setting up Cloud Monitoring alerts for:
- Function errors (5xx responses)
- High latency (> 5s)
- Unexpected traffic spikes
- Failed authentications

### 3. Daily Reconciliation

- Check live positions vs. expected positions
- Verify P/L against trading platform
- Review all executed trades
- Monitor API rate limits

---

## Risk Management Checklist

Before going live:

- [ ] **Position Sizing**: Start with minimum position sizes
- [ ] **Stop Losses**: All positions must have stop losses
- [ ] **Daily Limits**: Implement max trades per day
- [ ] **Max Exposure**: Set maximum total exposure limits
- [ ] **Testing Period**: Run for 1 week with tiny positions
- [ ] **Monitoring**: Someone actively watching during market hours
- [ ] **Kill Switch**: Know how to quickly stop all trading
- [ ] **Backup Plan**: Manual override process defined

---

## Emergency Procedures

### Stop All Trading Immediately

**Option 1: Close all positions via API**
```bash
# Get all positions
curl "YOUR_PRODUCTION_URL/get_positions"

# Close each position (replace DEAL_ID)
curl -X DELETE "YOUR_PRODUCTION_URL/close_position/DEAL_ID"
```

**Option 2: Disable TradingView Webhooks**
- Delete or disable all TradingView alerts

**Option 3: Make function private (stop external access)**
```bash
gcloud functions remove-iam-policy-binding marketServiceLive \
  --region us-central1 \
  --member="allUsers" \
  --role="roles/cloudfunctions.invoker" \
  --gen2 \
  --project double-venture-442318-k8
```

**Option 4: Delete the function**
```bash
gcloud functions delete marketServiceLive \
  --region us-central1 \
  --gen2 \
  --project double-venture-442318-k8
```

---

## Differences: Demo vs Production

| Feature | Demo Environment | Production Environment |
|---------|-----------------|----------------------|
| **API URL** | `demo-api-capital.backend-capital.com` | `api-capital.backend-capital.com` |
| **Money** | Virtual/Paper trading | **Real money** |
| **Secret Name** | `capitalService` | `marketServiceCredentials` |
| **Function Name** | `capitalComService` | `marketServiceLive` |
| **Memory** | 256Mi | 512Mi |
| **CPU** | 1 | 2 |
| **Environment Variable** | `CAPITAL_ENV=demo` | `CAPITAL_ENV=live` |

---

## Cost Considerations

### Cloud Function Costs
- **Invocations**: First 2M free, then $0.40 per million
- **Compute Time**: First 400K GB-seconds free
- **Egress**: First 1GB free per month

### trading Trading Costs
- **Spreads**: Varies by instrument
- **Overnight financing**: For held positions
- **Commission**: Depends on account type

---

## Rollback Procedure

If you need to rollback:

```bash
# List previous revisions
gcloud functions describe marketServiceLive \
  --region us-central1 \
  --gen2 \
  --project double-venture-442318-k8

# Rollback to previous revision (if needed)
# Contact Google Cloud support for revision management
```

---

## Support & Resources

- **trading Live API Docs**: https://open-api.capital.com/
- **Google Cloud Functions**: https://console.cloud.google.com/functions
- **Secret Manager**: https://console.cloud.google.com/security/secret-manager
- **Cloud Logging**: https://console.cloud.google.com/logs

---

## Final Checklist Before Going Live

- [ ] Tested extensively on demo for at least 1 week
- [ ] All features working as expected
- [ ] Error handling properly implemented
- [ ] Stop losses mandatory on all positions
- [ ] Position sizes are minimal to start
- [ ] Monitoring dashboard set up
- [ ] Emergency procedures documented
- [ ] Someone available to monitor during market hours
- [ ] trading live account funded
- [ ] Production secret created and tested
- [ ] TradingView alerts tested with tiny positions
- [ ] Understand all risks involved

---

## ⚠️ FINAL WARNING

**This is real money trading. You can lose your entire capital.**

- Start small and scale gradually
- Never risk more than you can afford to lose
- Monitor continuously during market hours
- Have a kill switch ready
- Keep detailed logs of all trades
- Review performance daily

**If you're not 100% confident, stay on demo longer!**

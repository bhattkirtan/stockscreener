# 🔐 GCP Authentication Setup for Signal Flow

## Current Status

✅ **Firestore Database**: Enabled and running
```
Project: double-venture-442318-k8
Database: (default)
Location: nam5
Type: FIRESTORE_NATIVE
Status: ACTIVE
```

⏳ **Authentication**: Needs setup for write permissions

---

## Quick Setup (2 Options)

### Option A: Application Default Credentials (Simplest)

```bash
# Authenticate your local machine
gcloud auth application-default login

# Set project
export GOOGLE_CLOUD_PROJECT=double-venture-442318-k8
export GCP_PROJECT_ID=double-venture-442318-k8

# Test
python3 scripts/test_signal_flow.py
```

**When to use**: Development, local testing, personal use

### Option B: Service Account (Production)

```bash
# 1. Create service account
gcloud iam service-accounts create trading-bot \
    --display-name="Trading Bot" \
    --project=double-venture-442318-k8

# 2. Grant Firestore permissions
gcloud projects add-iam-policy-binding double-venture-442318-k8 \
    --member="serviceAccount:trading-bot@double-venture-442318-k8.iam.gserviceaccount.com" \
    --role="roles/datastore.user"

# 3. Create key
gcloud iam service-accounts keys create ~/trading-bot-key.json \
    --iam-account=trading-bot@double-venture-442318-k8.iam.gserviceaccount.com

# 4. Use key
export GOOGLE_APPLICATION_CREDENTIALS=~/trading-bot-key.json

# 5. Test
python3 scripts/test_signal_flow.py
```

**When to use**: Production deployments, Cloud Run, GCE, automated systems

---

## For Your 2-Week Test

Since you're running the bot locally on your Mac for paper trading, use **Option A**:

```bash
# One-time setup
gcloud auth application-default login

# Add to your shell profile (~/.zshrc or ~/.bashrc)
echo 'export GOOGLE_CLOUD_PROJECT=double-venture-442318-k8' >> ~/.zshrc
echo 'export GCP_PROJECT_ID=double-venture-442318-k8' >> ~/.zshrc
source ~/.zshrc

# Start bot (signals will auto-publish to Firestore)
cd cloud-function
./scripts/start_bot.sh screen
```

---

## Alternative: Run Without Firestore (File-based)

If you don't need Firestore right now:

```python
# In scripts/trading_bot.py, modify the SignalPublisher init:
self.signal_publisher = SignalPublisher(
    backends=[SignalBackend.FILE],  # Use local file instead
    file_path='trading_signals.json'
)
```

Signals will be saved to `trading_signals.json` instead of Firestore.

Your React app can then:
- Poll the JSON file via HTTP endpoint
- Or upload file to GCS and read from there

---

## Firestore Permissions Needed

The bot needs: `roles/datastore.user` which includes:
- `datastore.entities.create` - Create signals
- `datastore.entities.get` - Read signals  
- `datastore.entities.update` - Update signals
- `datastore.entities.delete` - Delete old signals
- `datastore.entities.list` - Query signals

---

## Testing Signal Flow

### 1. Demo (No Auth Required)
```bash
python3 scripts/demo_signal_flow.py
```
Shows how signals will flow, saves to local file

### 2. Full Test (Requires Auth)
```bash
# After authentication
python3 scripts/test_signal_flow.py
```
Publishes real test signal to Firestore

### 3. Live Bot Test
```bash
# Start bot (publishes real signals)
./scripts/start_bot.sh screen

# In another terminal, consume signals
python3 scripts/signal_consumer.py realtime
```

---

## Troubleshooting

### "403 Missing or insufficient permissions"

**Cause**: Not authenticated or missing Firestore permissions

**Fix**:
```bash
gcloud auth application-default login
# OR set up service account (see Option B above)
```

### "Could not load default credentials"

**Cause**: No credentials file found

**Fix**:
```bash
# Set default credentials
gcloud auth application-default login

# Or point to service account key
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/key.json
```

### "Firestore not enabled"

**Already enabled!** Your project has Firestore active.

Verify: `gcloud firestore databases list`

---

## For React Frontend

No special auth needed! Firebase SDK handles it:

```javascript
// firebaseConfig.js
import { initializeApp } from 'firebase/app';
import { getFirestore } from 'firebase/firestore';

const firebaseConfig = {
  projectId: "double-venture-442318-k8",
  // ... other config from Firebase Console
};

const app = initializeApp(firebaseConfig);
export const db = getFirestore(app);

// Now use in components (see SIGNAL_FLOW.md)
```

Get config from: https://console.firebase.google.com/project/double-venture-442318-k8/settings/general

---

## Summary

**For your 2-week test**:
1. Run: `gcloud auth application-default login`
2. Start bot: `./scripts/start_bot.sh screen`
3. Signals auto-publish to Firestore ✅
4. Add React listener (see SIGNAL_FLOW.md)

**Authentication is done once, signals flow forever!**

# 🎉 New Firebase Project Setup Complete!

## Project Created
**Project ID**: `capital-screener-1773127368`  
**Display Name**: Capital Screener  
**Console**: https://console.firebase.google.com/project/capital-screener-1773127368

---

## ✅ What's Done

### 1. Firebase Project
- ✅ Created new project: `capital-screener-1773127368`
- ✅ Selected as active Firebase CLI project

### 2. Config Files Updated
- ✅ [capital-connect/src/lib/firebase.ts](../capital-connect/src/lib/firebase.ts) - Frontend Firebase init
- ✅ [capital-connect/.env](../capital-connect/.env) - Frontend env vars
- ✅ [capital-connect/.env.example](../capital-connect/.env.example) - Template
- ✅ [cloud-function/.env](../.env) - Backend env vars (bot)
- ✅ [cloud-function/firestore.rules](../firestore.rules) - Security rules
- ✅ [cloud-function/firebase.json](../firebase.json) - Firebase config

---

## 🔧 Next Steps (3 minutes)

### Step 1: Enable Firestore
1. Open: https://console.firebase.google.com/project/capital-screener-1773127368/firestore
2. Click **"Create Database"**
3. Choose **"Production mode"** (we'll update rules right after)
4. Select location: **us-central1** (or your preferred region)
5. Click **"Enable"**

### Step 2: Deploy Security Rules
After Firestore is enabled:
```bash
cd /Users/kirtanbhatt/code/stockScreener/cloud-function
firebase deploy --only firestore:rules
```

Or manually via console:
1. Go to: https://console.firebase.google.com/project/capital-screener-1773127368/firestore/rules
2. Copy contents from `cloud-function/firestore.rules`
3. Paste and click **"Publish"**

### Step 3: Get Real Firebase Credentials
1. Go to: https://console.firebase.google.com/project/capital-screener-1773127368/settings/general
2. Scroll to **"Your apps"** → Click **web icon** (</>) to add web app
3. Register app name: "Capital Connect UI"
4. Copy the `firebaseConfig` values
5. Update `capital-connect/.env` with real values:
   - `VITE_FIREBASE_API_KEY`
   - `VITE_FIREBASE_MESSAGING_SENDER_ID`
   - `VITE_FIREBASE_APP_ID`

### Step 4: Restart Bot
```bash
# Kill old bot
pkill -f "trading_bot_m5.py"

# Start with new project config
cd /Users/kirtanbhatt/code/stockScreener/cloud-function
python3 scripts/trading_bot_m5.py > bot.log 2>&1 &

# Verify
sleep 3 && tail -30 bot.log
```

### Step 5: Test UI
```bash
cd /Users/kirtanbhatt/code/stockScreener/capital-connect
npm run dev
```

---

## 📋 Firestore Security Rules Created

```javascript
rules_version = '2';
service cloud.firestore {
  match /databases/{database}/documents {
    // Trading signals collection
    match /trading_signals/{signalId} {
      // Allow bot to write signals
      allow write: if true;
      
      // Allow anyone to read signals (testing)
      // TODO: Change to 'if request.auth != null' for production
      allow read: if true;
    }
    
    // Deny all other collections
    match /{document=**} {
      allow read, write: if false;
    }
  }
}
```

---

## 🔐 Service Account Credentials

The bot uses Application Default Credentials (ADC). Ensure you're authenticated:

```bash
# Check current auth
gcloud auth application-default print-access-token

# If needed, login
gcloud auth application-default login --project=capital-screener-1773127368
```

---

## 🎯 Signal Flow Architecture

```
Bot (Python)
    ↓ (publishes)
Firestore (trading_signals collection)
    ↓ (real-time subscription)
React UI (SignalsPanel component)
```

**Latency**: 50-200ms (real-time)  
**Cost**: $0/month (free tier)

---

## 📱 Deployment Checklist

- [ ] Enable Firestore in console
- [ ] Deploy/publish security rules
- [ ] Get real Firebase web app credentials
- [ ] Update capital-connect/.env with real credentials
- [ ] Restart bot with new project config
- [ ] Test local UI (npm run dev)
- [ ] Wait for first signal (~09:53)
- [ ] Verify signal appears in UI
- [ ] Push to git (Lovable auto-deploys)

---

## 🆘 Troubleshooting

**Bot can't write to Firestore**:
```bash
gcloud auth application-default login --project=capital-screener-1773127368
```

**UI can't read signals** (permission denied):
- Check Firestore rules are deployed
- Verify `allow read: if true;` in rules

**Wrong project ID**:
```bash
firebase use capital-screener-1773127368
```

---

## 📚 Files Reference

- Rules: [firestore.rules](../firestore.rules)
- Config: [firebase.json](../firebase.json)
- Frontend: [src/lib/firebase.ts](../capital-connect/src/lib/firebase.ts)
- Backend: [.env](../.env)
- Hook: [useSignals.ts](../capital-connect/src/hooks/useSignals.ts)
- UI: [SignalsPanel.tsx](../capital-connect/src/components/SignalsPanel.tsx)

---

**Ready to complete setup! Start with Step 1: Enable Firestore** 🚀

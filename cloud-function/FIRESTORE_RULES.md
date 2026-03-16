# Firestore Security Rules Update

## Files Created:
- `firestore.rules` - Security rules configuration
- `firebase.json` - Firebase project configuration

## Update Rules (Choose One Method):

### Method 1: Firebase CLI (Recommended)

**Install Firebase CLI:**
```bash
npm install -g firebase-cli
```

**Login and deploy rules:**
```bash
cd /Users/kirtanbhatt/code/stockScreener/cloud-function

# Login to Firebase
firebase login

# Initialize project (one-time)
firebase use double-venture-442318-k8

# Deploy rules
firebase deploy --only firestore:rules
```

### Method 2: Firebase Console (Manual)

1. Go to: https://console.firebase.google.com/project/double-venture-442318-k8/firestore/rules

2. Copy the contents of `firestore.rules` file

3. Paste into the rules editor

4. Click "Publish"

## Current Rules:

The `firestore.rules` file allows:
- ✅ **Read**: Open access (testing) - TODO: Change to authenticated users in production
- ✅ **Write**: Open access (bot can publish signals)

## Security Levels:

**Testing (Current):**
```javascript
allow read: if true;  // Anyone can read
```

**Production (Recommended):**
```javascript
allow read: if request.auth != null;  // Only authenticated users
```

## Next Steps:

1. Deploy rules using Method 1 or 2 above
2. Verify by refreshing your React app
3. Signals should load without permission errors
4. Later: Add Firebase Authentication and update to production rules

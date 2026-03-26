# API Setup Guide

This guide explains how to set up all three APIs (Capital.com, Firestore, Telegram) for the trading bot.

---

## 🏦 Capital.com API Setup

Capital.com provides REST and WebSocket APIs for trading operations.

### 1. Create Capital.com Account

- **Demo**: [https://capital.com/trading/signup](https://capital.com/trading/signup)
- **Live**: Same URL, create account and verify identity

### 2. Generate API Key

1. Log into Capital.com web platform
2. Go to **Settings** → **API**
3. Click **Create API Key**
4. Save your API key securely (cannot be retrieved later)

### 3. Get Credentials

You need three pieces of information:
- **Username**: Your Capital.com email
- **Password**: Your Capital.com password
- **API Key**: Generated in step 2

### 4. Test Connection

```python
from clients.capital_api import CapitalAPIClient

client = CapitalAPIClient(
    username="your_email@example.com",
    password="your_password",
    api_key="your_api_key",
    environment="demo"  # or "live"
)

# Test authentication
session = client.create_session()
print(f"Account ID: {session['account']['accountId']}")

# Get account balance
account = client.get_account_info()
print(f"Balance: {account['accounts'][0]['balance']['balance']}")
```

### 5. Configuration

Add to `config/trading_config.yaml`:

```yaml
capital_com:
  username: your_email@example.com
  password: your_password_here
  api_key: your_api_key_here
  environment: demo  # Change to 'live' for real trading
  epic: CS.D.CFDGOLD.CFD.IP
  position_size: 0.5
  sl_pips: 20
  tp_pips: 40
```

### ⚠️ Important Notes

- **Always test in demo environment first**
- Demo and live environments use different API endpoints (handled automatically)
- Session tokens expire after 60 minutes (auto-refreshed by client)
- Rate limits: ~60 requests/minute

---

## 🔥 Firestore API Setup

Google Cloud Firestore is used for position and trade persistence.

### 1. Create GCP Project

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project (e.g., "trading-bot-storage")
3. Note your **Project ID**

### 2. Enable Firestore

1. In GCP Console, go to **Firestore**
2. Click **Select Native Mode**
3. Choose region (e.g., `us-central1`)
4. Click **Create Database**

### 3. Create Service Account

1. Go to **IAM & Admin** → **Service Accounts**
2. Click **Create Service Account**
3. Name: `trading-bot`
4. Grant roles:
   - **Cloud Datastore User** (read/write Firestore)
5. Click **Create Key** → **JSON**
6. Save JSON file to secure location (e.g., `~/credentials/trading-bot-serviceaccount.json`)

### 4. Set Up Authentication

**Option A: Environment Variable** (Recommended)
```bash
export GOOGLE_APPLICATION_CREDENTIALS="/path/to/serviceaccount.json"
```

**Option B: Config File**
```yaml
firestore:
  credentials_path: /path/to/serviceaccount.json
```

### 5. Create Collections

Create these Firestore collections (will be auto-created on first write):
- `active_positions` - Open positions
- `trading_signals` - Signal history
- `trade_history` - Closed trades
- `bot_status` - Bot heartbeat

### 6. Test Connection

```python
from clients.firestore_api import FirestoreAPIClient

client = FirestoreAPIClient(
    project_id="your-gcp-project-id",
    credentials_path="/path/to/serviceaccount.json"
)

# Test write
success = client.save_position(
    collection="active_positions",
    deal_id="TEST123",
    position_data={"direction": "BUY", "entry_price": 1950.50}
)
print(f"Write success: {success}")

# Test read
position = client.get_position(
    collection="active_positions",
    deal_id="TEST123"
)
print(f"Position: {position}")
```

### 7. Configuration

Add to `config/trading_config.yaml`:

```yaml
firestore:
  project_id: your-gcp-project-id
  credentials_path: /path/to/serviceaccount.json  # Optional if using env var
  collections:
    positions: active_positions
    signals: trading_signals
    trade_history: trade_history
    bot_status: bot_status
```

### ⚠️ Important Notes

- **Never commit service account JSON to git**
- Use IAM roles to restrict permissions (principle of least privilege)
- Firestore free tier: 50K reads + 20K writes per day
- Consider setting up Firestore rules for security

---

## 📱 Telegram Bot Setup

Telegram is used for trade alerts and notifications.

### 1. Create Telegram Bot

1. Open Telegram app
2. Search for `@BotFather`
3. Send `/newbot`
4. Choose a name (e.g., "Gold Trading Bot")
5. Choose a username (e.g., "my_gold_trading_bot")
6. **Save the bot token** (looks like `1234567890:ABCdefGHIjklMNOpqrsTUVwxyz`)

### 2. Get Your Chat ID

**Option A: Using @userinfobot**
1. Search for `@userinfobot` in Telegram
2. Start a chat
3. It will reply with your **Chat ID** (e.g., `123456789`)

**Option B: Using API**
```bash
# Replace YOUR_BOT_TOKEN with your actual token
curl "https://api.telegram.org/botYOUR_BOT_TOKEN/getUpdates"
```
Send a message to your bot, then look for `"chat":{"id":123456789}` in the response

### 3. Test Bot

```bash
# Replace YOUR_BOT_TOKEN and YOUR_CHAT_ID
curl -X POST "https://api.telegram.org/botYOUR_BOT_TOKEN/sendMessage" \
  -H "Content-Type: application/json" \
  -d '{
    "chat_id": "YOUR_CHAT_ID",
    "text": "Hello from trading bot! 🤖"
  }'
```

### 4. Test with Python Client

```python
from clients.telegram_api import TelegramAPIClient

client = TelegramAPIClient(
    bot_token="1234567890:ABCdefGHIjklMNOpqrsTUVwxyz",
    chat_id="123456789"
)

# Send test message
success = client.send_message("🤖 Bot is online!")
print(f"Message sent: {success}")

# Send trade alert
success = client.send_trade_opened(
    direction="BUY",
    entry_price=1950.50,
    stop_loss=1940.00,
    take_profit=1970.00,
    size=0.5,
    deal_id="TEST123"
)
print(f"Trade alert sent: {success}")
```

### 5. Configuration

Add to `config/trading_config.yaml`:

```yaml
telegram:
  enabled: true
  token: 1234567890:ABCdefGHIjklMNOpqrsTUVwxyz
  chat_id: 123456789
  trade_opened: true
  trade_closed: true
  sl_hit: true
  tp_hit: true
  error: true
  daily_summary: true
```

### ⚠️ Important Notes

- **Keep bot token secret** - anyone with token can send messages as your bot
- Bot tokens never expire unless revoked via @BotFather
- Telegram API free tier: unlimited messages
- Rate limit: ~30 messages/second
- For group alerts, add bot to group and use group chat_id (negative number)

---

## 🧪 Testing All APIs

### Quick Test (Mock Mode)

```bash
cd /Users/kirtanbhatt/code/stockScreener/trading-bot-skills
python test_api_connections.py
```

This tests all APIs in **mock mode** (no credentials needed).

### Full Test (Real APIs)

1. Configure APIs in `config/trading_config.yaml`
2. Set `mock_mode: false`
3. Run:
   ```bash
   python test_api_connections.py
   ```
4. Choose "y" when prompted to test real APIs

Expected output:
```
✅ Capital.com session created
✅ Firestore write successful
✅ Telegram message sent
```

---

## 🔒 Security Best Practices

### 1. Environment Variables

Store sensitive credentials in environment variables:

```bash
# Add to ~/.bashrc or ~/.zshrc
export CAPITAL_USERNAME="your_email@example.com"
export CAPITAL_PASSWORD="your_password"
export CAPITAL_API_KEY="your_api_key"
export TELEGRAM_BOT_TOKEN="1234567890:ABCdefGHIjklMNOpqrsTUVwxyz"
export TELEGRAM_CHAT_ID="123456789"
export GOOGLE_APPLICATION_CREDENTIALS="/path/to/serviceaccount.json"
```

Load in Python:
```python
import os

config = {
    'capital_com': {
        'username': os.getenv('CAPITAL_USERNAME'),
        'password': os.getenv('CAPITAL_PASSWORD'),
        'api_key': os.getenv('CAPITAL_API_KEY'),
    },
    'telegram': {
        'token': os.getenv('TELEGRAM_BOT_TOKEN'),
        'chat_id': os.getenv('TELEGRAM_CHAT_ID'),
    }
}
```

### 2. Git Ignore

Add to `.gitignore`:
```
config/trading_config.yaml
*.json
credentials/
.env
```

### 3. Credential Rotation

- Rotate Capital.com API key every 90 days
- Rotate Telegram bot token if compromised
- Rotate GCP service account keys every 90 days

### 4. Access Control

- Use demo environment for development
- Use separate API keys for staging/production
- Limit Firestore service account permissions
- Never share credentials via Slack/email

---

## 📊 API Usage Limits

| API | Rate Limit | Free Tier | Cost |
|-----|------------|-----------|------|
| **Capital.com** | ~60 req/min | N/A | Trading fees only |
| **Firestore** | None* | 50K reads/day, 20K writes/day | $0.18/100K reads |
| **Telegram** | ~30 msg/sec | Unlimited | Free |

*Firestore has soft limits; contact GCP if you need more

---

## ❓ Troubleshooting

### Capital.com 401 Unauthorized
- **Cause**: Wrong credentials or expired session
- **Fix**: Check username/password, regenerate API key

### Capital.com 429 Rate Limit
- **Cause**: Too many API requests
- **Fix**: Add delays between requests, use caching

### Firestore Permission Denied
- **Cause**: Service account lacks permissions
- **Fix**: Grant "Cloud Datastore User" role

### Telegram Message Not Received
- **Cause**: Wrong chat_id or bot not started
- **Fix**: Send `/start` to your bot, verify chat_id with @userinfobot

### Firestore "Project not found"
- **Cause**: Wrong project_id or credentials
- **Fix**: Verify project_id in GCP Console, check credentials path

---

## 📚 Additional Resources

- [Capital.com API Docs](https://open-api.capital.com/)
- [Firestore Python Client](https://googleapis.dev/python/firestore/latest/)
- [Telegram Bot API](https://core.telegram.org/bots/api)
- [GCP Free Tier](https://cloud.google.com/free)

---

## ✅ Checklist

Before running the bot in live mode:

- [ ] Capital.com API tested in demo environment
- [ ] Firestore collections created and accessible
- [ ] Telegram bot receives test messages
- [ ] All credentials stored securely (not in git)
- [ ] Mock mode tests pass
- [ ] Real API tests pass
- [ ] Trading config validated
- [ ] Risk limits configured
- [ ] Bot tested in demo mode for 1 week
- [ ] Ready for live trading 🚀

# News Update Job

Local job to update news headlines from RSS feeds and upload to GCS.

## Quick Start

```bash
cd cloud-function

# Run once
./update_news.sh

# Or run directly with Python
python3 -m src.data.news_generator
```

## What it does

1. Fetches latest headlines from RSS feeds:
   - Reuters
   - CNBC
   - MarketWatch
   - BBC Business
   - AP Business

2. Saves to `data/news_headlines.json`

3. Uploads to GCS: `gs://double-venture-442318-k8-optimization-results/external-data/`

4. API can then serve the news at `/api/v1/news`

## Setup Cron Job (Auto-update every 15 minutes)

```bash
# Edit crontab
crontab -e

# Add this line (update every 15 minutes):
*/15 * * * * cd /Users/kirtanbhatt/code/stockScreener/cloud-function && ./update_news.sh >> logs/news_update.log 2>&1
```

## Setup Cron Job (Every hour)

```bash
# Edit crontab
crontab -e

# Add this line (update every hour at :05):
5 * * * * cd /Users/kirtanbhatt/code/stockScreener/cloud-function && ./update_news.sh >> logs/news_update.log 2>&1
```

## Manual Schedule Options

### Every 30 minutes
```bash
*/30 * * * * cd /Users/kirtanbhatt/code/stockScreener/cloud-function && ./update_news.sh >> logs/news_update.log 2>&1
```

### Every 2 hours
```bash
0 */2 * * * cd /Users/kirtanbhatt/code/stockScreener/cloud-function && ./update_news.sh >> logs/news_update.log 2>&1
```

### Business hours only (9 AM - 5 PM, every 30 min)
```bash
*/30 9-17 * * 1-5 cd /Users/kirtanbhatt/code/stockScreener/cloud-function && ./update_news.sh >> logs/news_update.log 2>&1
```

## Check Logs

```bash
# View latest updates
tail -f cloud-function/logs/news_update.log

# View last 50 lines
tail -50 cloud-function/logs/news_update.log
```

## Verify It's Working

```bash
# Check local file
cat data/news_headlines.json | jq '.total_headlines'

# Check GCS
gsutil cat gs://double-venture-442318-k8-optimization-results/external-data/news_headlines.json | jq '.total_headlines'

# Test API
curl "https://optimize-api-6ovej2yaoa-uc.a.run.app/api/v1/news" | jq '.[:3]'
```

## Stop Cron Job

```bash
# Edit crontab
crontab -e

# Comment out or delete the news update line
# Save and exit
```

## Troubleshooting

### No headlines generated

RSS feeds might be temporarily down. The script will skip failed feeds and continue with others.

### GCS upload fails

Check permissions:
```bash
gcloud auth application-default login
```

### Cron not running

Check cron service:
```bash
# macOS
sudo launchctl list | grep cron

# Linux
sudo systemctl status cron
```

View cron logs:
```bash
# macOS
log show --predicate 'process == "cron"' --last 2h

# Linux
grep CRON /var/log/syslog
```

## File Structure

```
cloud-function/
├── update_news.sh           # Main update script
├── src/data/
│   └── news_generator.py    # News fetcher
├── data/
│   └── news_headlines.json  # Generated file
└── logs/
    └── news_update.log      # Cron logs (create if needed)
```

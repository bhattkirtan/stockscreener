#!/bin/bash

# News Update Job - Run this locally or via cron
# Updates news_headlines.json and uploads to GCS

set -e

echo "🔄 Starting news update job..."
echo "Time: $(date)"
echo ""

# Navigate to cloud-function directory
cd "$(dirname "$0")"

# Generate news headlines
echo "📰 Generating news headlines..."
python3 -m src.data.news_generator

if [ ! -f "data/news_headlines.json" ]; then
    echo "❌ Error: news_headlines.json not generated"
    exit 1
fi

# Show stats
echo ""
echo "📊 News Statistics:"
cat data/news_headlines.json | python3 -c "import sys, json; data=json.load(sys.stdin); print(f'  Total headlines: {data[\"total_headlines\"]}'); print(f'  Sources: {len(data[\"sources\"])}'); print(f'  Updated: {data[\"updated_at\"]}')"

# Upload to GCS
echo ""
echo "☁️  Uploading to GCS..."
gsutil cp data/news_headlines.json gs://double-venture-442318-k8-optimization-results/external-data/

echo ""
echo "✅ News update complete!"
echo "Time: $(date)"

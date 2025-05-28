#!/bin/bash

# Exit immediately if a command exits with a non-zero status
set -e

echo "📥 Collecting news articles..."
python news_collection.py

echo "🧹 Deduplicating articles..."
python de_duplicate.py

echo "🧽 Filtering articles..."
python filter_articles.py

echo "✅ Pipeline completed."

echo "📣 Sending notification to Telegram..."

curl -s -X POST "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/sendMessage" \
  -d chat_id="$TELEGRAM_CHAT_ID" \
  -d text="📰 *New articles are ready!*\nUse /label to begin reviewing." \
  -d parse_mode=Markdown
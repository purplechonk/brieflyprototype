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
python run_pipeline.py
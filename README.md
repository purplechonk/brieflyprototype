# Briefly Prototype

This repository contains two main services:

1. News Collector Service (`/news-collector`)
   - Collects news articles from various sources
   - Runs on a schedule via Cloud Scheduler
   - Stores articles in PostgreSQL database

2. Telegram Bot Service (`/telegram-bot`)
   - Serves news articles to users via Telegram
   - Handles user interactions and feedback
   - Reads from the same PostgreSQL database

## Repository Structure

```
briefly-prototype-1/
├── news-collector/       # News collection service
│   ├── Dockerfile
│   ├── news_collection.py
│   ├── requirements.txt
│   └── README.md
├── telegram-bot/        # Telegram bot service
│   ├── Dockerfile
│   ├── label_bot.py
│   ├── requirements.txt
│   └── README.md
├── shared/             # Shared resources
│   └── database/       # Database schemas and migrations
│       └── *.sql
└── cloudbuild.yaml     # Cloud Build configuration for both services
```

## Setup

1. Set up environment variables in `.env`:
```bash
DATABASE_URL=postgresql://user:pass@host:port/newsdb
EVENT_REGISTRY_API_KEY=your_api_key
TELEGRAM_BOT_TOKEN=your_bot_token
```

2. Deploy services:
```bash
# Deploy via Cloud Build
gcloud builds submit

# Or deploy services individually
cd news-collector && docker build -t news-collector . && docker push ...
cd telegram-bot && docker build -t telegram-bot . && docker push ...
```

3. Set up Cloud Scheduler for news collection:
- Create a job to hit the news-collector service endpoint
- Recommended schedule: daily at midnight (0 0 * * *)

## Development

Each service can be developed and tested independently:

```bash
# Run news collector locally
cd news-collector
pip install -r requirements.txt
python news_collection.py

# Run Telegram bot locally
cd telegram-bot
pip install -r requirements.txt
python label_bot.py
```

## Architecture

- Both services use the same PostgreSQL database
- News collector runs on schedule to fetch and store articles
- Telegram bot serves articles to users and collects feedback
- Services are deployed separately on Cloud Run
- Cloud Scheduler triggers news collection daily

# News Bot

A Telegram bot that serves news articles and collects user feedback. The bot allows users to:
- Read geopolitical news
- Read Singapore news
- Like/Dislike articles
- View full article content

## Setup

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Set up environment variables in `.env`:
```
TELEGRAM_BOT_TOKEN=your_bot_token
DATABASE_URL=your_database_url
```

3. Run database migrations:
```bash
psql $DATABASE_URL -f create_user_responses_table.sql
```

4. Start the bot:
```bash
python label_bot.py
```

## Docker Support

Build the container:
```bash
docker build -t news-bot .
```

Run the container:
```bash
docker run -d --env-file .env news-bot
```

## Cloud Deployment

This project is configured for Google Cloud Platform deployment using:
- Cloud Run for hosting
- Cloud SQL for PostgreSQL database
- Cloud Build for CI/CD

See `cloudbuild.yaml` for deployment configuration. 
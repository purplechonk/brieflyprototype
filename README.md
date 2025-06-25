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
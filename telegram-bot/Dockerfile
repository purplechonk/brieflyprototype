FROM python:3.9-slim

# Set working directory
WORKDIR /app

# Install git
RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

# Copy requirements file
COPY telegram-bot/requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy service files
COPY telegram-bot/label_bot.py .

# Run the Telegram bot
EXPOSE 8080
CMD ["python", "label_bot.py"] 
# Use Python 3.9 slim image
FROM python:3.9-slim

# Install git and required system dependencies
RUN apt-get update && apt-get install -y \
    git \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements first to leverage Docker cache
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application code
COPY news_collection.py .

# Set environment variables
ENV PORT=8080

# Run the application
CMD ["python", "news_collection.py"] 
FROM python:3.9-slim

# Set working directory
WORKDIR /app

# Install git
RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

# Copy requirements file
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy service files
COPY news_collection.py .

# Run the news collection script
CMD ["python", "news_collection.py"] 
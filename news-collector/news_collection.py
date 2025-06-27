# news_collection.py
# Retrieving News Using News API for multiple topics
# Use pip install eventregistry

from eventregistry import *
import pandas as pd
from datetime import datetime, timedelta
from dotenv import load_dotenv
import psycopg2
import os
import time
from flask import Flask
import sys
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

api_key = os.getenv('EVENT_REGISTRY_API_KEY')
DATABASE_URL = os.getenv('DATABASE_URL')

logger.info(f"Starting with API key: {api_key[:8]}... and DB URL format: {DATABASE_URL.split('@')[1] if '@' in DATABASE_URL else 'No @ in URL'}")

er = EventRegistry(apiKey=api_key)

app = Flask(__name__)

@app.route('/', methods=['GET'])
def health_check():
    return 'News collector service is running'

@app.route('/', methods=['POST'])
def collect_news():
    try:
        logger.info("Starting news collection via HTTP trigger")
        sys.stdout.flush()
        main()
        return 'News collection completed successfully', 200
    except Exception as e:
        logger.error(f"Error in collect_news endpoint: {str(e)}")
        sys.stdout.flush()
        return f'Error collecting news: {str(e)}', 500

def _build_query(base_query):
    """
    Wraps a base EventRegistry query with filters.
    """
    logger.info(f"Building query with base: {base_query}")
    return {
        "$query": base_query,
        "$filter": {
            # Data type filter: news or press
            "dataType": "news",
            # Duplicate handling: skipDuplicates, keepDuplicates
            "isDuplicate": "skipDuplicates",
            "hasDuplicate": "skipHasDuplicates",
            # Event linking: skipArticlesWithoutEvent, keepArticlesWithoutEvent
            "hasEvent": "skipArticlesWithoutEvent",
            # Source rank percentile range
            "startSourceRankPercentile": 0,
            "endSourceRankPercentile": 90,
            # Sentiment range
            "minSentiment": -1,
            "maxSentiment": 1,
        },
    }


def fetch_geopolitics(date_start, date_end):
    """Fetch geopolitics-related articles."""
    logger.info(f"Fetching geopolitics articles from {date_start} to {date_end}")
    base_query = {
        "categoryUri": {"$or": [
            "dmoz/Society/Politics/International_Relations",
            "dmoz/Society/Issues/Warfare_and_Conflict",
            "dmoz/Society/Government/Foreign_Ministries"
        ]},
        "lang": "eng",
        "sourceUri": {"$or": ["channelnewsasia.com", "straitstimes.com"]},
        "dateStart": date_start,
        "dateEnd": date_end
    }
    return _fetch_topic(base_query, "Geopolitics", "International")

def fetch_singapore_news(date_start, date_end):
    """Fetch Singapore-related news."""
    logger.info(f"Fetching Singapore news from {date_start} to {date_end}")
    base_query = {
        "categoryUri": {"$or": [
            "dmoz/Regional/Asia/Singapore",
            "dmoz/Society/Government",
            "dmoz/Society/Politics",
            "dmoz/Business",
            "dmoz/Society"
        ]},
        "lang": "eng",
        "sourceUri": {"$or": ["channelnewsasia.com", "straitstimes.com"]},
        "dateStart": date_start,
        "dateEnd": date_end,
    }
    return _fetch_topic(base_query, "Singapore", "Local")

def get_connection(retries=5, delay=5):
    """Get a database connection with retry logic"""
    for attempt in range(retries):
        try:
            logger.info(f"Attempting database connection (attempt {attempt + 1}/{retries})")
            return psycopg2.connect(DATABASE_URL)
        except psycopg2.Error as e:
            if attempt == retries - 1:
                logger.error(f"Failed to connect to database after {retries} attempts: {str(e)}")
                raise e
            logger.warning(f"Database connection attempt {attempt + 1} failed. Retrying in {delay} seconds...")
            time.sleep(delay)

def save_article_to_db(article, category, subcategory):
    """Save a single article and initialize its metrics"""
    conn = None
    try:
        logger.info(f"Saving article: {article.get('uri')[:30]}...")
        conn = get_connection()
        with conn.cursor() as cur:
            # Insert article
            cur.execute("""
                INSERT INTO articles (
                    uri, title, body, url, image_url, category, 
                    published_date, created_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP
                ) ON CONFLICT (uri) DO UPDATE SET
                    title = EXCLUDED.title,
                    body = EXCLUDED.body,
                    url = EXCLUDED.url,
                    image_url = EXCLUDED.image_url,
                    category = EXCLUDED.category,
                    published_date = EXCLUDED.published_date
                RETURNING uri
            """, (
                article.get("uri"),
                article.get("title"),
                article.get("body"),
                article.get("url"),
                article.get("image", {}).get("url"),
                f"{category}/{subcategory}" if subcategory else category,
                article.get("dateTime")
            ))
            
            uri = cur.fetchone()[0]
            logger.info(f"Successfully inserted/updated article: {uri[:30]}...")
            
            # Initialize metrics if they don't exist
            cur.execute("""
                INSERT INTO article_metrics (uri, views, likes, dislikes, read_more_clicks)
                VALUES (%s, 0, 0, 0, 0)
                ON CONFLICT (uri) DO NOTHING
            """, (uri,))
            
            conn.commit()
            return True
    except Exception as e:
        logger.error(f"Error saving article {article.get('uri')}: {str(e)}")
        if conn:
            conn.rollback()
        return False
    finally:
        if conn:
            conn.close()

def _fetch_topic(base_query, category, topic_name):
    """Fetch articles for a topic and save them to the database"""
    try:
        logger.info(f"\nFetching {category}/{topic_name}")
        sys.stdout.flush()
        
        # Build and execute query
        complex_query = _build_query(base_query)
        q = QueryArticlesIter.initWithComplexQuery(complex_query)
        
        return_info = ReturnInfo(
            articleInfo=ArticleInfoFlags(
                bodyLen=-1,
                basicInfo=True,
                title=True,
                body=True,
                url=True,
                eventUri=True,
                authors=True,
                concepts=True,
                categories=True,
                links=True,
                videos=True,
                image=True,
                socialScore=True,
                sentiment=True,
                location=True,
                dates=True,
                extractedDates=True,
                originalArticle=True,
                storyUri=True
            )
        )
        
        results = []
        for article in q.execQuery(
            er,
            sortBy="date",
            sortByAsc=False,
            returnInfo=return_info,
            maxItems=100
        ):
            data = article.copy()
            data["category"] = category
            data["sub-category"] = topic_name
            results.append(data)
            
        logger.info(f"Found {len(results)} articles for {category}/{topic_name}")
        
        # Process and save articles
        saved_count = 0
        for article in results:
            try:
                if save_article_to_db(article, category, topic_name):
                    saved_count += 1
            except Exception as e:
                logger.error(f"Error saving individual article: {str(e)}")
                continue
        
        logger.info(f"Saved {saved_count}/{len(results)} articles for {category}/{topic_name}")
        sys.stdout.flush()
        return results
        
    except Exception as e:
        logger.error(f"Error fetching {category}/{topic_name}: {str(e)}")
        sys.stdout.flush()
        return []

def main():
    """Main function to fetch news"""
    logger.info(f"Starting news collection at {datetime.now()}")
    sys.stdout.flush()
    
    # Calculate exact 24 hour window
    end_date = datetime.now()
    start_date = end_date - timedelta(hours=24)
    
    # Format dates for EventRegistry with time precision
    date_end = end_date.strftime("%Y-%m-%d %H:%M:%S")
    date_start = start_date.strftime("%Y-%m-%d %H:%M:%S")
    
    logger.info(f"Fetching articles from {date_start} to {date_end}")
    sys.stdout.flush()
    
    try:
        # Fetch only geopolitics and Singapore news
        fetch_geopolitics(date_start, date_end)
        fetch_singapore_news(date_start, date_end)
        
        logger.info(f"Completed news collection at {datetime.now()}")
        sys.stdout.flush()
    except Exception as e:
        logger.error(f"Error in main collection process: {str(e)}")
        sys.stdout.flush()

# Run news collection on startup and then let Flask handle requests
if __name__ == "__main__":
    try:
        # Run initial news collection
        logger.info("Running initial news collection on startup")
        main()
    except Exception as e:
        logger.error(f"Error in startup news collection: {str(e)}")
    
    # Start the Flask server
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
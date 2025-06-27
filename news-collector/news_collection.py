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
from flask import Flask, request
import sys
import logging

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

load_dotenv()

api_key = os.getenv('EVENT_REGISTRY_API_KEY')
DATABASE_URL = os.getenv('DATABASE_URL')

logger.info(f"Starting with API key: {api_key[:8] if api_key else 'None'}... and DB URL format: {DATABASE_URL.split('@')[1] if DATABASE_URL and '@' in DATABASE_URL else 'No @ in URL'}")

if not api_key:
    logger.error("EVENT_REGISTRY_API_KEY not found in environment variables!")
if not DATABASE_URL:
    logger.error("DATABASE_URL not found in environment variables!")

er = EventRegistry(apiKey=api_key) if api_key else None

app = Flask(__name__)

@app.route('/', methods=['GET'])
def health_check():
    logger.info("Health check endpoint called")
    return 'News collector service is running'

@app.route('/', methods=['POST'])
def collect_news():
    try:
        logger.info("POST request received - starting news collection")
        sys.stdout.flush()
        
        if not er:
            logger.error("EventRegistry not initialized - missing API key")
            return 'Error: EventRegistry API key not configured', 500
            
        if not DATABASE_URL:
            logger.error("Database URL not configured")
            return 'Error: Database URL not configured', 500
            
        main()
        logger.info("News collection completed successfully")
        return 'News collection completed successfully', 200
    except Exception as e:
        logger.error(f"Error in collect_news endpoint: {str(e)}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        sys.stdout.flush()
        return f'Error collecting news: {str(e)}', 500

@app.route('/trigger', methods=['GET', 'POST'])
def trigger_collection():
    """Alternative endpoint for triggering news collection"""
    try:
        logger.info("Manual trigger endpoint called")
        sys.stdout.flush()
        
        if not er:
            logger.error("EventRegistry not initialized - missing API key")
            return 'Error: EventRegistry API key not configured', 500
            
        main()
        logger.info("Manual trigger completed successfully")
        return 'News collection triggered successfully', 200
    except Exception as e:
        logger.error(f"Error in trigger endpoint: {str(e)}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        return f'Error: {str(e)}', 500

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
        logger.info(f"Fetching {category}/{topic_name}")
        sys.stdout.flush()
        
        if not er:
            logger.error("EventRegistry not initialized")
            return []
        
        # Build and execute query
        complex_query = _build_query(base_query)
        logger.info(f"Complex query built: {complex_query}")
        
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
        
        logger.info(f"Starting query execution for {category}/{topic_name}")
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
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
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
        logger.info("About to fetch geopolitics articles")
        geopolitics_results = fetch_geopolitics(date_start, date_end)
        logger.info(f"Geopolitics fetch completed with {len(geopolitics_results)} articles")
        
        logger.info("About to fetch Singapore articles")
        singapore_results = fetch_singapore_news(date_start, date_end)
        logger.info(f"Singapore fetch completed with {len(singapore_results)} articles")
        
        total_articles = len(geopolitics_results) + len(singapore_results)
        logger.info(f"Completed news collection at {datetime.now()} - Total articles: {total_articles}")
        sys.stdout.flush()
        
    except Exception as e:
        logger.error(f"Error in main collection process: {str(e)}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        sys.stdout.flush()

if __name__ == "__main__":
    logger.info("Starting news collector service")
    
    # Start the Flask server without running collection on startup
    # Collection will be triggered via POST requests
    port = int(os.environ.get('PORT', 8080))
    logger.info(f"Starting Flask server on port {port}")
    app.run(host='0.0.0.0', port=port, debug=False)
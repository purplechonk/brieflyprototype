# news_collection_v2.py
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


load_dotenv()

api_key = os.getenv('EVENT_REGISTRY_API_KEY')
DATABASE_URL = os.getenv('DATABASE_URL')

print(f"Using API key: {api_key[:8]}...")  # Only show first 8 chars for security
er = EventRegistry(apiKey=api_key)

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")
print(f"Database URL format: {DATABASE_URL.split('@')[1] if '@' in DATABASE_URL else 'No @ in URL'}")  # Only show host part

app = Flask(__name__)

@app.route('/', methods=['GET'])
def health_check():
    return 'News collector service is running'

@app.route('/', methods=['POST'])
def collect_news():
    try:
        print("Starting news collection via HTTP trigger")
        sys.stdout.flush()  # Force flush print statements
        main()
        return 'News collection completed successfully', 200
    except Exception as e:
        print(f"Error in collect_news endpoint: {str(e)}")
        sys.stdout.flush()  # Force flush print statements
        return f'Error collecting news: {str(e)}', 500

def _build_query(base_query):
    """
    Wraps a base EventRegistry query with filters.
    """
    # Convert keyword queries to QueryItems format if present
    if "keyword" in base_query:
        if isinstance(base_query["keyword"], dict) and "$or" in base_query["keyword"]:
            keywords = base_query["keyword"]["$or"]
            base_query["keyword"] = QueryItems.OR([QueryItems(x) for x in keywords])
        elif isinstance(base_query["keyword"], str):
            base_query["keyword"] = QueryItems(base_query["keyword"])

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
    base_query = {
        "categoryUri": {"$or": [
            "dmoz/Society/Politics/International_Relations",
            "dmoz/Society/Issues/Warfare_and_Conflict",
            "dmoz/Society/Government/Foreign_Ministries"
        ]},
        "lang": "eng",
        "sourceUri": {"$or": ["channelnewsasia.com", "straitstimes.com"]},
        "dateStart": date_start,
        "dateEnd": date_end,
        "keyword": None  # Explicitly set keyword to None
    }
    return _fetch_topic(base_query, "Geopolitics", "International")

def fetch_singapore_news(date_start, date_end):
    """Fetch Singapore-related news."""
    base_query = {
        "categoryUri": {"$or": [
            "dmoz/Regional/Asia/Singapore",
            "dmoz/Society/Government",
            "dmoz/Society/Politics",
            "dmoz/Business",
            "dmoz/Society"
        ]},
        "keyword": None,  # Explicitly set keyword to None
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
            return psycopg2.connect(DATABASE_URL)
        except psycopg2.Error as e:
            if attempt == retries - 1:  # Last attempt
                raise e
            print(f"Database connection attempt {attempt + 1} failed. Retrying in {delay} seconds...")
            time.sleep(delay)

def save_article_to_db(article, category, subcategory):
    """Save a single article and initialize its metrics"""
    try:
        print(f"Attempting to save article: {article.get('uri')[:30]}...")
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
            print(f"Successfully inserted/updated article: {uri[:30]}...")
            
            # Initialize metrics if they don't exist
            cur.execute("""
                INSERT INTO article_metrics (uri, views, likes, dislikes, read_more_clicks)
                VALUES (%s, 0, 0, 0, 0)
                ON CONFLICT (uri) DO NOTHING
            """, (uri,))
            
            conn.commit()
            return True
    except Exception as e:
        print(f"Error saving article {article.get('uri')}: {str(e)}")
        if conn:
            conn.rollback()
        return False
    finally:
        if conn:
            conn.close()

def _fetch_topic(base_query, category, topic_name):
    """Fetch articles for a topic and save them to the database"""
    try:
        print(f"\nFetching {category}/{topic_name}")
        sys.stdout.flush()  # Force flush print statements
        
        # Build and execute query
        q = QueryArticles(
            _build_query(base_query)
        )
        
        articles = q.execute(
            maxItems=100,
            sortBy="date",
            sortByAsc=False
        )
        
        print(f"Query executed for {category}/{topic_name}")
        sys.stdout.flush()  # Force flush print statements
        
        if not articles:
            print(f"No articles object returned for {category}/{topic_name}")
            return []
            
        if "articles" not in articles:
            print(f"No 'articles' key in response for {category}/{topic_name}")
            return []
            
        if "results" not in articles["articles"]:
            print(f"No 'results' key in articles for {category}/{topic_name}")
            return []
            
        results = articles["articles"]["results"]
        print(f"Found {len(results)} articles for {category}/{topic_name}")
        
        # Process and save articles
        saved_count = 0
        for article in results:
            try:
                if save_article_to_db(article, category, topic_name):
                    saved_count += 1
            except Exception as e:
                print(f"Error saving individual article: {str(e)}")
                continue
        
        print(f"Saved {saved_count}/{len(results)} articles for {category}/{topic_name}")
        sys.stdout.flush()  # Force flush print statements
        return results
        
    except Exception as e:
        print(f"Error fetching {category}/{topic_name}: {str(e)}")
        sys.stdout.flush()  # Force flush print statements
        return []

def main():
    """Main function to fetch news"""
    print(f"Starting news collection at {datetime.now()}")
    sys.stdout.flush()
    
    # Calculate exact 24 hour window
    end_date = datetime.now()
    start_date = end_date - timedelta(hours=24)
    
    # Format dates for EventRegistry with time precision
    date_end = end_date.strftime("%Y-%m-%d %H:%M:%S")
    date_start = start_date.strftime("%Y-%m-%d %H:%M:%S")
    
    print(f"Fetching articles from {date_start} to {date_end}")
    sys.stdout.flush()
    
    try:
        # Fetch only geopolitics and Singapore news
        fetch_geopolitics(date_start, date_end)
        fetch_singapore_news(date_start, date_end)
        
        print(f"Completed news collection at {datetime.now()}")
        sys.stdout.flush()
    except Exception as e:
        print(f"Error in main collection process: {str(e)}")
        sys.stdout.flush()

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
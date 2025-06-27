# news_collection.py - Full functionality with debugging
from eventregistry import *
from datetime import datetime, timedelta
from dotenv import load_dotenv
import psycopg2
import os
import time
from flask import Flask, request, jsonify
import sys
import logging
import traceback

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

print("=== STARTING NEWS COLLECTOR ===", flush=True)
logger.info("Starting news collector service")

load_dotenv()

api_key = os.getenv('EVENT_REGISTRY_API_KEY')
DATABASE_URL = os.getenv('DATABASE_URL')

print(f"=== STARTUP INFO ===", flush=True)
print(f"API Key present: {bool(api_key)}", flush=True)
print(f"API Key length: {len(api_key) if api_key else 0}", flush=True)
print(f"Database URL present: {bool(DATABASE_URL)}", flush=True)
print(f"Database URL format: {DATABASE_URL.split('@')[1] if DATABASE_URL and '@' in DATABASE_URL else 'Invalid format'}", flush=True)
print(f"===================", flush=True)

logger.info(f"Starting with API key present: {bool(api_key)} and DB URL present: {bool(DATABASE_URL)}")

if not api_key:
    logger.error("EVENT_REGISTRY_API_KEY not found in environment variables!")
    print("ERROR: EVENT_REGISTRY_API_KEY not found!", flush=True)
if not DATABASE_URL:
    logger.error("DATABASE_URL not found in environment variables!")
    print("ERROR: DATABASE_URL not found!", flush=True)

er = None
if api_key:
    try:
        er = EventRegistry(apiKey=api_key)
        logger.info("EventRegistry initialized successfully")
        print("EventRegistry initialized successfully", flush=True)
    except Exception as e:
        logger.error(f"Failed to initialize EventRegistry: {str(e)}")
        print(f"ERROR: Failed to initialize EventRegistry: {str(e)}", flush=True)

app = Flask(__name__)

@app.route('/', methods=['GET'])
def health_check():
    logger.info("Health check endpoint called")
    print("Health check called", flush=True)
    return 'News collector service is running - Full functionality'

@app.route('/test', methods=['GET'])
def test_endpoint():
    """Test endpoint to check configuration"""
    try:
        print("=== TEST ENDPOINT CALLED ===", flush=True)
        logger.info("Test endpoint called")
        
        result = {
            "status": "ok",
            "api_key_present": bool(api_key),
            "api_key_length": len(api_key) if api_key else 0,
            "database_url_present": bool(DATABASE_URL),
            "eventregistry_initialized": bool(er),
            "timestamp": datetime.now().isoformat()
        }
        
        # Test database connection
        try:
            if DATABASE_URL:
                conn = psycopg2.connect(DATABASE_URL)
                conn.close()
                result["database_connection"] = "success"
                print("Database connection test: SUCCESS", flush=True)
            else:
                result["database_connection"] = "no_url"
                print("Database connection test: NO URL", flush=True)
        except Exception as db_e:
            result["database_connection"] = f"failed: {str(db_e)}"
            print(f"Database connection test: FAILED - {str(db_e)}", flush=True)
        
        # Test EventRegistry
        if er:
            try:
                # Try a simple test query
                test_query = QueryArticles(lang="eng")
                test_result = test_query.execute(maxItems=1)
                result["eventregistry_test"] = "success" if test_result else "no_results"
                print(f"EventRegistry test: {'SUCCESS' if test_result else 'NO RESULTS'}", flush=True)
            except Exception as er_e:
                result["eventregistry_test"] = f"failed: {str(er_e)}"
                print(f"EventRegistry test: FAILED - {str(er_e)}", flush=True)
        else:
            result["eventregistry_test"] = "not_initialized"
            print("EventRegistry test: NOT INITIALIZED", flush=True)
        
        print(f"Test result: {result}", flush=True)
        return jsonify(result)
        
    except Exception as e:
        error_msg = f"Test endpoint error: {str(e)}"
        logger.error(error_msg)
        print(f"ERROR in test endpoint: {str(e)}", flush=True)
        print(f"Traceback: {traceback.format_exc()}", flush=True)
        return jsonify({"error": error_msg}), 500

@app.route('/', methods=['POST'])
def collect_news():
    try:
        print("=== POST REQUEST RECEIVED ===", flush=True)
        logger.info("POST request received - starting news collection")
        sys.stdout.flush()
        
        if not er:
            error_msg = "EventRegistry not initialized - missing API key"
            logger.error(error_msg)
            print(f"ERROR: {error_msg}", flush=True)
            return error_msg, 500
            
        if not DATABASE_URL:
            error_msg = "Database URL not configured"
            logger.error(error_msg)
            print(f"ERROR: {error_msg}", flush=True)
            return error_msg, 500
        
        print("Starting main() function...", flush=True)
        main()
        print("main() function completed", flush=True)
        logger.info("News collection completed successfully")
        return 'News collection completed successfully', 200
    except Exception as e:
        error_msg = f"Error in collect_news endpoint: {str(e)}"
        logger.error(error_msg)
        logger.error(f"Traceback: {traceback.format_exc()}")
        print(f"ERROR: {error_msg}", flush=True)
        print(f"Traceback: {traceback.format_exc()}", flush=True)
        sys.stdout.flush()
        return f'Error collecting news: {str(e)}', 500

@app.route('/trigger', methods=['GET', 'POST'])
def trigger_collection():
    """Alternative endpoint for triggering news collection"""
    try:
        print("=== TRIGGER ENDPOINT CALLED ===", flush=True)
        logger.info("Manual trigger endpoint called")
        sys.stdout.flush()
        
        if not er:
            error_msg = "EventRegistry not initialized - missing API key"
            logger.error(error_msg)
            print(f"ERROR: {error_msg}", flush=True)
            return error_msg, 500
            
        print("Starting main() function from trigger...", flush=True)
        main()
        print("main() function completed from trigger", flush=True)
        logger.info("Manual trigger completed successfully")
        return 'News collection triggered successfully', 200
    except Exception as e:
        error_msg = f"Error in trigger endpoint: {str(e)}"
        logger.error(error_msg)
        logger.error(f"Traceback: {traceback.format_exc()}")
        print(f"ERROR: {error_msg}", flush=True)
        print(f"Traceback: {traceback.format_exc()}", flush=True)
        return f'Error: {str(e)}', 500

def _build_query(base_query):
    """Wraps a base EventRegistry query with filters."""
    print(f"Building query with base: {base_query}", flush=True)
    logger.info(f"Building query with base: {base_query}")
    return {
        "$query": base_query,
        "$filter": {
            "dataType": "news",
            "isDuplicate": "skipDuplicates",
            "hasDuplicate": "skipHasDuplicates",
            "hasEvent": "skipArticlesWithoutEvent",
            "startSourceRankPercentile": 0,
            "endSourceRankPercentile": 90,
            "minSentiment": -1,
            "maxSentiment": 1,
        },
    }

def fetch_geopolitics(date_start, date_end):
    """Fetch geopolitics-related articles."""
    print(f"=== FETCHING GEOPOLITICS ===", flush=True)
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
    print(f"=== FETCHING SINGAPORE NEWS ===", flush=True)
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

def get_connection(retries=3, delay=2):
    """Get a database connection with retry logic"""
    for attempt in range(retries):
        try:
            print(f"Database connection attempt {attempt + 1}/{retries}", flush=True)
            logger.info(f"Attempting database connection (attempt {attempt + 1}/{retries})")
            return psycopg2.connect(DATABASE_URL)
        except psycopg2.Error as e:
            if attempt == retries - 1:
                error_msg = f"Failed to connect to database after {retries} attempts: {str(e)}"
                logger.error(error_msg)
                print(f"ERROR: {error_msg}", flush=True)
                raise e
            print(f"Database connection attempt {attempt + 1} failed. Retrying in {delay} seconds...", flush=True)
            logger.warning(f"Database connection attempt {attempt + 1} failed. Retrying in {delay} seconds...")
            time.sleep(delay)

def save_article_to_db(article, category, subcategory):
    """Save a single article and initialize its metrics"""
    conn = None
    try:
        print(f"Saving article: {article.get('uri', 'NO_URI')[:30]}...", flush=True)
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
            print(f"Successfully saved article: {uri[:30]}...", flush=True)
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
        error_msg = f"Error saving article {article.get('uri')}: {str(e)}"
        logger.error(error_msg)
        print(f"ERROR: {error_msg}", flush=True)
        if conn:
            conn.rollback()
        return False
    finally:
        if conn:
            conn.close()

def _fetch_topic(base_query, category, topic_name):
    """Fetch articles for a topic and save them to the database"""
    try:
        print(f"=== STARTING FETCH FOR {category}/{topic_name} ===", flush=True)
        logger.info(f"Fetching {category}/{topic_name}")
        sys.stdout.flush()
        
        if not er:
            error_msg = "EventRegistry not initialized"
            logger.error(error_msg)
            print(f"ERROR: {error_msg}", flush=True)
            return []
        
        # Build and execute query
        print("Building complex query...", flush=True)
        complex_query = _build_query(base_query)
        print(f"Complex query built: {complex_query}", flush=True)
        logger.info(f"Complex query built: {complex_query}")
        
        print("Initializing QueryArticlesIter...", flush=True)
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
        
        print(f"Starting query execution for {category}/{topic_name}...", flush=True)
        logger.info(f"Starting query execution for {category}/{topic_name}")
        results = []
        
        article_count = 0
        for article in q.execQuery(
            er,
            sortBy="date",
            sortByAsc=False,
            returnInfo=return_info,
            maxItems=100
        ):
            article_count += 1
            if article_count <= 5:  # Log first 5 articles
                print(f"Processing article {article_count}: {article.get('title', 'NO_TITLE')[:50]}...", flush=True)
            
            data = article.copy()
            data["category"] = category
            data["sub-category"] = topic_name
            results.append(data)
        
        print(f"Found {len(results)} articles for {category}/{topic_name}", flush=True)
        logger.info(f"Found {len(results)} articles for {category}/{topic_name}")
        
        # Process and save articles
        saved_count = 0
        for i, article in enumerate(results):
            try:
                if save_article_to_db(article, category, topic_name):
                    saved_count += 1
                if i < 3:  # Log first 3 saves
                    print(f"Processed article {i+1}/{len(results)}", flush=True)
            except Exception as e:
                error_msg = f"Error saving individual article: {str(e)}"
                logger.error(error_msg)
                print(f"ERROR: {error_msg}", flush=True)
                continue
        
        print(f"Saved {saved_count}/{len(results)} articles for {category}/{topic_name}", flush=True)
        logger.info(f"Saved {saved_count}/{len(results)} articles for {category}/{topic_name}")
        sys.stdout.flush()
        return results
        
    except Exception as e:
        error_msg = f"Error fetching {category}/{topic_name}: {str(e)}"
        logger.error(error_msg)
        logger.error(f"Traceback: {traceback.format_exc()}")
        print(f"ERROR: {error_msg}", flush=True)
        print(f"Traceback: {traceback.format_exc()}", flush=True)
        sys.stdout.flush()
        return []

def main():
    """Main function to fetch news"""
    print("=== STARTING MAIN FUNCTION ===", flush=True)
    logger.info(f"Starting news collection at {datetime.now()}")
    sys.stdout.flush()
    
    # Calculate exact 24 hour window
    end_date = datetime.now()
    start_date = end_date - timedelta(hours=24)
    
    # Format dates for EventRegistry - use YYYY-MM-DD format only
    date_end = end_date.strftime("%Y-%m-%d")
    date_start = start_date.strftime("%Y-%m-%d")
    
    print(f"Fetching articles from {date_start} to {date_end}", flush=True)
    logger.info(f"Fetching articles from {date_start} to {date_end}")
    sys.stdout.flush()
    
    try:
        # Fetch only geopolitics and Singapore news
        print("About to fetch geopolitics articles...", flush=True)
        logger.info("About to fetch geopolitics articles")
        geopolitics_results = fetch_geopolitics(date_start, date_end)
        print(f"Geopolitics fetch completed with {len(geopolitics_results)} articles", flush=True)
        logger.info(f"Geopolitics fetch completed with {len(geopolitics_results)} articles")
        
        print("About to fetch Singapore articles...", flush=True)
        logger.info("About to fetch Singapore articles")
        singapore_results = fetch_singapore_news(date_start, date_end)
        print(f"Singapore fetch completed with {len(singapore_results)} articles", flush=True)
        logger.info(f"Singapore fetch completed with {len(singapore_results)} articles")
        
        total_articles = len(geopolitics_results) + len(singapore_results)
        print(f"=== COMPLETED NEWS COLLECTION - Total articles: {total_articles} ===", flush=True)
        logger.info(f"Completed news collection at {datetime.now()} - Total articles: {total_articles}")
        sys.stdout.flush()
        
    except Exception as e:
        error_msg = f"Error in main collection process: {str(e)}"
        logger.error(error_msg)
        logger.error(f"Traceback: {traceback.format_exc()}")
        print(f"ERROR: {error_msg}", flush=True)
        print(f"Traceback: {traceback.format_exc()}", flush=True)
        sys.stdout.flush()

if __name__ == "__main__":
    print("=== STARTING FLASK SERVER ===", flush=True)
    logger.info("Starting Flask server")
    
    port = int(os.environ.get('PORT', 8080))
    print(f"Starting Flask server on port {port}", flush=True)
    logger.info(f"Starting Flask server on port {port}")
    
    try:
        app.run(host='0.0.0.0', port=port, debug=False)
    except Exception as e:
        print(f"ERROR starting Flask server: {str(e)}", flush=True)
        logger.error(f"Error starting Flask server: {str(e)}")
        sys.exit(1)

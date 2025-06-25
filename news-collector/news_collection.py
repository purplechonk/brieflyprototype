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
database_url = os.getenv('DATABASE_URL')

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


MAJOR_POWER_KEYWORDS = ["United States", "China", "Russia", "India", "France", "United Kingdom", "Germany", "Japan"]

def fetch_great_power_competition(date_start, date_end):
    base_query = {
        "keyword": {"$or": MAJOR_POWER_KEYWORDS},
        "categoryUri": {"$or": ["dmoz/Society/Politics", "dmoz/Society/Government/Foreign_Ministries", "dmoz/Business"]},
        "lang": "eng",
        "sourceUri": {"$or": ["channelnewsasia.com", "straitstimes.com"]},
        "dateStart": date_start,
        "dateEnd": date_end,
        "minArticlesInEvent": 1,
    }
    all_articles = _fetch_topic(base_query,"Geopolitics", "Great-Power Competition")

    # Post-filter: match multiple countries mentioned in title/body
    filtered_articles = []
    for art in all_articles:
        text = (art.get("title", "") + " " + art.get("body", "")).lower()
        mentioned = [c for c in MAJOR_POWER_KEYWORDS if c.lower() in text]
        if len(set(mentioned)) >= 2:
            filtered_articles.append(art)

    print(f"Filtered to {len(filtered_articles)} multi-power articles from {len(all_articles)} total")
    return filtered_articles


SECURITY_KEYWORDS = [
    "war", "conflict", "military", "border dispute", "airstrike",
    "missile", "tensions", "sovereignty", "cyberattack", "espionage",
    "terrorism", "deterrence", "military drill", "troop movement", "ceasefire"
]


def fetch_conflict_and_security(date_start, date_end):
    base_query = {
        "keyword": {"$or": SECURITY_KEYWORDS},
        "categoryUri": {"$or": [
            "dmoz/Society/Issues/Warfare_and_Conflict",
            "dmoz/Society/Politics/International_Relations",
            "dmoz/Computers/Security",
            "dmoz/Society/Politics"
        ]},
        "lang": "eng",
        "sourceUri": {"$or": ["channelnewsasia.com", "straitstimes.com"]},
        "dateStart": date_start,
        "dateEnd": date_end,
        "keywordLoc": "title,body",
        "keywordSearchMode": "simple",
        "minArticlesInEvent": 1,
    }
    all_articles = _fetch_topic(base_query,"Geopolitics", "Conflict and Security")

    # Optional: refine by checking if at least one keyword appears in article text
    filtered_articles = []
    for art in all_articles:
        text = (art.get("title", "") + " " + art.get("body", "")).lower()
        if any(kw.lower() in text for kw in SECURITY_KEYWORDS):
            filtered_articles.append(art)

    print(f"Filtered to {len(filtered_articles)} security/conflict articles from {len(all_articles)} total")
    return filtered_articles


TRADE_KEYWORDS = [
    "trade agreement", "tariffs", "trade war", "exports", "imports",
    "supply chain", "WTO", "FTA", "trade pact", "export ban",
    "import restriction", "sanctions", "trade negotiation", "logistics"
]


def fetch_international_trade(date_start, date_end):
    base_query = {
        "keyword": {"$or": TRADE_KEYWORDS},
        "categoryUri": {"$or": [
            "dmoz/Business",
            "dmoz/Society/Politics/International_Relations"
        ]},
        "lang": "eng",
        "sourceUri": {"$or": ["channelnewsasia.com", "straitstimes.com"]},
        "dateStart": date_start,
        "dateEnd": date_end,
        "keywordLoc": "title,body",
        "keywordSearchMode": "simple",
        "minArticlesInEvent": 1,
    }
    all_articles = _fetch_topic(base_query,"Geopolitics", "International Trade")

    # Optional: basic keyword verification
    filtered_articles = []
    for art in all_articles:
        text = (art.get("title", "") + " " + art.get("body", "")).lower()
        if any(kw.lower() in text for kw in TRADE_KEYWORDS):
            filtered_articles.append(art)

    print(f"Filtered to {len(filtered_articles)} trade articles from {len(all_articles)} total")
    return filtered_articles

def fetch_international_institutions(date_start, date_end):
    base_query = {
        "keyword": {"$or": [
            "United Nations", "WTO", "IMF", "NATO", "ASEAN", 
            "European Union", "G7", "G20", "BRICS", "SCO", "ICC"
        ]},
        # Temporarily broaden category
        "categoryUri": {"$or": [
            "dmoz/Society/Politics",
            "dmoz/Society/Politics/International_Relations"
        ]},
        "lang": "eng",
        "sourceUri": {"$or": ["channelnewsasia.com", "straitstimes.com"]},
        "dateStart": date_start,
        "dateEnd": date_end,
        "keywordLoc": "title,body",
        "keywordSearchMode": "simple",
        "minArticlesInEvent": 1,
    }
    all_articles = _fetch_topic(base_query,"Geopolitics", "International Institutions")
    
    return all_articles

def fetch_geopolitics(date_start, date_end):
    base_query = {
        "categoryUri": {"$or": [
            "dmoz/Society/Politics",
            "dmoz/Society/Politics/International_Relations",
            "dmoz/Society/Issues"
        ]},
        "lang": "eng",
        "sourceUri": {"$or": ["channelnewsasia.com", "straitstimes.com"]},
        "dateStart": date_start,
        "dateEnd": date_end,
        "minArticlesInEvent": 1,
    }
    return _fetch_topic(base_query,"Geopolitics", "General")

def fetch_economy(date_start, date_end):
    base_query = {
        "categoryUri": {"$or": [
            "dmoz/Business/Economy",
            "dmoz/Business/Economy_and_Finance",
            "dmoz/Business"
        ]},
        "lang": "eng",
        "sourceUri": {"$or": ["channelnewsasia.com", "straitstimes.com"]},
        "dateStart": date_start,
        "dateEnd": date_end,
        "minArticlesInEvent": 1,
    }
    return _fetch_topic(base_query, "Economy", "General")

def fetch_technology(date_start, date_end):
    base_query = {
        "categoryUri": {"$or": [
            "dmoz/Computers/Technology_News",
            "dmoz/Business/Industries/Computers_and_Electronics",
            "dmoz/Computers", 
            "dmoz/Business/Industries/Technology"
        ]},
        "lang": "eng",
        "sourceUri": {"$or": ["channelnewsasia.com", "straitstimes.com"]},
        "dateStart": date_start,
        "dateEnd": date_end,
        "minArticlesInEvent": 1,
    }
    return _fetch_topic(base_query, "Technology", "General")

def fetch_esg(date_start, date_end):
    base_query = {
        "categoryUri": {"$or": [
            "dmoz/Society/Government",
            "dmoz/Society/Issues", 
            "dmoz/Science/Environment"
        ]},
        "lang": "eng",
        "sourceUri": {"$or": ["channelnewsasia.com", "straitstimes.com"]},
        "dateStart": date_start,
        "dateEnd": date_end,
        "minArticlesInEvent": 1,
    }
    return _fetch_topic(base_query, "ESG", "General")

def fetch_business(date_start, date_end):
    base_query = {
        "categoryUri": {"$or": ["dmoz/Business"]},
        "lang": "eng",
        "sourceUri": {"$or": ["channelnewsasia.com", "straitstimes.com"]},
        "dateStart": date_start,
        "dateEnd": date_end,
        "minArticlesInEvent": 1,
    }
    return _fetch_topic(base_query, "Business", "General")


def fetch_government(date_start, date_end):
    base_query = {
        "categoryUri": {"$or": [
            "dmoz/Society/Government",
            "dmoz/Society/Politics/Government"
        ]},
        "lang": "eng",
        "sourceUri": {"$or": ["channelnewsasia.com", "straitstimes.com"]},
        "dateStart": date_start,
        "dateEnd": date_end,
        "minArticlesInEvent": 1,
    }
    return _fetch_topic(base_query, "Government", "General")

def fetch_society(date_start, date_end):
    base_query = {
        "keyword": {"$or": [
            "consumer behaviour", "consumer trend", "shopping habits", 
            "lifestyle trend", "retail trends", "spending habits", 
            "purchase decisions", "brand loyalty", "consumer insights"
        ]},
        "categoryUri": {"$or": [
            "dmoz/Society",
            "dmoz/Business/Consumer_Goods_and_Services"
        ]},
        "lang": "eng",
        "sourceUri": {"$or": ["channelnewsasia.com", "straitstimes.com"]},
        "dateStart": date_start,
        "dateEnd": date_end,
        "keywordLoc": "title,body",
        "keywordSearchMode": "simple",
        "minArticlesInEvent": 1,
    }
    return _fetch_topic(base_query, "Society", "General")

def fetch_companies(start, end):
    base_query={
        "keyword": {"$or": [
            "corporate earnings", "business strategy", "company results"
        ]}, 
        "categoryUri": {"$or": [
            "dmoz/Business"
        ]}, 
        "lang": "eng", 
        "sourceUri": {"$or": [
            "channelnewsasia.com", "straitstimes.com"
        ]}, 
        "dateStart": start, 
        "dateEnd": end, 
        "minArticlesInEvent": 1
    }
    return _fetch_topic(base_query,"Business", "Companies")

def fetch_mergers_acquisitions(start, end):
    base_query={
        "keyword": {"$or": [
            "merger", "acquisition", "takeover", "buyout"
        ]}, 
        "lang": "eng", 
        "sourceUri": {"$or": ["channelnewsasia.com", "straitstimes.com"]}, 
        "dateStart": start, 
        "dateEnd": end, 
        "minArticlesInEvent": 1
    }
    return _fetch_topic(base_query,"Buisiness", "Mergers and Acquisitions")

def fetch_property_infra(start, end):
    base_query={
        "keyword": {"$or": [
            "real estate", "property development", "infrastructure"
        ]}, 
        "lang": "eng", 
        "sourceUri": {"$or": ["channelnewsasia.com", "straitstimes.com"]}, 
        "dateStart": start, 
        "dateEnd": end, 
        "minArticlesInEvent": 1
    }
    return _fetch_topic(base_query,"Business", "Property and Infrastructure")

def fetch_startups(start, end):
    base_query={
        "keyword": {"$or": [
            "startup", "venture capital", "seed funding", "unicorn"
        ]}, 
        "lang": "eng", 
        "sourceUri": {"$or": ["channelnewsasia.com", "straitstimes.com"]}, 
        "dateStart": start, 
        "dateEnd": end, 
        "minArticlesInEvent": 1
    }
    return _fetch_topic(base_query,"Business", "Startups")

# Government
def fetch_sea_politics(start, end):
    return _fetch_topic({"keyword": {"$or": ["Singapore politics", "Malaysia politics", "Indonesian elections"]}, "categoryUri": {"$or": ["dmoz/Society/Politics"]}, "lang": "eng", "sourceUri": {"$or": ["channelnewsasia.com", "straitstimes.com"]}, "dateStart": start, "dateEnd": end, "minArticlesInEvent": 1},"Government", "Southeast Asian Politics")

def fetch_government_initiatives(start, end):
    return _fetch_topic({"keyword": {"$or": ["policy announcement", "public consultation", "government programme"]}, "categoryUri": {"$or": ["dmoz/Society/Government"]}, "lang": "eng", "sourceUri": {"$or": ["channelnewsasia.com", "straitstimes.com"]}, "dateStart": start, "dateEnd": end, "minArticlesInEvent": 1},"Government", "Government Initiatives")

def fetch_tech_policy(start, end):
    
    return _fetch_topic({"keyword": {"$or": ["technology regulation", "data governance", "AI regulation"]}, "categoryUri": {"$or": ["dmoz/Society/Politics"]}, "lang": "eng", "sourceUri": {"$or": ["channelnewsasia.com", "straitstimes.com"]}, "dateStart": start, "dateEnd": end, "minArticlesInEvent": 1},"Government", "Technology Regulation and Policy")

def fetch_climate_policy(start, end):
    return _fetch_topic({"keyword": {"$or": ["climate legislation", "carbon pricing", "environmental regulation"]}, "categoryUri": {"$or": ["dmoz/Science/Environment"]}, "lang": "eng", "sourceUri": {"$or": ["channelnewsasia.com", "straitstimes.com"]}, "dateStart": start, "dateEnd": end, "minArticlesInEvent": 1},"Government", "Climate Regulation and Policy")

# Society
def fetch_consumer_trends(start, end):
    return _fetch_topic({"keyword": {"$or": ["consumer behaviour", "shopping trend", "spending habit", "retail trend"]}, "categoryUri": {"$or": ["dmoz/Society", "dmoz/Business/Consumer_Goods_and_Services"]}, "lang": "eng", "sourceUri": {"$or": ["channelnewsasia.com", "straitstimes.com"]}, "dateStart": start, "dateEnd": end, "minArticlesInEvent": 1},"Society", "Consumer Trends")



def fetch_trump(date_start, date_end):
    """Fetch Trump-related articles."""
    base_query = {
        "conceptUri": {"$and": ["http://en.wikipedia.org/wiki/Donald_Trump"]},
        # "keyword": {"$or": ["trump", "donald"]},
        "categoryUri": {"$or": ["dmoz/Business","dmoz/Society/Politics","dmoz/Society/Government/Foreign_Ministries"]},
        "lang": "eng",
        "sourceUri": {"$or":["channelnewsasia.com","straitstimes.com"]},
        # "sourceLocationUri": "",
        # "sourceGroupUri": "",
        # "authorUri": "",
        # "locationUri": "",
        "dateStart": date_start,
        "dateEnd": date_end,
        # "dateMention": "2025-05-05",
        #"keywordLoc": "title,body",
        # "keywordSearchMode": "simple",
        "minArticlesInEvent": 1,
        # "maxArticlesInEvent": ,
    }
    return _fetch_topic(base_query, "trump")

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
    """Main function to fetch all news categories"""
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
        # Fetch all categories
        fetch_great_power_competition(date_start, date_end)
        fetch_conflict_and_security(date_start, date_end)
        fetch_international_trade(date_start, date_end)
        fetch_international_institutions(date_start, date_end)
        fetch_geopolitics(date_start, date_end)
        fetch_economy(date_start, date_end)
        fetch_technology(date_start, date_end)
        fetch_esg(date_start, date_end)
        fetch_business(date_start, date_end)
        fetch_government(date_start, date_end)
        fetch_society(date_start, date_end)
        fetch_companies(date_start, date_end)
        fetch_mergers_acquisitions(date_start, date_end)
        fetch_property_infra(date_start, date_end)
        fetch_startups(date_start, date_end)
        fetch_sea_politics(date_start, date_end)
        fetch_government_initiatives(date_start, date_end)
        fetch_tech_policy(date_start, date_end)
        fetch_climate_policy(date_start, date_end)
        fetch_consumer_trends(date_start, date_end)
        
        print(f"Completed news collection at {datetime.now()}")
        sys.stdout.flush()
    except Exception as e:
        print(f"Error in main collection process: {str(e)}")
        sys.stdout.flush()

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
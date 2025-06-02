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

# Initialize EventRegistry client (replace with your API key)
API_KEY = "4669b6ea-fa93-40b1-ad2c-1714cc3727b4"
er = EventRegistry(apiKey=API_KEY)

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")

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

def _fetch_topic(base_query, category, topic_name):
    """Helper to execute query and tag results by topic."""
    complex_query = _build_query(base_query)
    q_iter = QueryArticlesIter.initWithComplexQuery(complex_query)
    articles = []
    for art in q_iter.execQuery(
        er,
        sortBy="socialScore",
        # sortBy="rel",
        returnInfo=ReturnInfo(
            articleInfo=ArticleInfoFlags(
                # Toggle desired ArticleInfoFlags fields (True/False):
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
        ),
        maxItems=100
    ):
        data = art.copy()
        data["category"] = category
        data["sub_category"] = topic_name
        articles.append(data)
    print(f"Retrieved {len(articles)} articles for category: {category} sub_category: {topic_name}")
    return articles


def get_connection(retries=5, delay=5):
    for attempt in range(1, retries + 1):
        try:
            conn = psycopg2.connect(DATABASE_URL)
            print("✅ Successfully connected to the database.")
            return conn
        except psycopg2.OperationalError as e:
            print(f"⏳ Attempt {attempt}: Could not connect to database. Retrying in {delay}s...\n{e}")
            time.sleep(delay)
    raise Exception("❌ Failed to connect to database after multiple attempts.")


def save_articles_to_db(df):
    """
    Save articles DataFrame to PostgreSQL 'articles' table.
    """
    if df.empty:
        print("⚠️ No articles to save.")
        return

    try:
        conn = get_connection()
        cursor = conn.cursor()

        for _, row in df.iterrows():
            cursor.execute("""
                INSERT INTO articles (uri, title, body, url, category, sub_category, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (uri) DO NOTHING;
            """, (
                row.get("uri", row.get("url")),
                row.get("title"),
                row.get("body"),
                row.get("url"),
                row.get("category"),
                row.get("sub_category"),
                datetime.now().strftime('%Y-%m-%d')
            ))

        conn.commit()
        cursor.close()
        conn.close()
        print(f"✅ Saved {len(df)} articles to the database.")
    except Exception as e:
        print(f"❌ Error saving to database: {e}")

def main():
    today = datetime.now().strftime('%Y-%m-%d')
    output_dir = os.path.join("output", today)
    os.makedirs(output_dir, exist_ok=True)

    all_articles = []
    all_articles.extend(fetch_great_power_competition(today, today))
    all_articles.extend(fetch_conflict_and_security(today, today))
    all_articles.extend(fetch_international_trade(today, today))
    all_articles.extend(fetch_international_institutions(today, today))
    all_articles.extend(fetch_geopolitics(today, today))
    
    all_articles.extend(fetch_economy(today, today))
    all_articles.extend(fetch_technology(today, today))
    all_articles.extend(fetch_esg(today, today))
    all_articles.extend(fetch_business(today, today))
    all_articles.extend(fetch_government(today, today))
    all_articles.extend(fetch_society(today, today))

    all_articles.extend(fetch_companies(today, today))
    all_articles.extend(fetch_mergers_acquisitions(today, today))
    all_articles.extend(fetch_property_infra(today, today))
    all_articles.extend(fetch_startups(today, today))
    all_articles.extend(fetch_sea_politics(today, today))
    all_articles.extend(fetch_government_initiatives(today, today))
    all_articles.extend(fetch_tech_policy(today, today))
    all_articles.extend(fetch_climate_policy(today, today))
    all_articles.extend(fetch_consumer_trends(today, today))

    df = pd.DataFrame(all_articles)
    save_articles_to_db(df)
    print(f"Exported {len(df)} total articles into the database.")

if __name__ == "__main__":
    main()
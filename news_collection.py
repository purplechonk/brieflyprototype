# news_collection_v2.py
# Retrieving News Using News API for multiple topics
# Use pip install eventregistry

from eventregistry import *
import pandas as pd
from datetime import datetime, timedelta
from dotenv import load_dotenv
import psycopg2
import os

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


# def fetch_elections(date_start, date_end):
    # """Fetch election-related articles."""
    # base_query = {
        # "conceptUri": "",
        # "keyword": "",
        # "categoryUri": "dmoz/Society/Politics/Campaigns_and_Elections",
        # "lang": "eng",
        # "sourceUri": {"$or":["channelnewsasia.com","straitstimes.com"]},
        # "sourceLocationUri": "",
        # "sourceGroupUri": "",
        # "authorUri": "",
        # "locationUri": "",
        # "dateStart": date_start,
        # "dateEnd": date_end,
        # "dateMention": "2025-05-05",
        # "keywordLoc": "title",
        # "keywordSearchMode": "simple",
        # "minArticlesInEvent": 1,
        # "maxArticlesInEvent": ,
    # }
    # return _fetch_topic(base_query, "elections")

def fetch_security(date_start, date_end):
    """Fetch security and conflict-related articles."""
    base_query = {
        # "conceptUri": "",
        # "keyword": "",
        "categoryUri": {
            "$or": [
                "dmoz/Business",
                "dmoz/Society/Politics",
                "dmoz/Society/Government/Foreign_Ministries",
                "dmoz/Society/Issues/Warfare_and_Conflict",
                "dmoz/Society/Issues/Human_Rights",
                "dmoz/Regional/Asia",
                "dmoz/World"
            ]
        },
        "lang": "eng",
        "sourceUri": {"$or":["channelnewsasia.com","straitstimes.com"]},
        # "sourceLocationUri": "",
        # "sourceGroupUri": "",
        # "authorUri": "",
        # "locationUri": "",
        "dateStart": date_start,
        "dateEnd": date_end,
        # "dateMention": "2025-05-05",
        # "keywordLoc": "title",
        # "keywordSearchMode": "simple",
        "minArticlesInEvent": 1,
        # "maxArticlesInEvent": ,
    }
    return _fetch_topic(base_query, "security")

def fetch_tariffs(date_start, date_end):
    """Fetch tariff-related articles."""
    base_query = {
        "conceptUri": {"$and": ["https://en.wikipedia.org/wiki/Tariff"]},
        "keyword": {"$or": ["tariff", "tariffs", "geopolitics", "foreign policy", "diplomacy", "international relations"]},
        "categoryUri": "dmoz/Business",
        "lang": "eng",
        "sourceUri": {"$or":["channelnewsasia.com","straitstimes.com"]},
        # "sourceLocationUri": "",
        # "sourceGroupUri": "",
        # "authorUri": "",
        # "locationUri": "",
        "dateStart": date_start,
        "dateEnd": date_end,
        # "dateMention": "2025-05-05",
        "keywordLoc": "title",
        "keywordSearchMode": "simple",
        "minArticlesInEvent": 1,
        # "maxArticlesInEvent": 9999,
    }
    return _fetch_topic(base_query, "tariffs")

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

def _fetch_topic(base_query, topic_name):
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
        data["category"] = "geopolitics"
        data["sub-category"] = topic_name
        articles.append(data)
    print(f"Retrieved {len(articles)} articles for sub-category: {topic_name}")
    return articles

def save_articles_to_db(df):
    """
    Save articles DataFrame to PostgreSQL 'articles' table.
    """
    if df.empty:
        print("⚠️ No articles to save.")
        return

    try:
        conn = psycopg2.connect(DATABASE_URL)
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
                row.get("sub-category"),
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
    all_articles.extend(fetch_security(today, today))
    all_articles.extend(fetch_tariffs(today, today))
    all_articles.extend(fetch_trump(today, today))

    df = pd.DataFrame(all_articles)
    save_articles_to_db(df)
    print(f"Exported {len(df)} total articles into the database.")

if __name__ == "__main__":
    main()
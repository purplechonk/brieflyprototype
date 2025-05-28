import os
import pandas as pd
from datetime import datetime
import psycopg2
from dotenv import load_dotenv

# Load environment variables
load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")

def filter_articles_from_db():
    today = datetime.now().date()

    # Connect to PostgreSQL
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()

    # Load today's deduplicated articles
    df = pd.read_sql("""
        SELECT * FROM articles
        WHERE created_at::date = %s
    """, conn, params=(today,))

    if df.empty:
        print("⚠️ No articles to filter for today.")
        return

    original_count = len(df)

    # Apply filtering rules
    passed = df[(df['sentiment'] > -0.5) & (df['body'].str.len() > 500)]
    failed = df[~df.index.isin(passed.index)]

    # Delete failing articles from DB
    for uri in failed["uri"]:
        cur.execute("DELETE FROM articles WHERE uri = %s AND created_at::date = %s", (uri, today))

    conn.commit()

    print(f"✅ Filtered {len(passed)} / {original_count} articles.")
    cur.close()
    conn.close()

if __name__ == "__main__":
    filter_articles_from_db()

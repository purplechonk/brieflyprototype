import pandas as pd
import psycopg2
from dotenv import load_dotenv
from datetime import datetime
import os

# Load DB credentials
load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")

def deduplicate_today_articles():
    today = datetime.now().date()

    # Connect to database
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()

    # Load only today’s articles
    df = pd.read_sql("""
        SELECT * FROM articles
        WHERE created_at::date = %s
    """, conn, params=(today,))

    if df.empty:
        print("⚠️ No articles found for today.")
        return

    # Deduplicate by URI
    df_sorted = df.sort_values(by="uri")
    df_deduped = df_sorted.drop_duplicates(subset="uri").reset_index(drop=True)

    # Delete today’s raw articles
    cur.execute("DELETE FROM articles WHERE created_at::date = %s", (today,))

    # Reinsert clean articles
    for _, row in df_deduped.iterrows():
        cur.execute("""
            INSERT INTO articles (
                uri, title, body, url, published_at,
                sentiment, source, topic, created_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            row["uri"], row["title"], row["body"], row["url"], row["published_at"],
            row["sentiment"], row["source"], row["topic"], row["created_at"]
        ))

    conn.commit()
    cur.close()
    conn.close()

    print(f"✅ Deduplicated {len(df_deduped)} articles for {today}.")

if __name__ == "__main__":
    deduplicate_today_articles()

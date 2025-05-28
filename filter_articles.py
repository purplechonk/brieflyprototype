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
    df = df[df['sentiment'] > -0.5]
    df = df[df['body'].str.len() > 500]

    # Save for manual review or downstream use
    output_dir = os.path.join("output", today.strftime('%Y-%m-%d'))
    os.makedirs(output_dir, exist_ok=True)
    filtered_csv = os.path.join(output_dir, "geopol_articles_final.csv")
    df.to_csv(filtered_csv, index=False)

    print(f"✅ Filtered {len(df)} out of {original_count} articles.")

    conn.close()

if __name__ == "__main__":
    filter_articles_from_db()

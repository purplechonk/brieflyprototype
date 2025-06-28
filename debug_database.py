import os
import psycopg2
from dotenv import load_dotenv

# Load environment variables
load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")

def inspect_database():
    """Inspect database structure and data"""
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()
        
        print("=== DATABASE INSPECTION ===\n")
        
        # 1. Show table schema for articles
        print("1. ARTICLES TABLE SCHEMA:")
        cursor.execute("""
            SELECT column_name, data_type, is_nullable 
            FROM information_schema.columns 
            WHERE table_name = 'articles' 
            ORDER BY ordinal_position;
        """)
        schema = cursor.fetchall()
        for col in schema:
            print(f"  - {col[0]}: {col[1]} ({'NULL' if col[2] == 'YES' else 'NOT NULL'})")
        
        print("\n" + "="*50 + "\n")
        
        # 2. Show table schema for user_interactions
        print("2. USER_INTERACTIONS TABLE SCHEMA:")
        cursor.execute("""
            SELECT column_name, data_type, is_nullable 
            FROM information_schema.columns 
            WHERE table_name = 'user_interactions' 
            ORDER BY ordinal_position;
        """)
        schema = cursor.fetchall()
        for col in schema:
            print(f"  - {col[0]}: {col[1]} ({'NULL' if col[2] == 'YES' else 'NOT NULL'})")
        
        print("\n" + "="*50 + "\n")
        
        # 3. Count total articles
        print("3. ARTICLE COUNTS:")
        cursor.execute("SELECT COUNT(*) FROM articles;")
        total_articles = cursor.fetchone()[0]
        print(f"  - Total articles: {total_articles}")
        
        # 4. Show unique categories
        print("\n4. UNIQUE CATEGORIES:")
        cursor.execute("SELECT DISTINCT category, COUNT(*) FROM articles GROUP BY category ORDER BY COUNT(*) DESC;")
        categories = cursor.fetchall()
        for cat, count in categories:
            print(f"  - '{cat}': {count} articles")
        
        print("\n" + "="*50 + "\n")
        
        # 5. Show sample articles with categories
        print("5. SAMPLE ARTICLES (first 5):")
        cursor.execute("""
            SELECT uri, title, category, published_date 
            FROM articles 
            ORDER BY published_date DESC 
            LIMIT 5;
        """)
        samples = cursor.fetchall()
        for i, (uri, title, category, pub_date) in enumerate(samples, 1):
            print(f"  {i}. Category: '{category}'")
            print(f"     Title: {title[:60]}...")
            print(f"     Date: {pub_date}")
            print(f"     URI: {uri[:50]}...")
            print()
        
        # 6. Show articles from today
        print("6. TODAY'S ARTICLES:")
        cursor.execute("""
            SELECT COUNT(*), category 
            FROM articles 
            WHERE published_date >= CURRENT_DATE 
            GROUP BY category 
            ORDER BY COUNT(*) DESC;
        """)
        today_articles = cursor.fetchall()
        if today_articles:
            for count, category in today_articles:
                print(f"  - '{category}': {count} articles today")
        else:
            print("  - No articles from today")
        
        print("\n" + "="*50 + "\n")
        
        # 7. Check recent articles (last 7 days)
        print("7. RECENT ARTICLES (last 7 days):")
        cursor.execute("""
            SELECT COUNT(*), category 
            FROM articles 
            WHERE published_date >= CURRENT_DATE - INTERVAL '7 days'
            GROUP BY category 
            ORDER BY COUNT(*) DESC;
        """)
        recent_articles = cursor.fetchall()
        if recent_articles:
            for count, category in recent_articles:
                print(f"  - '{category}': {count} articles (last 7 days)")
        else:
            print("  - No articles from last 7 days")
        
        cursor.close()
        conn.close()
        
        print("\n" + "="*50)
        print("DATABASE INSPECTION COMPLETE")
        
    except Exception as e:
        print(f"Error inspecting database: {e}")
        import traceback
        print(traceback.format_exc())

if __name__ == "__main__":
    inspect_database() 
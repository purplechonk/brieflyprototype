import os
import pandas as pd
import psycopg2
from datetime import datetime
from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (Updater, CallbackContext, CommandHandler, CallbackQueryHandler,
                          ConversationHandler, MessageHandler, Filters)

# Load environment variables
load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

LOOKBACK_DAYS = 3

# Define conversation states
ASK_USEFUL, ASK_CATEGORY, ASK_SUBCATEGORY, ASK_PURPOSE = range(4)

# Categories and Subcategories
CATEGORIES = {
    "Geopolitics": ["Great-Power Competition", "Conflict and Security", "International Trade", "International Institutions"],
    "Economy": ["Economic Data and Outlook", "Economic Policy", "Financial Markets", "Southeast Asian Economies"],
    "Technology": ["Artificial Intelligence", "Digital Transformation and Automation", "Cybersecurity and Data Privacy", "Emerging Technologies"],
    "ESG": ["Climate News and Agreements", "Renewable Energy", "Diversity, Equity and Inclusion", "Governance"],
    "Businesses": ["Companies", "Mergers and Acquisitions", "Property and Infrastructure", "Startups"],
    "Government": ["Southeast Asian Politics", "Government Initiatives", "Technology Regulation and Policy", "Climate Regulation and Policy"],
    "Society": ["Consumer Trends"]
}

user_sessions = {}

def get_connection():
    try:
        return psycopg2.connect(DATABASE_URL, sslmode='require')
    except psycopg2.OperationalError as e:
        print(f"❌ Database connection failed: {e}")
        print(f"🔍 DATABASE_URL: {DATABASE_URL[:50]}...")  # Show partial URL for debugging
        raise e

def load_articles():
    try:
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT uri, title, body, url, category, sub_category FROM articles
                    WHERE created_at >= CURRENT_DATE - INTERVAL '%s days'
                """, (LOOKBACK_DAYS,))
                return pd.DataFrame(cur.fetchall(), columns=["uri", "title", "body", "url", "article_category", "article_subcategory"])
        finally:
            conn.close()
    except Exception as e:
        print(f"❌ Error loading articles: {e}")
        return pd.DataFrame()  # Return empty DataFrame on error

def get_labeled_uris(user_id):
    print(f"🔍 DEBUG: Getting labeled URIs for user {user_id}")
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT uri FROM detailed_labels WHERE user_id = %s", (user_id,))
            uris = set(row[0] for row in cur.fetchall())
            print(f"🔍 DEBUG: Found {len(uris)} labeled URIs for user {user_id}")
            return uris
    except Exception as e:
        print(f"❌ ERROR: Failed to get labeled URIs: {e}")
        return set()
    finally:
        conn.close()

def save_detailed_label(user_id, session):
    print(f"🔍 DEBUG: Attempting to save label for user {user_id}")
    print(f"🔍 DEBUG: Session data: {session}")
    
    try:
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                print(f"🔍 DEBUG: Executing UPDATE/INSERT query...")
                
                # Check if purpose column exists
                cur.execute("""
                    SELECT column_name FROM information_schema.columns 
                    WHERE table_name = 'detailed_labels' AND column_name = 'purpose'
                """)
                has_purpose_column = cur.fetchone() is not None
                print(f"🔍 DEBUG: Purpose column exists: {has_purpose_column}")
                
                if has_purpose_column:
                    # Update with purpose column
                    cur.execute("""
                        UPDATE detailed_labels 
                        SET useful = %s, category = %s, subcategory = %s, purpose = %s
                        WHERE user_id = %s AND uri = %s
                    """, (session['useful'], session.get('category'), session.get('subcategory'), 
                         session.get('purpose'), user_id, session['uri']))
                    
                    if cur.rowcount == 0:
                        cur.execute("""
                            INSERT INTO detailed_labels (user_id, uri, useful, category, subcategory, purpose)
                            VALUES (%s, %s, %s, %s, %s, %s)
                        """, (user_id, session['uri'], session['useful'], session.get('category'), 
                             session.get('subcategory'), session.get('purpose')))
                else:
                    # Update without purpose column
                    cur.execute("""
                        UPDATE detailed_labels 
                        SET useful = %s, category = %s, subcategory = %s
                        WHERE user_id = %s AND uri = %s
                    """, (session['useful'], session.get('category'), session.get('subcategory'), 
                         user_id, session['uri']))
                    
                    if cur.rowcount == 0:
                        cur.execute("""
                            INSERT INTO detailed_labels (user_id, uri, useful, category, subcategory)
                            VALUES (%s, %s, %s, %s, %s)
                        """, (user_id, session['uri'], session['useful'], session.get('category'), 
                             session.get('subcategory')))
                
                print(f"🔍 DEBUG: UPDATE affected {cur.rowcount} rows")
                print(f"🔍 DEBUG: Query executed, committing transaction...")
            conn.commit()
            print(f"✅ DEBUG: Label saved successfully for user {user_id}, URI: {session['uri']}")
        finally:
            conn.close()
    except Exception as e:
        print(f"❌ ERROR: Failed to save label: {e}")
        print(f"❌ ERROR: Exception type: {type(e).__name__}")
        if 'conn' in locals():
            try:
                conn.rollback()
                conn.close()
            except:
                pass
        raise e

def get_last_labeled_article(user_id):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            # Check if purpose column exists
            cur.execute("""
                SELECT column_name FROM information_schema.columns 
                WHERE table_name = 'detailed_labels' AND column_name = 'purpose'
            """)
            has_purpose_column = cur.fetchone() is not None
            
            if has_purpose_column:
                cur.execute("""
                    SELECT uri, category, subcategory, purpose FROM detailed_labels
                    WHERE user_id = %s ORDER BY id DESC LIMIT 1
                """, (user_id,))
                row = cur.fetchone()
                return row if row else None
            else:
                cur.execute("""
                    SELECT uri, category, subcategory FROM detailed_labels
                    WHERE user_id = %s ORDER BY id DESC LIMIT 1
                """, (user_id,))
                row = cur.fetchone()
                if row:
                    # Add None for purpose to maintain compatibility
                    return row + (None,)
                return None
    finally:
        conn.close()

def start(update: Update, context: CallbackContext):
    user = update.effective_user
    welcome_message = (
        f"\U0001F44B Hello {user.first_name}!\n"
        "Welcome to the News Labeling Bot.\n\n"
        "Use /label to begin tagging articles, /status to check progress, or /redo to update your last label."
    )
    update.message.reply_text(welcome_message)

def status(update: Update, context: CallbackContext):
    user_id = update.message.chat_id
    try:
        df = load_articles()
        if df.empty:
            update.message.reply_text("⚠️ No articles available or database connection issue.")
            return
            
        available_uris = set(df["uri"])
        labeled_uris = get_labeled_uris(user_id)
        labeled = len(available_uris & labeled_uris)
        total = len(df)
        remaining = total - labeled
        update.message.reply_text(f"📊 Status:\nTotal Articles: {total}\nYou've Labeled: {labeled}\nRemaining: {remaining}")
    except Exception as e:
        print(f"❌ Error in status command: {e}")
        update.message.reply_text("❌ Database connection error. Please try again later.")

def redo(update: Update, context: CallbackContext):
    user_id = update.message.chat_id
    last = get_last_labeled_article(user_id)
    if not last:
        update.message.reply_text("No recent labeled article found to redo.")
        return ConversationHandler.END

    uri, category, subcategory, purpose = last
    df = load_articles()
    article = df[df["uri"] == uri]
    if article.empty:
        update.message.reply_text("The last labeled article is no longer available.")
        return ConversationHandler.END

    article = article.iloc[0]
    user_sessions[user_id] = {"uri": uri}
    text = (
        f"🔄 *Redoing last labeled article:*\n\n"
        f"*{article['title']}*\n\n"
        f"{article['body'][:500]}...\n\n"
        f"[Read more]({article['url']})\n\n"
        f"📂 *Suggested Category:* {article['article_category']}\n"
        f"🔖 *Suggested Subcategory:* {article['article_subcategory']}\n\n"
        f"*Previous Labels:*\n"
        f"Category: {category or 'N/A'}\n"
        f"Subcategory: {subcategory or 'N/A'}\n"
        f"Purpose: {purpose or 'N/A'}"
    )
    buttons = [[
        InlineKeyboardButton("👍 Useful", callback_data="useful|yes"),
        InlineKeyboardButton("👎 Not Useful", callback_data="useful|no")
    ]]
    update.message.reply_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(buttons))
    return ASK_USEFUL

def ask_category(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    user_id = query.message.chat_id
    is_useful = query.data.endswith("yes")
    user_sessions[user_id]['useful'] = is_useful

    print(f"🔍 DEBUG: ask_category called for user {user_id}, useful: {is_useful}")

    if not is_useful:
        print(f"🔍 DEBUG: Article marked as not useful, saving label...")
        print(f"🔍 DEBUG: Session data before save: {user_sessions[user_id]}")
        
        try:
            save_detailed_label(user_id, user_sessions[user_id])
            print(f"✅ DEBUG: Not useful label saved successfully")
            
            df = load_articles()
            available_uris = set(df["uri"])
            labeled_uris = get_labeled_uris(user_id)
            labeled = len(available_uris & labeled_uris)
            total = len(df)
            remaining = total - labeled
            
            success_message = f"❌ Marked as Not Useful.\n\n📊 Status:\nTotal Articles: {total}\nYou've Labeled: {labeled}\nRemaining: {remaining}\n\nUse /label to tag another article."
            print(f"🔍 DEBUG: Sending not useful message: {success_message}")
            
            query.edit_message_text(success_message)
            
            # Clean up session
            if user_id in user_sessions:
                del user_sessions[user_id]
                
        except Exception as e:
            print(f"❌ ERROR: Exception saving not useful label: {e}")
            query.edit_message_text(f"❌ Error saving label: {str(e)}\n\nPlease try again with /label")
            
        return ConversationHandler.END

    buttons = [[InlineKeyboardButton(cat, callback_data=f"cat|{cat}")] for cat in CATEGORIES.keys()]
    query.edit_message_text("Which category does this article fall under?", reply_markup=InlineKeyboardMarkup(buttons))
    return ASK_CATEGORY

def ask_subcategory(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    user_id = query.message.chat_id
    category = query.data.split("|")[1]
    user_sessions[user_id]['category'] = category

    buttons = [[InlineKeyboardButton(sub, callback_data=f"subcat|{sub}")] for sub in CATEGORIES[category]]
    query.edit_message_text(f"Select a subcategory for *{category}*:", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(buttons))
    return ASK_SUBCATEGORY

def ask_purpose(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    user_id = query.message.chat_id
    subcategory = query.data.split("|")[1]
    user_sessions[user_id]['subcategory'] = subcategory

    buttons = [[
        InlineKeyboardButton("Summary", callback_data="purpose|summary"),
        InlineKeyboardButton("Insights", callback_data="purpose|insights"),
        InlineKeyboardButton("Both", callback_data="purpose|both")
    ]]
    query.edit_message_text("What is this article best used for?", reply_markup=InlineKeyboardMarkup(buttons))
    return ASK_PURPOSE

def label(update: Update, context: CallbackContext):
    user_id = update.message.chat_id
    try:
        df = load_articles()
        if df.empty:
            update.message.reply_text("⚠️ No articles available or database connection issue.")
            return ConversationHandler.END
            
        labeled_uris = get_labeled_uris(user_id)
        remaining_df = df[~df['uri'].isin(labeled_uris)]

        if remaining_df.empty:
            update.message.reply_text("🎉 You've labeled all available articles.")
            return ConversationHandler.END

        article = remaining_df.iloc[0]
        user_sessions[user_id] = {"uri": article["uri"]}
        text = (
            f"*{article['title']}*\n\n"
            f"{article['body'][:500]}...\n\n"
            f"[Read more]({article['url']})\n\n"
            f"📂 *Suggested Category:* {article['article_category']}\n"
            f"🔖 *Suggested Subcategory:* {article['article_subcategory']}"
        )

        buttons = [[
            InlineKeyboardButton("👍 Useful", callback_data="useful|yes"),
            InlineKeyboardButton("👎 Not Useful", callback_data="useful|no")
        ]]
        update.message.reply_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(buttons))
        return ASK_USEFUL
    except Exception as e:
        print(f"❌ Error in label command: {e}")
        update.message.reply_text("❌ Database connection error. Please try again later.")
        return ConversationHandler.END


def end_label(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    user_id = query.message.chat_id
    purpose = query.data.split("|")[1]

    print(f"🔍 DEBUG: end_label called for user {user_id}, purpose: {purpose}")
    
    if user_id not in user_sessions:
        print(f"❌ DEBUG: No session found for user {user_id}")
        query.edit_message_text("⚠️ Session expired or not found. Please use /label to restart.")
        return ConversationHandler.END

    user_sessions[user_id]['purpose'] = purpose
    print(f"🔍 DEBUG: Final session data: {user_sessions[user_id]}")
    
    try:
        save_detailed_label(user_id, user_sessions[user_id])
        print(f"✅ DEBUG: Label saved successfully, updating UI...")
        
        df = load_articles()
        available_uris = set(df["uri"])
        labeled_uris = get_labeled_uris(user_id)
        labeled = len(available_uris & labeled_uris)
        total = len(df)
        remaining = total - labeled
        
        success_message = f"✅ Label saved!\n\n📊 Status:\nTotal Articles: {total}\nYou've Labeled: {labeled}\nRemaining: {remaining}\n\nUse /label to tag another article."
        print(f"🔍 DEBUG: Sending success message: {success_message}")
        
        query.edit_message_text(success_message)
        
        # Clean up session
        if user_id in user_sessions:
            del user_sessions[user_id]
            
    except Exception as e:
        print(f"❌ ERROR: Exception in end_label: {e}")
        query.edit_message_text(f"❌ Error saving label: {str(e)}\n\nPlease try again with /label")
    
    return ConversationHandler.END


def cancel(update: Update, context: CallbackContext):
    update.message.reply_text("Labelling cancelled.")
    return ConversationHandler.END

def test_database(update: Update, context: CallbackContext):
    """Test database connection and table structure"""
    user_id = update.message.chat_id
    
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            # Test connection
            cur.execute("SELECT version();")
            version = cur.fetchone()[0]
            update.message.reply_text(f"✅ Database connected!\nPostgreSQL version: {version}")
            
            # Check if detailed_labels table exists
            cur.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_name = 'detailed_labels'
                );
            """)
            table_exists = cur.fetchone()[0]
            
            if table_exists:
                # Get table structure
                cur.execute("""
                    SELECT column_name, data_type, is_nullable
                    FROM information_schema.columns
                    WHERE table_name = 'detailed_labels'
                    ORDER BY ordinal_position;
                """)
                columns = cur.fetchall()
                
                structure = "📋 detailed_labels table structure:\n"
                for col_name, data_type, nullable in columns:
                    structure += f"• {col_name}: {data_type} ({'NULL' if nullable == 'YES' else 'NOT NULL'})\n"
                
                # Check existing data
                cur.execute("SELECT COUNT(*) FROM detailed_labels;")
                count = cur.fetchone()[0]
                structure += f"\n📊 Total records: {count}"
                
                # Check user's data
                cur.execute("SELECT COUNT(*) FROM detailed_labels WHERE user_id = %s;", (user_id,))
                user_count = cur.fetchone()[0]
                structure += f"\n👤 Your records: {user_count}"
                
                update.message.reply_text(structure)
            else:
                update.message.reply_text("❌ detailed_labels table does not exist!")
                
        conn.close()
        
    except Exception as e:
        update.message.reply_text(f"❌ Database error: {str(e)}")

def main():
    # Updated conv_handler to include /redo as an entry point

    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('label', label), CommandHandler('redo', redo)],
        states={
            ASK_USEFUL: [CallbackQueryHandler(ask_category, pattern="^useful\\|")],
            ASK_CATEGORY: [CallbackQueryHandler(ask_subcategory, pattern="^cat\\|")],
            ASK_SUBCATEGORY: [CallbackQueryHandler(ask_purpose, pattern="^subcat\\|")],
            ASK_PURPOSE: [CallbackQueryHandler(end_label, pattern="^purpose\\|")],
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )

    dp.add_handler(CommandHandler('start', start))
    dp.add_handler(CommandHandler('status', status))
    dp.add_handler(CommandHandler('test', test_database))  # Add test command
    # Removed standalone redo handler to avoid conflicts
    # dp.add_handler(CommandHandler('redo', redo))
    dp.add_handler(conv_handler)

    print("\u2705 Detailed labeling bot running...")
    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()

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

# Define conversation states
CHOOSING_CATEGORY, READING_NEWS = range(2)

# Store user sessions
user_sessions = {}

def get_connection():
    try:
        return psycopg2.connect(DATABASE_URL, sslmode='require')
    except psycopg2.OperationalError as e:
        print(f"❌ Database connection failed: {e}")
        print(f"🔍 DATABASE_URL: {DATABASE_URL[:50]}...")  # Show partial URL for debugging
        raise e

def load_articles(category):
    """Load articles from database based on category"""
    try:
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                if category == "geopolitics":
                    cur.execute("""
                        SELECT uri, title, body, url FROM articles
                        WHERE category = 'Geopolitics'
                        ORDER BY published_at DESC
                    """)
                else:  # singapore news
                    cur.execute("""
                        SELECT uri, title, body, url FROM articles
                        WHERE source IN ('channelnewsasia.com', 'straitstimes.com')
                        AND category != 'Geopolitics'
                        ORDER BY published_at DESC
                    """)
                return pd.DataFrame(cur.fetchall(), columns=["uri", "title", "body", "url"])
        finally:
            conn.close()
    except Exception as e:
        print(f"❌ Error loading articles: {e}")
        return pd.DataFrame()

def save_user_response(user_id, uri, response):
    """Save user's like/dislike response"""
    try:
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO user_responses (user_id, uri, response)
                    VALUES (%s, %s, %s)
                """, (user_id, uri, response))
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        print(f"❌ Error saving response: {e}")

def start(update: Update, context: CallbackContext):
    """Start the conversation and ask for category choice"""
    keyboard = [
        [
            InlineKeyboardButton("Geopolitics News", callback_data="geopolitics"),
            InlineKeyboardButton("Singapore News", callback_data="singapore")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    update.message.reply_text(
        "Welcome! Please choose a news category:",
        reply_markup=reply_markup
    )
    return CHOOSING_CATEGORY

def show_article(update: Update, context: CallbackContext, show_full=False):
    """Show article with options"""
    user_id = update.effective_user.id
    session = user_sessions.get(user_id)
    
    if not session or session['current_index'] >= len(session['articles']):
        update.callback_query.message.reply_text("No more articles available.")
        return ConversationHandler.END
    
    article = session['articles'].iloc[session['current_index']]
    
    if show_full:
        text = f"*{article['title']}*\n\n{article['body']}\n\nOriginal article: {article['url']}"
        keyboard = [
            [InlineKeyboardButton("Next Article", callback_data="next")]
        ]
    else:
        # Show only first 200 characters of body
        preview = article['body'][:200] + "..."
        text = f"*{article['title']}*\n\n{preview}"
        keyboard = [
            [
                InlineKeyboardButton("👍 Like", callback_data="like"),
                InlineKeyboardButton("👎 Dislike", callback_data="dislike"),
            ],
            [InlineKeyboardButton("📖 Read More", callback_data="read_more")]
        ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Edit the message if it exists, otherwise send new message
    if update.callback_query:
        update.callback_query.message.edit_text(
            text,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    else:
        update.message.reply_text(
            text,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    
    return READING_NEWS

def handle_category_choice(update: Update, context: CallbackContext):
    """Handle category selection"""
    query = update.callback_query
    user_id = update.effective_user.id
    
    # Load articles based on category
    articles = load_articles(query.data)
    
    if articles.empty:
        query.message.reply_text("No articles available at the moment.")
        return ConversationHandler.END
    
    # Initialize user session
    user_sessions[user_id] = {
        'articles': articles,
        'current_index': 0
    }
    
    # Show first article
    return show_article(update, context)

def handle_article_response(update: Update, context: CallbackContext):
    """Handle user's response to an article"""
    query = update.callback_query
    user_id = update.effective_user.id
    session = user_sessions.get(user_id)
    
    if query.data in ['like', 'dislike']:
        # Save response
        current_article = session['articles'].iloc[session['current_index']]
        save_user_response(user_id, current_article['uri'], query.data)
        
        # Move to next article
        session['current_index'] += 1
        return show_article(update, context)
    
    elif query.data == 'read_more':
        return show_article(update, context, show_full=True)
    
    elif query.data == 'next':
        session['current_index'] += 1
        return show_article(update, context)

def main():
    """Start the bot"""
    # Create the Updater and pass it your bot's token
    updater = Updater(TOKEN)

    # Get the dispatcher to register handlers
    dp = updater.dispatcher

    # Add conversation handler
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            CHOOSING_CATEGORY: [
                CallbackQueryHandler(handle_category_choice)
            ],
            READING_NEWS: [
                CallbackQueryHandler(handle_article_response)
            ]
        },
        fallbacks=[],
    )

    dp.add_handler(conv_handler)

    # Start the Bot
    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()

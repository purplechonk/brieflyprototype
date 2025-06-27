import os
import sys
import psycopg2
from datetime import datetime
from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ConversationHandler, ContextTypes
from flask import Flask, request
import asyncio
import threading
import logging

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

print(f"Bot token present: {bool(TOKEN)}", flush=True)
print(f"Database URL present: {bool(DATABASE_URL)}", flush=True)

# Create Flask app
app = Flask(__name__)

@app.route('/', methods=['GET'])
def health_check():
    return 'Telegram bot service is running'

@app.route('/webhook', methods=['POST'])
def webhook():
    """Handle webhook updates from Telegram"""
    return 'OK'

# Define conversation states
CHOOSING_CATEGORY, READING_NEWS = range(2)

# Store user sessions
user_sessions = {}

def get_connection():
    """Get database connection with retry logic"""
    try:
        return psycopg2.connect(DATABASE_URL)
    except psycopg2.OperationalError as e:
        logger.error(f"Database connection failed: {e}")
        print(f"❌ Database connection failed: {e}", flush=True)
        print(f"🔍 DATABASE_URL: {DATABASE_URL[:50] if DATABASE_URL else 'None'}...", flush=True)
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
                        WHERE category LIKE '%Geopolitics%'
                        ORDER BY created_at DESC
                        LIMIT 10
                    """)
                else:  # singapore news
                    cur.execute("""
                        SELECT uri, title, body, url FROM articles
                        WHERE category LIKE '%Singapore%'
                        ORDER BY created_at DESC
                        LIMIT 10
                    """)
                
                articles = cur.fetchall()
                logger.info(f"Loaded {len(articles)} articles for category: {category}")
                return articles
        finally:
            conn.close()
    except Exception as e:
        logger.error(f"Error loading articles: {e}")
        print(f"❌ Error loading articles: {e}", flush=True)
        return []

def save_user_response(user_id, uri, response):
    """Save user's like/dislike response"""
    try:
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                # Check if user_responses table exists, if not create it
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS user_responses (
                        id SERIAL PRIMARY KEY,
                        user_id BIGINT NOT NULL,
                        uri TEXT NOT NULL,
                        response TEXT NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                
                cur.execute("""
                    INSERT INTO user_responses (user_id, uri, response)
                    VALUES (%s, %s, %s)
                """, (user_id, uri, response))
            conn.commit()
            logger.info(f"Saved user response: {user_id} -> {response}")
        finally:
            conn.close()
    except Exception as e:
        logger.error(f"Error saving response: {e}")
        print(f"❌ Error saving response: {e}", flush=True)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start the conversation and ask for category choice"""
    keyboard = [
        [
            InlineKeyboardButton("🌍 Geopolitics News", callback_data="geopolitics"),
            InlineKeyboardButton("🇸🇬 Singapore News", callback_data="singapore")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "Welcome to Briefly News Bot! 📰\n\nPlease choose a news category:",
        reply_markup=reply_markup
    )
    return CHOOSING_CATEGORY

async def show_article(update: Update, context: ContextTypes.DEFAULT_TYPE, show_full=False):
    """Show article with options"""
    user_id = update.effective_user.id
    session = user_sessions.get(user_id)
    
    if not session or session['current_index'] >= len(session['articles']):
        await update.callback_query.message.reply_text("No more articles available. Use /start to begin again.")
        return ConversationHandler.END
    
    article = session['articles'][session['current_index']]
    uri, title, body, url = article
    
    if show_full:
        text = f"*{title}*\n\n{body}\n\n🔗 [Read original article]({url})"
        keyboard = [
            [
                InlineKeyboardButton("👍 Like", callback_data="like"),
                InlineKeyboardButton("👎 Dislike", callback_data="dislike"),
            ],
            [InlineKeyboardButton("➡️ Next Article", callback_data="next")]
        ]
    else:
        # Show only first 300 characters of body
        preview = body[:300] + "..." if len(body) > 300 else body
        text = f"*{title}*\n\n{preview}"
        keyboard = [
            [
                InlineKeyboardButton("👍 Like", callback_data="like"),
                InlineKeyboardButton("👎 Dislike", callback_data="dislike"),
            ],
            [InlineKeyboardButton("📖 Read More", callback_data="read_more")]
        ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    try:
        await update.callback_query.edit_message_text(
            text,
            reply_markup=reply_markup,
            parse_mode='Markdown',
            disable_web_page_preview=True
        )
    except Exception as e:
        logger.error(f"Error editing message: {e}")
        await update.callback_query.message.reply_text(
            text,
            reply_markup=reply_markup,
            parse_mode='Markdown',
            disable_web_page_preview=True
        )
    
    return READING_NEWS

async def handle_category_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle category selection"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    
    # Load articles based on category
    articles = load_articles(query.data)
    
    if not articles:
        await query.message.reply_text("No articles available at the moment. Please try again later.")
        return ConversationHandler.END
    
    # Initialize user session
    user_sessions[user_id] = {
        'articles': articles,
        'current_index': 0,
        'category': query.data
    }
    
    await query.message.reply_text(f"Loading {query.data} articles... 📰")
    
    # Show first article
    return await show_article(update, context)

async def handle_article_response(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle user's response to an article"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    session = user_sessions.get(user_id)
    
    if not session:
        await query.message.reply_text("Session expired. Use /start to begin again.")
        return ConversationHandler.END
    
    if query.data in ['like', 'dislike']:
        # Save response
        current_article = session['articles'][session['current_index']]
        uri = current_article[0]
        save_user_response(user_id, uri, query.data)
        
        # Show feedback
        feedback = "👍 Thanks for your feedback!" if query.data == 'like' else "👎 Thanks for your feedback!"
        await query.message.reply_text(feedback)
        
        # Move to next article
        session['current_index'] += 1
        return await show_article(update, context)
    
    elif query.data == 'read_more':
        return await show_article(update, context, show_full=True)
    
    elif query.data == 'next':
        session['current_index'] += 1
        return await show_article(update, context)

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel the conversation"""
    await update.message.reply_text("Goodbye! Use /start to begin again.")
    return ConversationHandler.END

def create_bot_application():
    """Create and configure the bot application"""
    if not TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not found!")
        return None
    
    # Create application
    application = Application.builder().token(TOKEN).build()
    
    # Add conversation handler
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            CHOOSING_CATEGORY: [
                CallbackQueryHandler(handle_category_choice)
            ],
            READING_NEWS: [
                CallbackQueryHandler(handle_article_response)
            ],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
    )
    
    application.add_handler(conv_handler)
    
    return application

def run_bot():
    """Run the bot in polling mode"""
    print("🔧 run_bot() function called", flush=True)
    
    try:
        print("🔧 Creating bot application...", flush=True)
        application = create_bot_application()
        
        if application:
            logger.info("Starting Telegram bot...")
            print("🤖 Starting Telegram bot polling...", flush=True)
            application.run_polling(drop_pending_updates=True)
            print("🤖 Bot polling ended", flush=True)
        else:
            logger.error("Failed to create bot application")
            print("❌ Failed to create bot application", flush=True)
    except Exception as e:
        print(f"❌ Error in run_bot(): {str(e)}", flush=True)
        logger.error(f"Error in run_bot(): {str(e)}")
        import traceback
        print(f"Traceback: {traceback.format_exc()}", flush=True)

def main():
    """Main function"""
    print("=== STARTING TELEGRAM BOT SERVICE ===", flush=True)
    print(f"Python version: {sys.version}", flush=True)
    print(f"Current working directory: {os.getcwd()}", flush=True)
    print(f"Environment variables: PORT={os.environ.get('PORT')}, TELEGRAM_BOT_TOKEN present: {bool(TOKEN)}", flush=True)
    
    logger.info("Starting Telegram bot service")
    
    if not TOKEN:
        print("CRITICAL ERROR: No TELEGRAM_BOT_TOKEN found!", flush=True)
        logger.error("No TELEGRAM_BOT_TOKEN found!")
        return
    
    print("Bot token is present, starting bot thread...", flush=True)
    
    # Start bot in a separate thread
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    
    print("Bot thread started, starting Flask server...", flush=True)
    
    # Start Flask server
    port = int(os.environ.get('PORT', 8080))
    print(f"Starting Flask server on port {port}", flush=True)
    logger.info(f"Starting Flask server on port {port}")
    
    try:
        print("About to start Flask app.run()...", flush=True)
        app.run(host='0.0.0.0', port=port, debug=False)
    except Exception as e:
        print(f"ERROR starting Flask server: {str(e)}", flush=True)
        logger.error(f"Error starting Flask server: {str(e)}")

if __name__ == "__main__":
    main()

#testtest
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

# Flask app for health checks
app = Flask(__name__)

@app.route('/')
def health_check():
    return "Telegram Bot is running!"

@app.route('/health')
def health():
    return {"status": "healthy", "service": "telegram-bot"}

# Bot conversation states
WAITING_FOR_LABEL = 1

def get_db_connection():
    """Get database connection"""
    try:
        conn = psycopg2.connect(DATABASE_URL)
        logger.info("Database connection successful")
        return conn
    except Exception as e:
        logger.error(f"Database connection failed: {str(e)}")
        return None

def get_unlabeled_articles_for_user(user_id, limit=10):
    """Get articles that haven't been labeled by this specific user yet"""
    print(f"🔍 Getting unlabeled articles for user {user_id}", flush=True)
    conn = get_db_connection()
    if not conn:
        print("❌ No database connection", flush=True)
        return []
    
    try:
        cursor = conn.cursor()
        print(f"🔍 Querying for today's articles...", flush=True)
        # Get articles from today that this user hasn't labeled yet
        cursor.execute("""
            SELECT a.uri, a.title, a.body, a.url, a.category, a.published_date
            FROM articles a
            LEFT JOIN user_interactions ui ON a.uri = ui.uri AND ui.user_id = %s 
                AND ui.interaction_type IN ('positive', 'negative', 'neutral')
            WHERE ui.id IS NULL
            AND a.published_date >= CURRENT_DATE
            ORDER BY a.published_date DESC 
            LIMIT %s
        """, (user_id, limit))
        articles = cursor.fetchall()
        print(f"🔍 Found {len(articles)} articles from today", flush=True)
        
        # If no articles from today, get recent unlabeled articles
        if not articles:
            print(f"🔍 No today's articles, getting recent ones...", flush=True)
            cursor.execute("""
                SELECT a.uri, a.title, a.body, a.url, a.category, a.published_date
                FROM articles a
                LEFT JOIN user_interactions ui ON a.uri = ui.uri AND ui.user_id = %s 
                    AND ui.interaction_type IN ('positive', 'negative', 'neutral')
                WHERE ui.id IS NULL
                ORDER BY a.published_date DESC 
                LIMIT %s
            """, (user_id, limit))
            articles = cursor.fetchall()
            print(f"🔍 Found {len(articles)} recent articles", flush=True)
        
        cursor.close()
        conn.close()
        logger.info(f"Found {len(articles)} unlabeled articles for user {user_id}")
        return articles
    except Exception as e:
        error_msg = f"Error fetching articles for user {user_id}: {str(e)}"
        logger.error(error_msg)
        print(f"❌ {error_msg}", flush=True)
        import traceback
        print(f"Traceback: {traceback.format_exc()}", flush=True)
        return []

def save_user_article_label(user_id, article_uri, label):
    """Save user's label for a specific article"""
    conn = get_db_connection()
    if not conn:
        return False
    
    try:
        cursor = conn.cursor()
        # Use INSERT ... ON CONFLICT to handle updates
        cursor.execute("""
            INSERT INTO user_interactions (user_id, uri, interaction_type)
            VALUES (%s, %s, %s)
            ON CONFLICT (user_id, uri)
            DO UPDATE SET 
                interaction_type = EXCLUDED.interaction_type,
                updated_at = CURRENT_TIMESTAMP
        """, (user_id, article_uri, label))
        conn.commit()
        cursor.close()
        conn.close()
        logger.info(f"Saved label '{label}' for user {user_id}, article {article_uri}")
        return True
    except Exception as e:
        logger.error(f"Error saving user label: {str(e)}")
        return False

def get_user_labeling_stats(user_id):
    """Get user's labeling statistics"""
    conn = get_db_connection()
    if not conn:
        return None
    
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT 
                COUNT(*) as total_labeled,
                COUNT(CASE WHEN interaction_type = 'positive' THEN 1 END) as positive_count,
                COUNT(CASE WHEN interaction_type = 'negative' THEN 1 END) as negative_count,
                COUNT(CASE WHEN interaction_type = 'neutral' THEN 1 END) as neutral_count
            FROM user_interactions 
            WHERE user_id = %s 
            AND interaction_type IN ('positive', 'negative', 'neutral')
        """, (user_id,))
        stats = cursor.fetchone()
        cursor.close()
        conn.close()
        return stats
    except Exception as e:
        logger.error(f"Error getting user stats: {str(e)}")
        return None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start command handler"""
    user = update.effective_user
    user_id = user.id
    logger.info(f"User {user.first_name} (ID: {user_id}) started the bot")
    
    # Get user's labeling stats
    stats = get_user_labeling_stats(user_id)
    stats_text = ""
    if stats:
        total, positive, negative, neutral = stats
        if total > 0:
            stats_text = f"\n📊 Your stats: {total} articles labeled ({positive} positive, {negative} negative, {neutral} neutral)"
    
    # Get articles this user hasn't labeled yet
    articles = get_unlabeled_articles_for_user(user_id)
    
    if not articles:
        await update.message.reply_text(
            f"🎉 Great job! You've labeled all available articles!{stats_text}\n\n"
            "New articles will be available after the next news collection (runs at midnight)."
        )
        return ConversationHandler.END
    
    # Store user info and articles in context
    context.user_data['user_id'] = user_id
    context.user_data['articles'] = articles
    context.user_data['current_index'] = 0
    
    # Send welcome message with stats
    welcome_msg = f"Welcome to Briefly News Labeling Bot! 📰{stats_text}\n\n"
    welcome_msg += f"You have {len(articles)} articles to label. Let's start!"
    
    await update.message.reply_text(welcome_msg)
    
    # Send first article
    return await send_article_for_labeling(update, context)

async def send_article_for_labeling(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Send article for user to label"""
    articles = context.user_data.get('articles', [])
    current_index = context.user_data.get('current_index', 0)
    
    if current_index >= len(articles):
        await update.message.reply_text("All articles have been processed! Thank you.")
        return ConversationHandler.END
    
    article = articles[current_index]
    article_uri, title, body, url, category, published_date = article
    
    # Store current article URI
    context.user_data['current_article_uri'] = article_uri
    
    # Create inline keyboard for labeling
    keyboard = [
        [InlineKeyboardButton("📈 Positive", callback_data="positive")],
        [InlineKeyboardButton("📉 Negative", callback_data="negative")],
        [InlineKeyboardButton("😐 Neutral", callback_data="neutral")],
        [InlineKeyboardButton("⏭️ Skip", callback_data="skip")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Format message
    message = f"**Article {current_index + 1}/{len(articles)}**\n\n"
    message += f"**Title:** {title}\n\n"
    message += f"**Category:** {category}\n\n"
    message += f"**Published:** {published_date.strftime('%Y-%m-%d %H:%M') if published_date else 'Unknown'}\n\n"
    message += f"**Content:** {body[:400]}{'...' if len(body) > 400 else ''}\n\n"
    message += f"**URL:** {url}\n\n"
    message += "Please select a label for this article:"
    
    if update.message:
        await update.message.reply_text(message, reply_markup=reply_markup, parse_mode='Markdown')
    else:
        await update.callback_query.message.reply_text(message, reply_markup=reply_markup, parse_mode='Markdown')
    
    return WAITING_FOR_LABEL

async def handle_label(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle user's label selection"""
    query = update.callback_query
    await query.answer()
    
    label = query.data
    user_id = context.user_data.get('user_id')
    article_uri = context.user_data.get('current_article_uri')
    current_index = context.user_data.get('current_index', 0)
    articles = context.user_data.get('articles', [])
    
    if label != "skip":
        # Save user's label for this article
        if save_user_article_label(user_id, article_uri, label):
            emoji = {"positive": "📈", "negative": "📉", "neutral": "😐"}.get(label, "✅")
            await query.edit_message_text(f"{emoji} Article labeled as: **{label}**", parse_mode='Markdown')
        else:
            await query.edit_message_text("❌ Error saving label")
    else:
        await query.edit_message_text("⏭️ Article skipped")
    
    # Move to next article
    context.user_data['current_index'] += 1
    
    # Check if this was the last article
    if context.user_data['current_index'] >= len(articles):
        # Get final stats
        stats = get_user_labeling_stats(user_id)
        if stats:
            total, positive, negative, neutral = stats
            final_msg = f"🎉 **Labeling session complete!**\n\n"
            final_msg += f"📊 **Your total stats:**\n"
            final_msg += f"• Total labeled: {total}\n"
            final_msg += f"• Positive: {positive}\n"
            final_msg += f"• Negative: {negative}\n"
            final_msg += f"• Neutral: {neutral}\n\n"
            final_msg += "Thank you for helping improve our news analysis! 🙏\n"
            final_msg += "Use /start again to label more articles."
            
            await query.message.reply_text(final_msg, parse_mode='Markdown')
        
        return ConversationHandler.END
    
    # Small delay before next article
    await asyncio.sleep(1)
    
    # Send next article
    return await send_article_for_labeling(update, context)

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show user's labeling statistics"""
    user = update.effective_user
    user_id = user.id
    
    stats = get_user_labeling_stats(user_id)
    if not stats or stats[0] == 0:
        await update.message.reply_text(
            "📊 **Your Labeling Stats**\n\n"
            "You haven't labeled any articles yet!\n"
            "Use /start to begin labeling articles.",
            parse_mode='Markdown'
        )
        return
    
    total, positive, negative, neutral = stats
    
    # Calculate percentages
    pos_pct = (positive / total * 100) if total > 0 else 0
    neg_pct = (negative / total * 100) if total > 0 else 0
    neu_pct = (neutral / total * 100) if total > 0 else 0
    
    stats_msg = f"📊 **Your Labeling Stats**\n\n"
    stats_msg += f"🏆 **Total articles labeled:** {total}\n\n"
    stats_msg += f"📈 **Positive:** {positive} ({pos_pct:.1f}%)\n"
    stats_msg += f"📉 **Negative:** {negative} ({neg_pct:.1f}%)\n"
    stats_msg += f"😐 **Neutral:** {neutral} ({neu_pct:.1f}%)\n\n"
    stats_msg += "Keep up the great work! 🙌"
    
    await update.message.reply_text(stats_msg, parse_mode='Markdown')

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel conversation"""
    await update.message.reply_text("Labeling session cancelled.")
    return ConversationHandler.END

def create_bot_application():
    """Create and configure the bot application"""
    print("🔧 create_bot_application() called", flush=True)
    
    if not TOKEN:
        error_msg = "TELEGRAM_BOT_TOKEN not found"
        logger.error(error_msg)
        print(f"❌ {error_msg}", flush=True)
        return None
    
    print(f"🔧 Token present: {TOKEN[:10]}...", flush=True)
    
    try:
        print("🔧 Testing token validity...", flush=True)
        # Test token by creating a simple bot instance
        from telegram import Bot
        test_bot = Bot(token=TOKEN)
        print("✅ Token appears valid", flush=True)
        
        print("🔧 Building application...", flush=True)
        application = Application.builder().token(TOKEN).build()
        print("✅ Application built successfully", flush=True)
        
        print("🔧 Adding simple command handlers first...", flush=True)
        # Add stats command handler first (simpler)
        application.add_handler(CommandHandler('stats', stats_command))
        print("✅ Stats handler added", flush=True)
        
        print("🔧 Creating conversation handler...", flush=True)
        # Create conversation handler
        try:
            conv_handler = ConversationHandler(
                entry_points=[CommandHandler('start', start)],
                states={
                    WAITING_FOR_LABEL: [CallbackQueryHandler(handle_label)]
                },
                fallbacks=[CommandHandler('cancel', cancel)]
            )
            print("✅ Conversation handler created", flush=True)
            
            print("🔧 Adding conversation handler to application...", flush=True)
            application.add_handler(conv_handler)
            print("✅ Conversation handler added", flush=True)
        except Exception as conv_error:
            print(f"❌ Error creating conversation handler: {conv_error}", flush=True)
            # Still add a basic start command
            application.add_handler(CommandHandler('start', start))
            print("✅ Basic start handler added instead", flush=True)
        
        logger.info("Bot application created successfully")
        print("✅ Bot application created successfully", flush=True)
        return application
        
    except Exception as e:
        error_msg = f"Error creating bot application: {str(e)}"
        logger.error(error_msg)
        print(f"❌ {error_msg}", flush=True)
        import traceback
        print(f"Traceback: {traceback.format_exc()}", flush=True)
        return None

def run_bot_sync():
    """Run the bot synchronously"""
    print("🔧 run_bot_sync() function called", flush=True)
    
    try:
        print("🔧 Creating bot application...", flush=True)
        application = create_bot_application()
        
        if application:
            logger.info("Starting Telegram bot...")
            print("🤖 Starting Telegram bot polling...", flush=True)
            
            # Use run_polling without custom event loop
            application.run_polling(
                drop_pending_updates=True,
                close_loop=False,
                stop_signals=None  # Disable signal handling in thread
            )
            print("🤖 Bot polling ended", flush=True)
        else:
            logger.error("Failed to create bot application")
            print("❌ Failed to create bot application", flush=True)
            
    except Exception as e:
        error_msg = f"Error in run_bot_sync(): {str(e)}"
        logger.error(error_msg)
        print(f"❌ {error_msg}", flush=True)
        import traceback
        print(f"Traceback: {traceback.format_exc()}", flush=True)

def main():
    """Main function"""
    print("=== STARTING TELEGRAM BOT SERVICE ===", flush=True)
    print(f"Python version: {sys.version}", flush=True)
    print(f"Current working directory: {os.getcwd()}", flush=True)
    print(f"Environment variables:", flush=True)
    print(f"  - PORT: {os.environ.get('PORT', 'Not set')}", flush=True)
    print(f"  - TELEGRAM_BOT_TOKEN present: {bool(TOKEN)}", flush=True)
    print(f"  - DATABASE_URL present: {bool(DATABASE_URL)}", flush=True)
    
    if not TOKEN:
        print("❌ TELEGRAM_BOT_TOKEN not found!", flush=True)
        logger.error("TELEGRAM_BOT_TOKEN not found")
        return
    
    if not DATABASE_URL:
        print("❌ DATABASE_URL not found!", flush=True)
        logger.error("DATABASE_URL not found")
        return
    
    logger.info("Starting Telegram bot service")
    
    # Start bot in a separate thread
    print("🚀 Starting bot thread...", flush=True)
    bot_thread = threading.Thread(target=run_bot_sync, daemon=True)
    bot_thread.start()
    print("✅ Bot thread started", flush=True)
    
    # Start Flask server
    port = int(os.environ.get('PORT', 8080))
    print(f"🌐 Starting Flask server on port {port}", flush=True)
    logger.info(f"Starting Flask server on port {port}")
    
    try:
        app.run(host='0.0.0.0', port=port, debug=False)
    except Exception as e:
        print(f"❌ ERROR starting Flask server: {str(e)}", flush=True)
        logger.error(f"Error starting Flask server: {str(e)}")

if __name__ == "__main__":
    main()

#testtest
import os
import sys
import asyncio
import logging
import threading
import queue
import json
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, ConversationHandler
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # Will be set by Cloud Run
PORT = int(os.getenv("PORT", 8080))

print(f"Bot token present: {bool(TOKEN)}", flush=True)
print(f"Database URL present: {bool(DATABASE_URL)}", flush=True)

# Bot conversation states
WAITING_FOR_CATEGORY = 1
WAITING_FOR_LABEL = 2

# Global application instance
application = None

def get_db_connection():
    """Get database connection"""
    try:
        conn = psycopg2.connect(DATABASE_URL)
        logger.info("Database connection successful")
        return conn
    except Exception as e:
        logger.error(f"Database connection failed: {str(e)}")
        return None

def get_unlabeled_articles_for_user(user_id, category=None, limit=10):
    """Get articles that haven't been labeled by this specific user yet"""
    print(f"🔍 Getting unlabeled articles for user {user_id}, category: {category}", flush=True)
    conn = get_db_connection()
    if not conn:
        print("❌ No database connection", flush=True)
        return []
    
    try:
        cursor = conn.cursor()
        
        # Build category filter
        category_filter = ""
        params = [user_id]
        
        if category:
            if category.lower() == 'geopolitics':
                category_filter = "AND LOWER(a.category) LIKE '%geopolitic%'"
            elif category.lower() == 'singapore':
                category_filter = "AND LOWER(a.category) LIKE '%singapore%'"
        
        # Get articles from today that this user hasn't labeled yet
        print(f"🔍 Querying for today's articles with category filter...", flush=True)
        query = f"""
            SELECT a.uri, a.title, a.body, a.url, a.category, a.published_date
            FROM articles a
            LEFT JOIN user_interactions ui ON a.uri = ui.uri AND ui.user_id = %s 
                AND ui.interaction_type IN ('positive', 'negative', 'neutral')
            WHERE ui.id IS NULL
            AND a.published_date >= CURRENT_DATE
            {category_filter}
            ORDER BY a.published_date DESC 
            LIMIT %s
        """
        params.append(limit)
        cursor.execute(query, params)
        articles = cursor.fetchall()
        print(f"🔍 Found {len(articles)} articles from today", flush=True)
        
        # If no articles from today, get recent unlabeled articles
        if not articles:
            print(f"🔍 No today's articles, getting recent ones...", flush=True)
            query = f"""
                SELECT a.uri, a.title, a.body, a.url, a.category, a.published_date
                FROM articles a
                LEFT JOIN user_interactions ui ON a.uri = ui.uri AND ui.user_id = %s 
                    AND ui.interaction_type IN ('positive', 'negative', 'neutral')
                WHERE ui.id IS NULL
                {category_filter}
                ORDER BY a.published_date DESC 
                LIMIT %s
            """
            params = [user_id, limit]
            cursor.execute(query, params)
            articles = cursor.fetchall()
            print(f"🔍 Found {len(articles)} recent articles", flush=True)
        
        cursor.close()
        conn.close()
        logger.info(f"Found {len(articles)} unlabeled articles for user {user_id}, category: {category}")
        return articles
    except Exception as e:
        error_msg = f"Error fetching articles for user {user_id}: {str(e)}"
        logger.error(error_msg)
        print(f"❌ {error_msg}", flush=True)
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
    try:
        print("🚀 Start command received!", flush=True)
        user = update.effective_user
        user_id = user.id
        print(f"👤 User: {user.first_name} (ID: {user_id})", flush=True)
        logger.info(f"User {user.first_name} (ID: {user_id}) started the bot")
        
        # Get user's labeling stats
        print("📊 Getting user stats...", flush=True)
        stats = get_user_labeling_stats(user_id)
        stats_text = ""
        if stats:
            total, positive, negative, neutral = stats
            if total > 0:
                stats_text = f"\n📊 Your stats: {total} articles labeled ({positive} positive, {negative} negative, {neutral} neutral)"
        print(f"✅ Stats retrieved: {stats_text}", flush=True)
        
        # Store user info in context
        context.user_data['user_id'] = user_id
        print("💾 User data stored in context", flush=True)
        
        # Send welcome message with category selection
        welcome_msg = f"Welcome to Briefly News Labeling Bot! 📰{stats_text}\n\n"
        welcome_msg += "Please choose a news category:"
        
        # Create category selection keyboard
        keyboard = [
            [InlineKeyboardButton("🌍 Geopolitics News", callback_data="category_geopolitics")],
            [InlineKeyboardButton("🇸🇬 Singapore News", callback_data="category_singapore")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        print("📤 Sending welcome message with category buttons...", flush=True)
        await update.message.reply_text(welcome_msg, reply_markup=reply_markup)
        print("✅ Welcome message sent successfully!", flush=True)
        
        return WAITING_FOR_CATEGORY
        
    except Exception as e:
        error_msg = f"Error in start command: {str(e)}"
        print(f"❌ {error_msg}", flush=True)
        logger.error(error_msg)
        import traceback
        print(f"📋 Traceback: {traceback.format_exc()}", flush=True)
        
        # Try to send error message
        try:
            await update.message.reply_text("❌ Sorry, something went wrong. Please try again.")
        except Exception as send_error:
            print(f"❌ Could not send error message: {send_error}", flush=True)
        
        return ConversationHandler.END

async def handle_category_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle user's category selection"""
    query = update.callback_query
    await query.answer()
    
    user_id = context.user_data.get('user_id')
    
    # Extract category from callback data
    if query.data == "category_geopolitics":
        category = "geopolitics"
        category_display = "🌍 Geopolitics News"
    elif query.data == "category_singapore":
        category = "singapore" 
        category_display = "🇸🇬 Singapore News"
    else:
        await query.edit_message_text("❌ Invalid category selection")
        return ConversationHandler.END
    
    print(f"🔖 User {user_id} selected category: {category}", flush=True)
    
    # Get articles for selected category
    articles = get_unlabeled_articles_for_user(user_id, category)
    
    if not articles:
        await query.edit_message_text(
            f"🎉 Great job! You've labeled all available {category_display} articles!\n\n"
            "Try selecting another category or check back later for new articles."
        )
        return ConversationHandler.END
    
    # Store articles and category in context
    context.user_data['articles'] = articles
    context.user_data['current_index'] = 0
    context.user_data['selected_category'] = category
    
    # Update message to show selected category
    await query.edit_message_text(
        f"✅ Selected: {category_display}\n\n"
        f"Found {len(articles)} articles to label. Let's start!"
    )
    
    # Small delay before first article
    await asyncio.sleep(1)
    
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

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log the error and send a message to notify the developer."""
    print(f"❌ Exception while handling an update: {context.error}", flush=True)
    logger.error(f"Exception while handling an update: {context.error}")
    
    # Print full traceback for debugging
    import traceback
    traceback_msg = traceback.format_exception(type(context.error), context.error, context.error.__traceback__)
    print(f"📋 Full traceback: {''.join(traceback_msg)}", flush=True)

def main():
    """Main function using python-telegram-bot's built-in webhook server"""
    global application
    
    print("=== STARTING SIMPLE TELEGRAM BOT ===", flush=True)
    print(f"Python version: {sys.version}", flush=True)
    print(f"Environment variables:", flush=True)
    print(f"  - TELEGRAM_BOT_TOKEN present: {bool(TOKEN)}", flush=True)
    print(f"  - DATABASE_URL present: {bool(DATABASE_URL)}", flush=True)
    print(f"  - WEBHOOK_URL: {WEBHOOK_URL}", flush=True)
    print(f"  - PORT: {PORT}", flush=True)
    
    if not TOKEN:
        print("❌ TELEGRAM_BOT_TOKEN not found!", flush=True)
        return
    
    if not DATABASE_URL:
        print("❌ DATABASE_URL not found!", flush=True)
        return
    
    try:
        print("🤖 Creating bot application...", flush=True)
        
        # Create application
        application = Application.builder().token(TOKEN).build()
        print("✅ Application created", flush=True)
        
        # Create conversation handler
        conv_handler = ConversationHandler(
            entry_points=[CommandHandler('start', start)],
            states={
                WAITING_FOR_CATEGORY: [CallbackQueryHandler(handle_category_selection)],
                WAITING_FOR_LABEL: [CallbackQueryHandler(handle_label)]
            },
            fallbacks=[CommandHandler('cancel', cancel)]
        )
        
        # Add handlers
        application.add_handler(conv_handler)
        application.add_handler(CommandHandler('stats', stats_command))
        application.add_error_handler(error_handler)
        print("✅ Handlers added", flush=True)
        
        if WEBHOOK_URL:
            # Use built-in webhook server
            print(f"🚀 Starting webhook server on port {PORT}...", flush=True)
            application.run_webhook(
                listen="0.0.0.0",
                port=PORT,
                url_path="webhook",
                webhook_url=f"{WEBHOOK_URL}/webhook",
                drop_pending_updates=True
            )
        else:
            # Fallback to polling for development
            print("🚀 Starting with polling (no webhook URL set)...", flush=True)
            application.run_polling(drop_pending_updates=True)
        
    except Exception as e:
        error_msg = f"Error starting bot: {str(e)}"
        logger.error(error_msg)
        print(f"❌ {error_msg}", flush=True)
        import traceback
        print(f"Traceback: {traceback.format_exc()}", flush=True)

if __name__ == "__main__":
    main() 
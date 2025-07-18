import os
import sys
import asyncio
import logging
import threading
import queue
import json
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, ConversationHandler, MessageHandler, filters
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv
import requests

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # Will be set by Cloud Run
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
PORT = int(os.getenv("PORT", 8080))

print(f"Bot token present: {bool(TOKEN)}", flush=True)
print(f"Database URL present: {bool(DATABASE_URL)}", flush=True)
print(f"OpenAI API key present: {bool(OPENAI_API_KEY)}", flush=True)

# Bot conversation states
WAITING_FOR_CATEGORY = 1
WAITING_FOR_LABEL = 2
WAITING_FOR_QUESTION = 3
WAITING_FOR_ARTICLE_QUESTION = 4

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

def get_unlabeled_articles_for_user(user_id, category=None, limit=None):
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
                category_filter = "AND LOWER(a.category) LIKE %s"
                params.append('%geopolitics%')
            elif category.lower() == 'singapore':
                category_filter = "AND LOWER(a.category) LIKE %s"
                params.append('%singapore%')
        
        # Get articles from today that this user hasn't labeled yet
        print(f"🔍 Querying for today's articles with category filter...", flush=True)
        limit_clause = f"LIMIT %s" if limit else ""
        query = f"""
            SELECT a.uri, a.title, a.body, a.url, a.category, a.published_date
            FROM articles a
            LEFT JOIN user_interactions ui ON a.uri = ui.uri AND ui.user_id = %s 
                AND ui.interaction_type IN ('positive', 'negative', 'neutral')
            WHERE ui.id IS NULL
            AND a.published_date >= CURRENT_DATE
            {category_filter}
            ORDER BY a.published_date DESC 
            {limit_clause}
        """
        if limit:
            params.append(limit)
        print(f"🔍 Executing query: {query}", flush=True)
        print(f"🔍 Query params: {params}", flush=True)
        
        try:
            cursor.execute(query, params)
            articles = cursor.fetchall()
            print(f"🔍 Query executed successfully", flush=True)
            print(f"🔍 Found {len(articles)} articles from today", flush=True)
            print(f"🔍 Articles type: {type(articles)}", flush=True)
            
            if articles:
                print(f"🔍 First article type: {type(articles[0])}", flush=True)
                print(f"🔍 First article length: {len(articles[0]) if articles[0] else 'None'}", flush=True)
                print(f"🔍 First article sample: {articles[0]}", flush=True)
        except Exception as query_error:
            print(f"❌ Query execution error: {query_error}", flush=True)
            import traceback
            print(f"📋 Query traceback: {traceback.format_exc()}", flush=True)
            raise
        
        # If no articles from today, get recent unlabeled articles
        if not articles:
            print(f"🔍 No today's articles, getting recent ones...", flush=True)
            fallback_limit_clause = f"LIMIT %s" if limit else ""
            query = f"""
                SELECT a.uri, a.title, a.body, a.url, a.category, a.published_date
                FROM articles a
                LEFT JOIN user_interactions ui ON a.uri = ui.uri AND ui.user_id = %s 
                    AND ui.interaction_type IN ('positive', 'negative', 'neutral')
                WHERE ui.id IS NULL
                {category_filter}
                ORDER BY a.published_date DESC 
                {fallback_limit_clause}
            """
            # Rebuild params for fallback query
            fallback_params = [user_id]
            if category:
                if category.lower() == 'geopolitics':
                    fallback_params.append('%geopolitics%')
                elif category.lower() == 'singapore':
                    fallback_params.append('%singapore%')
            if limit:
                fallback_params.append(limit)
            
            print(f"🔍 Executing fallback query: {query}", flush=True)
            print(f"🔍 Fallback params: {fallback_params}", flush=True)
            cursor.execute(query, fallback_params)
            articles = cursor.fetchall()
            print(f"🔍 Found {len(articles)} recent articles", flush=True)
            if articles:
                print(f"🔍 First recent article sample: {articles[0] if articles else 'None'}", flush=True)
        
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

def get_recent_news_context(category=None, limit=10):
    """Get recent news articles for AI context"""
    conn = get_db_connection()
    if not conn:
        return []
    
    try:
        cursor = conn.cursor()
        
        # Build category filter
        category_filter = ""
        params = []
        
        if category:
            if category.lower() == 'geopolitics':
                category_filter = "WHERE LOWER(category) LIKE %s"
                params.append('%geopolitics%')
            elif category.lower() == 'singapore':
                category_filter = "WHERE (LOWER(category) LIKE %s OR LOWER(title) LIKE %s OR LOWER(body) LIKE %s)"
                params.extend(['%singapore%', '%singapore%', '%singapore%'])
        
        # Get recent articles
        query = f"""
            SELECT title, body, category, published_date, url
            FROM articles
            {category_filter}
            ORDER BY published_date DESC
            LIMIT %s
        """
        params.append(limit)
        
        cursor.execute(query, params)
        articles = cursor.fetchall()
        
        cursor.close()
        conn.close()
        
        return articles
    except Exception as e:
        logger.error(f"Error getting news context: {str(e)}")
        return []

def generate_ai_response(user_question, news_context, category=None):
    """Generate AI response based on news context using HTTP requests"""
    if not OPENAI_API_KEY:
        return "❌ AI service is not available. Please contact the administrator."
    
    try:
        # Format news context for AI
        context_text = ""
        if news_context:
            context_text = "\n\n".join([
                f"**{article[0]}**\n{article[1][:500]}...\nCategory: {article[2]}\nDate: {article[3]}\nURL: {article[4]}"
                for article in news_context[:5]  # Use only top 5 articles
            ])
        else:
            return "❌ No recent news articles available to answer your question."
        
        # Create prompt
        category_context = f" about {category}" if category else ""
        prompt = f"""You are a helpful news analyst. Based on the following recent news articles{category_context}, please answer the user's question concisely and informatively.

Recent News Articles:
{context_text}

User Question: {user_question}

Please provide a helpful answer based on the news content above. Include information from ANY of the articles that relate to the question - this includes current events, lifestyle topics, business news, social issues, infrastructure developments, and other newsworthy content. If no articles are relevant to the specific question, then say so politely."""

        # Make HTTP request to OpenAI API
        headers = {
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json"
        }
        
        data = {
            "model": "gpt-3.5-turbo",
            "messages": [
                {"role": "system", "content": "You are a helpful news analyst assistant."},
                {"role": "user", "content": prompt}
            ],
            "max_tokens": 500,
            "temperature": 0.7
        }
        
        response = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers=headers,
            json=data,
            timeout=30
        )
        
        if response.status_code == 200:
            response_data = response.json()
            return response_data['choices'][0]['message']['content'].strip()
        else:
            logger.error(f"OpenAI API error: {response.status_code} - {response.text}")
            return f"❌ Error from AI service: {response.status_code}"
    
    except requests.exceptions.RequestException as e:
        logger.error(f"HTTP request error: {str(e)}")
        return f"❌ Network error: {str(e)}"
    except Exception as e:
        logger.error(f"Error generating AI response: {str(e)}")
        return f"❌ Error generating response: {str(e)}"

def generate_general_ai_response(user_question):
    """Generate AI response for general questions without database context"""
    if not OPENAI_API_KEY:
        return "❌ AI service is not available. Please contact the administrator."
    
    try:
        prompt = f"""You are a helpful assistant. Please answer the user's question using your general knowledge. Provide a concise and informative response.

User Question: {user_question}

Please provide a helpful answer based on your knowledge."""

        # Make HTTP request to OpenAI API
        headers = {
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json"
        }
        
        data = {
            "model": "gpt-3.5-turbo",
            "messages": [
                {"role": "system", "content": "You are a helpful assistant that provides informative and accurate answers to user questions."},
                {"role": "user", "content": prompt}
            ],
            "max_tokens": 500,
            "temperature": 0.7
        }
        
        response = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers=headers,
            json=data,
            timeout=30
        )
        
        if response.status_code == 200:
            response_data = response.json()
            return response_data['choices'][0]['message']['content'].strip()
        else:
            logger.error(f"OpenAI API error: {response.status_code} - {response.text}")
            return f"❌ Error from AI service: {response.status_code}"
    
    except requests.exceptions.RequestException as e:
        logger.error(f"HTTP request error: {str(e)}")
        return f"❌ Network error: {str(e)}"
    except Exception as e:
        logger.error(f"Error generating AI response: {str(e)}")
        return f"❌ Error generating response: {str(e)}"

def generate_article_ai_response(user_question, article_content):
    """Generate AI response for questions about a specific article"""
    if not OPENAI_API_KEY:
        return "❌ AI service is not available. Please contact the administrator."
    
    # Limit article content to prevent oversized requests
    max_content_length = 2000
    if len(article_content) > max_content_length:
        article_content = article_content[:max_content_length] + "...[content truncated]"
    
    for attempt in range(3):  # Retry up to 3 times
        try:
            prompt = f"""You are a helpful news analyst. Based on the following news article, please answer the user's question about it.

News Article:
{article_content}

User Question: {user_question}

Please provide a helpful answer based on the article content above."""

            # Make HTTP request to OpenAI API
            headers = {
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "Content-Type": "application/json"
            }
            
            data = {
                "model": "gpt-3.5-turbo",
                "messages": [
                    {"role": "system", "content": "You are a helpful news analyst assistant."},
                    {"role": "user", "content": prompt}
                ],
                "max_tokens": 400,
                "temperature": 0.7
            }
            
            response = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers=headers,
                json=data,
                timeout=15  # Reduced timeout
            )
            
            if response.status_code == 200:
                response_data = response.json()
                return response_data['choices'][0]['message']['content'].strip()
            else:
                logger.error(f"OpenAI API error (attempt {attempt + 1}): {response.status_code} - {response.text}")
                if attempt == 2:  # Last attempt
                    return f"❌ AI service error after 3 attempts. Please try again later."
        
        except requests.exceptions.Timeout:
            logger.error(f"Request timeout (attempt {attempt + 1})")
            if attempt == 2:
                return "❌ Request timed out. The article might be too long. Please try a simpler question."
        except requests.exceptions.ConnectionError:
            logger.error(f"Connection error (attempt {attempt + 1})")
            if attempt == 2:
                return "❌ Connection failed. Please check your internet connection and try again."
        except requests.exceptions.RequestException as e:
            logger.error(f"HTTP request error (attempt {attempt + 1}): {str(e)}")
            if attempt == 2:
                return "❌ Network error. Please try again in a moment."
        except Exception as e:
            logger.error(f"Error generating AI response (attempt {attempt + 1}): {str(e)}")
            if attempt == 2:
                return f"❌ Unexpected error. Please try again later."
        
        # Wait before retry (except on last attempt)
        if attempt < 2:
            import time
            time.sleep(1)
    
    return "❌ Service temporarily unavailable. Please try again later."

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
    print(f"🔍 Calling get_unlabeled_articles_for_user with category: {category}", flush=True)
    articles = get_unlabeled_articles_for_user(user_id, category)
    print(f"🔍 get_unlabeled_articles_for_user returned: {type(articles)}, length: {len(articles) if articles else 'None'}", flush=True)
    
    if not articles:
        await query.edit_message_text(
            f"🎉 Great job! You've labeled all available {category_display} articles!\n\n"
            "Try selecting another category or check back later for new articles."
        )
        return ConversationHandler.END
    
    print(f"🔍 First article from get_unlabeled_articles_for_user: {articles[0] if articles else 'None'}", flush=True)
    
    # Store articles and category in context
    context.user_data['articles'] = articles
    context.user_data['current_index'] = 0
    context.user_data['selected_category'] = category
    
    print(f"🔍 Articles stored in context, calling send_article_for_labeling", flush=True)
    
    # Update message to show selected category3
    await query.edit_message_text(
        f"✅ Selected: {category_display}\n\n"
        f"🗞️ Ready to explore the latest news? Let's dive into today's stories!\n"
        f"📖 Share your thoughts on each article as we go. Happy browsing! 🚀"
    )
    
    # Small delay before first article
    await asyncio.sleep(1)
    
    # Send first article
    return await send_article_for_labeling(update, context)

async def send_article_for_labeling(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Send article for user to label"""
    try:
        articles = context.user_data.get('articles', [])
        current_index = context.user_data.get('current_index', 0)
        
        print(f"🔍 send_article_for_labeling called", flush=True)
        print(f"🔍 Articles count: {len(articles)}", flush=True)
        print(f"🔍 Current index: {current_index}", flush=True)
        
        if current_index >= len(articles):
            await update.message.reply_text("All articles have been processed! Thank you.")
            return ConversationHandler.END
        
        article = articles[current_index]
        print(f"🔍 Article type: {type(article)}", flush=True)
        print(f"🔍 Article length: {len(article) if article else 'None'}", flush=True)
        print(f"🔍 Article content: {article}", flush=True)
        
        article_uri, title, body, url, category, published_date = article
        print(f"🔍 Article unpacked successfully", flush=True)
    except Exception as unpack_error:
        print(f"❌ Error in send_article_for_labeling: {unpack_error}", flush=True)
        import traceback
        print(f"📋 Unpack traceback: {traceback.format_exc()}", flush=True)
        
        # Try to send error message to user
        try:
            if update.message:
                await update.message.reply_text("❌ Error loading article. Please try again with /start")
            elif update.callback_query:
                await update.callback_query.message.reply_text("❌ Error loading article. Please try again with /start")
        except:
            pass
        
        return ConversationHandler.END
    
    # Store current article URI
    context.user_data['current_article_uri'] = article_uri
    
    # Create inline keyboard for labeling
    keyboard = [
        [InlineKeyboardButton("📈 Positive", callback_data="positive")],
        [InlineKeyboardButton("📉 Negative", callback_data="negative")],
        [InlineKeyboardButton("😐 Neutral", callback_data="neutral")],
        [InlineKeyboardButton("⏭️ Skip", callback_data="skip")],
        [InlineKeyboardButton("❓ Ask about this article", callback_data="ask_article")],
        [InlineKeyboardButton("🔄 Change Category", callback_data="change_category")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Format message with improved styling
    message = f"📰 **Article {current_index + 1}/{len(articles)}**\n\n"
    message += f"**{title}**\n\n"
    message += f"🏷️ **Category:** {category}\n\n"
    message += f"📅 **Published:** {published_date.strftime('%Y-%m-%d') if published_date else 'Unknown'}\n\n"
    message += f"📖 **Content:**\n{body[:400]}{'...' if len(body) > 400 else ''}\n\n"
    message += f"🔗 [Read Full Article]({url})\n\n"
    message += "👆 **Please select a label for this article:**"
    
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
    
    # Handle category change request
    if label == "change_category":
        # Show category selection menu again
        welcome_msg = "📰 Please choose a news category:"
        
        # Create category selection keyboard
        keyboard = [
            [InlineKeyboardButton("🌍 Geopolitics News", callback_data="category_geopolitics")],
            [InlineKeyboardButton("🇸🇬 Singapore News", callback_data="category_singapore")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(welcome_msg, reply_markup=reply_markup)
        return WAITING_FOR_CATEGORY
    
    # Handle ask about article request
    if label == "ask_article":
        # Get current article details
        current_article = articles[current_index]
        article_uri, title, body, url, category, published_date = current_article
        
        # Store article content for Q&A
        context.user_data['current_article_content'] = {
            'title': title,
            'body': body,
            'url': url,
            'category': category,
            'published_date': published_date
        }
        
        # Send Q&A prompt
        qa_msg = f"❓ **Ask about this article:**\n\n"
        qa_msg += f"**{title}**\n\n"
        qa_msg += f"You can ask questions like:\n"
        qa_msg += f"• What are the key points?\n"
        qa_msg += f"• Why is this significant?\n"
        qa_msg += f"• What are the implications?\n"
        qa_msg += f"• Who are the main players involved?\n\n"
        qa_msg += f"**Type your question below:**"
        
        await query.edit_message_text(qa_msg, parse_mode='Markdown')
        return WAITING_FOR_ARTICLE_QUESTION
    
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

async def ask_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Ask command - start Q&A session"""
    try:
        user = update.effective_user
        user_id = user.id
        logger.info(f"User {user.first_name} (ID: {user_id}) started Q&A session")
        
        # Store user info in context
        context.user_data['user_id'] = user_id
        context.user_data['ask_category'] = None  # No category filter by default
        
        # Send welcome message for Q&A
        welcome_msg = "🤔 **Ask me about the news!** 📰\n\n"
        welcome_msg += "You can ask questions like:\n"
        welcome_msg += "• What are the main headlines today?\n"
        welcome_msg += "• What economic issues are trending?\n"
        welcome_msg += "• Summarize recent geopolitical developments\n"
        welcome_msg += "• What's happening in Singapore?\n\n"
        welcome_msg += "**Type your question below:**"
        
        await update.message.reply_text(welcome_msg, parse_mode='Markdown')
        
        return WAITING_FOR_QUESTION
        
    except Exception as e:
        logger.error(f"Error in ask command: {str(e)}")
        await update.message.reply_text("❌ Sorry, something went wrong. Please try again.")
        return ConversationHandler.END

async def ask_geopolitics_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Ask command for geopolitics news specifically"""
    try:
        user = update.effective_user
        user_id = user.id
        logger.info(f"User {user.first_name} (ID: {user_id}) started geopolitics Q&A session")
        
        # Store user info in context
        context.user_data['user_id'] = user_id
        context.user_data['ask_category'] = 'geopolitics'
        
        # Send welcome message for geopolitics Q&A
        welcome_msg = "🌍 **Ask me about geopolitics news!** 📰\n\n"
        welcome_msg += "You can ask questions like:\n"
        welcome_msg += "• What are the main geopolitical tensions today?\n"
        welcome_msg += "• What's happening in international relations?\n"
        welcome_msg += "• Summarize recent conflicts or diplomatic developments\n\n"
        welcome_msg += "**Type your question below:**"
        
        await update.message.reply_text(welcome_msg, parse_mode='Markdown')
        
        return WAITING_FOR_QUESTION
        
    except Exception as e:
        logger.error(f"Error in ask_geopolitics command: {str(e)}")
        await update.message.reply_text("❌ Sorry, something went wrong. Please try again.")
        return ConversationHandler.END

async def ask_singapore_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Ask command for Singapore news specifically"""
    try:
        user = update.effective_user
        user_id = user.id
        logger.info(f"User {user.first_name} (ID: {user_id}) started Singapore Q&A session")
        
        # Store user info in context
        context.user_data['user_id'] = user_id
        context.user_data['ask_category'] = 'singapore'
        
        # Send welcome message for Singapore Q&A
        welcome_msg = "🇸🇬 **Ask me about Singapore news!** 📰\n\n"
        welcome_msg += "You can ask questions like:\n"
        welcome_msg += "• What are the key Singapore headlines today?\n"
        welcome_msg += "• What policies are being discussed?\n"
        welcome_msg += "• Summarize recent Singapore developments\n\n"
        welcome_msg += "**Type your question below:**"
        
        await update.message.reply_text(welcome_msg, parse_mode='Markdown')
        
        return WAITING_FOR_QUESTION
        
    except Exception as e:
        logger.error(f"Error in ask_singapore command: {str(e)}")
        await update.message.reply_text("❌ Sorry, something went wrong. Please try again.")
        return ConversationHandler.END

async def handle_question(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle user's question and generate AI response"""
    try:
        user_question = update.message.text
        user_id = context.user_data.get('user_id')
        category = context.user_data.get('ask_category')
        
        logger.info(f"User {user_id} asked: {user_question}")
        
        if category:
            # Category-specific questions use database context
            thinking_msg = await update.message.reply_text("🤔 Let me analyze the recent news to answer your question...")
            
            # Get news context
            news_context = get_recent_news_context(category=category, limit=10)
            
            # Debug: Log what articles we found
            logger.info(f"Found {len(news_context)} articles for category '{category}'")
            if news_context:
                logger.info(f"Sample article titles: {[article[0][:50] for article in news_context[:3]]}")
            
            # Generate AI response with database context
            ai_response = generate_ai_response(user_question, news_context, category)
            category_emoji = {"geopolitics": "🌍", "singapore": "🇸🇬"}.get(category, "📰")
        else:
            # General questions use AI's broader knowledge
            thinking_msg = await update.message.reply_text("🤔 Let me think about that...")
            
            # Generate AI response without database context
            ai_response = generate_general_ai_response(user_question)
            category_emoji = "📰"
        
        # Delete thinking message and send response
        await thinking_msg.delete()
        
        # Format response
        response_msg = f"{category_emoji} **Your Answer:**\n\n{ai_response}\n\n"
        response_msg += "💬 Ask another question or use /cancel to exit."
        
        await update.message.reply_text(response_msg, parse_mode='Markdown')
        
        return WAITING_FOR_QUESTION
        
    except Exception as e:
        logger.error(f"Error handling question: {str(e)}")
        await update.message.reply_text("❌ Sorry, I couldn't process your question. Please try again.")
        return WAITING_FOR_QUESTION

async def handle_article_question(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle user's question about a specific article"""
    try:
        user_question = update.message.text
        user_id = context.user_data.get('user_id')
        article_content = context.user_data.get('current_article_content')
        
        if not article_content:
            await update.message.reply_text("❌ Article information not found. Please try again.")
            return ConversationHandler.END
        
        logger.info(f"User {user_id} asked about article: {user_question}")
        
        # Send "thinking" message
        thinking_msg = await update.message.reply_text("🤔 Let me analyze this article...")
        
        # Format article content for AI
        formatted_article = f"""Title: {article_content['title']}

Content: {article_content['body']}

Category: {article_content['category']}
Published: {article_content['published_date']}
URL: {article_content['url']}"""
        
        # Generate AI response about the specific article
        ai_response = generate_article_ai_response(user_question, formatted_article)
        
        # Delete thinking message and send response
        await thinking_msg.delete()
        
        # Format response with back-to-labeling option
        response_msg = f"❓ **Your Answer:**\n\n{ai_response}\n\n"
        response_msg += "💬 Ask another question about this article, or use the buttons below:"
        
        # Create keyboard to return to labeling or ask more questions
        keyboard = [
            [InlineKeyboardButton("🔙 Back to Labeling", callback_data="back_to_labeling")],
            [InlineKeyboardButton("❓ Ask Another Question", callback_data="ask_another")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(response_msg, reply_markup=reply_markup, parse_mode='Markdown')
        
        return WAITING_FOR_ARTICLE_QUESTION
        
    except Exception as e:
        logger.error(f"Error handling article question: {str(e)}")
        await update.message.reply_text("❌ Sorry, I couldn't process your question. Please try again.")
        return WAITING_FOR_ARTICLE_QUESTION

async def handle_article_qa_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle callbacks in article Q&A mode"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "back_to_labeling":
        # Return to the article labeling interface
        articles = context.user_data.get('articles', [])
        current_index = context.user_data.get('current_index', 0)
        
        if current_index < len(articles):
            # Restore the article for labeling
            return await send_article_for_labeling(update, context)
        else:
            await query.edit_message_text("All articles have been processed! Thank you.")
            return ConversationHandler.END
    
    elif query.data == "ask_another":
        article_content = context.user_data.get('current_article_content')
        if article_content:
            qa_msg = f"❓ **Ask another question about:**\n\n"
            qa_msg += f"**{article_content['title']}**\n\n"
            qa_msg += f"**Type your question below:**"
            
            await query.edit_message_text(qa_msg, parse_mode='Markdown')
            return WAITING_FOR_ARTICLE_QUESTION
    
    return WAITING_FOR_ARTICLE_QUESTION

async def show_recent_articles_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show recent articles in database for debugging"""
    try:
        # Get recent articles for all categories
        all_articles = get_recent_news_context(category=None, limit=10)
        singapore_articles = get_recent_news_context(category='singapore', limit=5)
        geopolitics_articles = get_recent_news_context(category='geopolitics', limit=5)
        
        message = "📰 **Recent Articles in Database:**\n\n"
        message += f"📊 **Total recent articles:** {len(all_articles)}\n"
        message += f"🇸🇬 **Singapore articles:** {len(singapore_articles)}\n"
        message += f"🌍 **Geopolitics articles:** {len(geopolitics_articles)}\n\n"
        
        if singapore_articles:
            message += "🇸🇬 **Singapore Articles:**\n"
            for i, article in enumerate(singapore_articles[:3], 1):
                title, body, category, pub_date, url = article
                message += f"{i}. {title[:60]}...\n"
                message += f"   Category: {category}\n"
                message += f"   Date: {pub_date}\n\n"
        else:
            message += "🇸🇬 **No Singapore articles found**\n\n"
        
        if geopolitics_articles:
            message += "🌍 **Geopolitics Articles:**\n"
            for i, article in enumerate(geopolitics_articles[:3], 1):
                title, body, category, pub_date, url = article
                message += f"{i}. {title[:60]}...\n"
                message += f"   Category: {category}\n"
                message += f"   Date: {pub_date}\n\n"
        else:
            message += "🌍 **No Geopolitics articles found**\n\n"
        
        if len(message) > 4000:  # Telegram message limit
            message = message[:4000] + "...\n\n(Message truncated due to length)"
        
        await update.message.reply_text(message, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Error in show_recent_articles_command: {str(e)}")
        await update.message.reply_text(f"❌ Error retrieving articles: {str(e)}")

async def debug_database_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Debug command to inspect database structure and data"""
    user = update.effective_user
    user_id = user.id
    
    # Only allow specific users to run debug (you can modify this)
    if user_id != 2045755665:  # Your user ID
        await update.message.reply_text("❌ Debug command not available for this user.")
        return
    
    await update.message.reply_text("🔍 Inspecting database... Please wait.")
    
    try:
        conn = get_db_connection()
        if not conn:
            await update.message.reply_text("❌ Could not connect to database.")
            return
        
        cursor = conn.cursor()
        
        # Check user_interactions table structure and constraints
        cursor.execute("""
            SELECT conname, pg_get_constraintdef(pg_constraint.oid) as constraint_def
            FROM pg_constraint 
            JOIN pg_class ON conrelid = pg_class.oid 
            WHERE relname = 'user_interactions' AND contype = 'c';
        """)
        constraints = cursor.fetchall()
        
        if constraints:
            constraint_text = "🔧 **USER_INTERACTIONS CONSTRAINTS:**\n\n"
            for name, constraint_def in constraints:
                constraint_text += f"• `{name}`: {constraint_def}\n"
            await update.message.reply_text(constraint_text, parse_mode='Markdown')
        
        # Check existing interaction_type values in the table
        cursor.execute("""
            SELECT DISTINCT interaction_type, COUNT(*) 
            FROM user_interactions 
            GROUP BY interaction_type 
            ORDER BY COUNT(*) DESC;
        """)
        existing_types = cursor.fetchall()
        
        if existing_types:
            types_text = "📊 **EXISTING INTERACTION TYPES:**\n\n"
            for itype, count in existing_types:
                types_text += f"• `{itype}`: {count} records\n"
            await update.message.reply_text(types_text, parse_mode='Markdown')
        else:
            await update.message.reply_text("📊 **EXISTING INTERACTION TYPES:** No records found")
        
        # Try to get table definition
        cursor.execute("""
            SELECT column_name, data_type, is_nullable, column_default
            FROM information_schema.columns
            WHERE table_name = 'user_interactions'
            ORDER BY ordinal_position;
        """)
        columns = cursor.fetchall()
        
        if columns:
            columns_text = "🗂️ **USER_INTERACTIONS COLUMNS:**\n\n"
            for col_name, data_type, nullable, default in columns:
                columns_text += f"• `{col_name}`: {data_type} (nullable: {nullable})\n"
            await update.message.reply_text(columns_text, parse_mode='Markdown')
        
        # 1. Show unique categories
        cursor.execute("SELECT DISTINCT category, COUNT(*) FROM articles GROUP BY category ORDER BY COUNT(*) DESC;")
        categories = cursor.fetchall()
        
        categories_text = "📊 **CATEGORIES IN DATABASE:**\n\n"
        for cat, count in categories[:10]:  # Show top 10
            categories_text += f"• `{cat}`: {count} articles\n"
        
        await update.message.reply_text(categories_text, parse_mode='Markdown')
        
        # 2. Show sample articles for each filter we're using
        filters_to_test = [
            ("geopolitics", "LOWER(category) LIKE '%geopolitic%'"),
            ("singapore", "LOWER(category) LIKE '%singapore%'")
        ]
        
        for filter_name, filter_condition in filters_to_test:
            cursor.execute(f"""
                SELECT category, title, published_date 
                FROM articles 
                WHERE {filter_condition}
                ORDER BY published_date DESC 
                LIMIT 3;
            """)
            
            results = cursor.fetchall()
            
            if results:
                filter_text = f"🔍 **{filter_name.upper()} FILTER RESULTS:**\n\n"
                for cat, title, pub_date in results:
                    filter_text += f"• Category: `{cat}`\n"
                    filter_text += f"  Title: {title[:50]}...\n"
                    filter_text += f"  Date: {pub_date}\n\n"
            else:
                filter_text = f"❌ **{filter_name.upper()} FILTER:** No results found\n\n"
            
            await update.message.reply_text(filter_text, parse_mode='Markdown')
        
        # 3. Check today's articles
        cursor.execute("""
            SELECT COUNT(*), category 
            FROM articles 
            WHERE published_date >= CURRENT_DATE 
            GROUP BY category 
            ORDER BY COUNT(*) DESC 
            LIMIT 5;
        """)
        today_articles = cursor.fetchall()
        
        if today_articles:
            today_text = "📅 **TODAY'S ARTICLES:**\n\n"
            for count, category in today_articles:
                today_text += f"• `{category}`: {count} articles\n"
        else:
            today_text = "📅 **TODAY'S ARTICLES:** None found"
        
        await update.message.reply_text(today_text, parse_mode='Markdown')
        
        # 4. Check recent articles (last 7 days)
        cursor.execute("""
            SELECT COUNT(*), category 
            FROM articles 
            WHERE published_date >= CURRENT_DATE - INTERVAL '7 days'
            GROUP BY category 
            ORDER BY COUNT(*) DESC 
            LIMIT 5;
        """)
        recent_articles = cursor.fetchall()
        
        if recent_articles:
            recent_text = "📈 **LAST 7 DAYS:**\n\n"
            for count, category in recent_articles:
                recent_text += f"• `{category}`: {count} articles\n"
        else:
            recent_text = "📈 **LAST 7 DAYS:** None found"
        
        await update.message.reply_text(recent_text, parse_mode='Markdown')
        
        cursor.close()
        conn.close()
        
        await update.message.reply_text("✅ Database inspection complete!")
        
    except Exception as e:
        error_msg = f"❌ Debug error: {str(e)}"
        await update.message.reply_text(error_msg)
        print(f"Debug command error: {e}", flush=True)
        import traceback
        print(f"Debug traceback: {traceback.format_exc()}", flush=True)

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
        
        # Create conversation handler for labeling
        conv_handler = ConversationHandler(
            entry_points=[CommandHandler('start', start)],
            states={
                WAITING_FOR_CATEGORY: [CallbackQueryHandler(handle_category_selection)],
                WAITING_FOR_LABEL: [CallbackQueryHandler(handle_label)],
                WAITING_FOR_ARTICLE_QUESTION: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, handle_article_question),
                    CallbackQueryHandler(handle_article_qa_callback)
                ]
            },
            fallbacks=[CommandHandler('cancel', cancel)]
        )
        
        # Create conversation handler for Q&A
        qa_conv_handler = ConversationHandler(
            entry_points=[
                CommandHandler('ask', ask_command),
                CommandHandler('ask_geopolitics', ask_geopolitics_command),
                CommandHandler('ask_singapore', ask_singapore_command)
            ],
            states={
                WAITING_FOR_QUESTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_question)]
            },
            fallbacks=[CommandHandler('cancel', cancel)]
        )
        
        # Add handlers
        application.add_handler(conv_handler)
        application.add_handler(qa_conv_handler)
        application.add_handler(CommandHandler('stats', stats_command))
        application.add_handler(CommandHandler('debug', debug_database_command))
        application.add_handler(CommandHandler('articles', show_recent_articles_command))
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
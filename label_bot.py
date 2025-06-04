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
last_labeled_uri = {}  # Tracks last labeled URI per user

def get_connection():
    return psycopg2.connect(DATABASE_URL, sslmode='require')

def load_articles():
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

def get_labeled_uris(user_id):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT uri FROM detailed_labels WHERE user_id = %s", (user_id,))
            return set(row[0] for row in cur.fetchall())
    finally:
        conn.close()

def save_detailed_label(user_id, session):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO detailed_labels (user_id, uri, useful, category, subcategory, purpose)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (user_id, uri) DO UPDATE SET
                    useful = EXCLUDED.useful,
                    category = EXCLUDED.category,
                    subcategory = EXCLUDED.subcategory,
                    purpose = EXCLUDED.purpose
            """, (user_id, session['uri'], session['useful'], session.get('category'), session.get('subcategory'), session.get('purpose')))
        conn.commit()
    finally:
        conn.close()

def get_last_labeled_article(user_id):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT uri, category, subcategory, purpose FROM detailed_labels
                WHERE user_id = %s ORDER BY id DESC LIMIT 1
            """, (user_id,))
            row = cur.fetchone()
            return row if row else None
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
    df = load_articles()
    available_uris = set(df["uri"])
    labeled_uris = get_labeled_uris(user_id)
    labeled = len(available_uris & labeled_uris)
    total = len(df)
    remaining = total - labeled
    update.message.reply_text(f"\U0001F9FE Status:\nTotal Articles: {total}\nYou've Labeled: {labeled}\nRemaining: {remaining}")

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
    update.message.reply_text(f"🔄 Redoing last labeled article:{text}", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(buttons))
    return ASK_USEFUL

def ask_category(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    user_id = query.message.chat_id
    is_useful = query.data.endswith("yes")
    user_sessions[user_id]['useful'] = is_useful

    if not is_useful:
        save_detailed_label(user_id, user_sessions[user_id])
        df = load_articles()
        available_uris = set(df["uri"])
        labeled_uris = get_labeled_uris(user_id)
        labeled = len(available_uris & labeled_uris)
        total = len(df)
        remaining = total - labeled
        query.edit_message_text(f"\u274C Marked as Not Useful.\nTotal Articles: {total}\nYou've Labeled: {labeled}\nRemaining: {remaining}\n\nUse /label to tag another article.")
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
    df = load_articles()
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


def end_label(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    user_id = query.message.chat_id
    purpose = query.data.split("|")[1]

    if user_id not in user_sessions:
        query.edit_message_text("⚠️ Session expired or not found. Please use /label to restart.")
        return ConversationHandler.END

    user_sessions[user_id]['purpose'] = purpose
    save_detailed_label(user_id, user_sessions[user_id])

    df = load_articles()
    available_uris = set(df["uri"])
    labeled_uris = get_labeled_uris(user_id)
    labeled = len(available_uris & labeled_uris)
    total = len(df)
    remaining = total - labeled
    query.edit_message_text(
        f"✅ Label saved.\nTotal Articles: {total}\nYou've Labeled: {labeled}\nRemaining: {remaining}\n\nUse /label to tag another article."
    )
    return ConversationHandler.END

def cancel(update: Update, context: CallbackContext):
    update.message.reply_text("Labelling cancelled.")
    return ConversationHandler.END

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
    # Removed standalone redo handler to avoid conflicts
    # dp.add_handler(CommandHandler('redo', redo))
    dp.add_handler(conv_handler)

    print("\u2705 Detailed labeling bot running...")
    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()

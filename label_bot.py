import os
import pandas as pd
import psycopg2
from datetime import datetime, timedelta
from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Updater, CallbackContext, CommandHandler, CallbackQueryHandler

# Load environment variables
load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
LOOKBACK_DAYS = 3
BATCH_SIZE = 5

# Database connection
def get_connection():
    return psycopg2.connect(DATABASE_URL, sslmode='require')

# Load recent articles from PostgreSQL
def load_recent_articles():
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT uri, title, body, url
                FROM articles
                WHERE created_at >= %s
            """, ((datetime.now() - timedelta(days=LOOKBACK_DAYS)).date(),))
            rows = cur.fetchall()
            return pd.DataFrame(rows, columns=["uri", "title", "body", "url"])
    finally:
        conn.close()

# Get labeled URIs by user
def get_labeled_uris(user_id):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT uri FROM labels WHERE user_id = %s", (user_id,))
            return [row[0] for row in cur.fetchall()]
    finally:
        conn.close()

# Save label to PostgreSQL
def save_label(user_id, uri, title, label):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO labels (user_id, article_uri, title, label, timestamp)
                VALUES (%s, %s, %s, %s, %s)
            """, (user_id, uri, title, label, datetime.now()))
        conn.commit()
    finally:
        conn.close()

# Bot Handlers
df = load_recent_articles()
df = df.reset_index(drop=True)
user_sent_index = {}  # user_id -> current index

def start(update: Update, context: CallbackContext):
    update.message.reply_text("Welcome! Use /label to review news or /status to see your progress.")

def status(update: Update, context: CallbackContext):
    user_id = update.message.chat_id
    labeled_count = len(get_labeled_uris(user_id))
    total = len(df)
    remaining = total - labeled_count
    update.message.reply_text(f"🧾 Status:\nTotal Articles: {total}\nYou've Labeled: {labeled_count}\nRemaining: {remaining}")

def send_articles(update: Update, context: CallbackContext):
    user_id = update.message.chat_id
    labeled_uris = set(get_labeled_uris(user_id))
    remaining_df = df[~df['uri'].isin(labeled_uris)]

    if remaining_df.empty:
        update.message.reply_text("🎉 You've labeled all available articles.")
        return

    user_sent_index.setdefault(user_id, 0)
    remaining_df = remaining_df.reset_index(drop=True)
    start_idx = user_sent_index[user_id]
    end_idx = start_idx + BATCH_SIZE
    batch = remaining_df.iloc[start_idx:end_idx]

    for _, article in batch.iterrows():
        text = f"*{article['title']}*\n\n{article['body'][:500]}...\n\n[Read more]({article['url']})"
        buttons = [[
            InlineKeyboardButton("👍 Good", callback_data=f"{user_id}|{article['uri']}:1"),
            InlineKeyboardButton("👎 Not useful", callback_data=f"{user_id}|{article['uri']}:0")
        ]]
        context.bot.send_message(chat_id=user_id, text=text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="Markdown")

    user_sent_index[user_id] += BATCH_SIZE

def handle_label(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    data = query.data
    meta, label = data.split(":")
    user_id_str, uri = meta.split("|")
    user_id = int(user_id_str)
    label = int(label)

    article = df[df['uri'] == uri].iloc[0]
    save_label(user_id, uri, article['title'], label)

    query.edit_message_reply_markup(reply_markup=None)
    query.edit_message_text(f"Labeled as {'👍 Good' if label == 1 else '👎 Not useful'}.\nUse /label for more.")

def main():
    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("label", send_articles))
    dp.add_handler(CommandHandler("status", status))
    dp.add_handler(CallbackQueryHandler(handle_label))

    print("✅ Bot running with PostgreSQL storage...")
    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()

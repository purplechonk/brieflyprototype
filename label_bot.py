import os
import csv
import pandas as pd
from datetime import datetime, timedelta
from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Updater, CallbackContext, CommandHandler, CallbackQueryHandler

# Load token
load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# Constants
LABELS_FILE = "labeled_articles.csv"
LOOKBACK_DAYS = 3
BATCH_SIZE = 5

# Load articles from the past 3 days
def load_recent_articles():
    articles = []
    today = datetime.now()
    for i in range(LOOKBACK_DAYS):
        day = today - timedelta(days=i)
        folder = os.path.join("output", day.strftime('%Y-%m-%d'))
        file_path = os.path.join(folder, "geopol_articles_final.csv")
        if os.path.exists(file_path):
            day_articles = pd.read_csv(file_path)
            day_articles['source_date'] = day.strftime('%Y-%m-%d')
            articles.append(day_articles)
    return pd.concat(articles, ignore_index=True) if articles else pd.DataFrame()

# Ensure labeled file exists
def load_existing_labels():
    if not os.path.exists(LABELS_FILE):
        with open(LABELS_FILE, mode='w', encoding='utf-8', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(["user_id", "article_uri", "title", "label", "timestamp"])
    return pd.read_csv(LABELS_FILE)

df = load_recent_articles()
df = df.reset_index(drop=True)
if 'uri' not in df.columns:
    if 'url' in df.columns:
        df['uri'] = df['url']
    else:
        # Generate fake URIs from index if both are missing
        df['uri'] = df.index.astype(str)


user_sent_index = {}  # user_id → current index

def start(update: Update, context: CallbackContext):
    update.message.reply_text("Welcome! Use /label to review news or /status to see your progress.")

def status(update: Update, context: CallbackContext):
    user_id = update.message.chat_id
    labeled_df = load_existing_labels()
    total = len(df)
    labeled = labeled_df[labeled_df['user_id'] == user_id]['article_uri'].nunique()
    remaining = total - labeled
    update.message.reply_text(f"🧾 Status:\nTotal Articles: {total}\nYou've Labeled: {labeled}\nRemaining: {remaining}")

def send_articles(update: Update, context: CallbackContext):
    user_id = update.message.chat_id
    labeled_df = load_existing_labels()
    labeled_uris = labeled_df[labeled_df['user_id'] == user_id]['article_uri'].unique()
    remaining_df = df[~df['uri'].isin(labeled_uris)]

    if remaining_df.empty:
        update.message.reply_text("🎉 You've labeled all available articles.")
        return

    # Track where the user left off
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

    # Save label immediately
    with open(LABELS_FILE, mode='a', encoding='utf-8', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([
            user_id,
            uri,
            article["title"],
            label,
            datetime.now().isoformat()
        ])

    query.edit_message_reply_markup(reply_markup=None)
    query.edit_message_text(f"Labeled as {'👍 Good' if label == 1 else '👎 Not useful'}.\nUse /label for more.")

def main():
    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("label", send_articles))
    dp.add_handler(CommandHandler("status", status))
    dp.add_handler(CallbackQueryHandler(handle_label))

    print("✅ Bot running with batch + status features...")
    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()

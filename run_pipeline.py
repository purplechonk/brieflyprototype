import requests
import os
from dotenv import load_dotenv

# Load token and chat ID from .env
load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")  # Replace with your actual ID or set in .env

def send_telegram_message(message: str):
    if not BOT_TOKEN or not CHAT_ID:
        print("⚠️ Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID")
        return

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }

    try:
        response = requests.post(url, data=data)
        if response.status_code == 200:
            print("✅ Notification sent to Telegram.")
        else:
            print(f"❌ Failed to send message: {response.text}")
    except Exception as e:
        print(f"❌ Error sending Telegram message: {e}")

send_telegram_message("📰 New articles for labeling are now ready!\nUse /label to begin reviewing.")

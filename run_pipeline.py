import requests
import os
from dotenv import load_dotenv

# Load token and chat ID from .env
load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")  # Should be the full group ID, e.g. -1002243640008
THREAD_ID = os.getenv("TELEGRAM_THREAD_ID")  # This is the topic/thread ID, e.g. 1981

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

    # If thread ID is set, include it in the message pay load
    if THREAD_ID:
        data["message_thread_id"] = int(THREAD_ID)

    try:
        response = requests.post(url, data=data)
        if response.status_code == 200:
            print("✅ Notification sent to Telegram.")
        else:
            print(f"❌ Failed to send message: {response.text}")
    except Exception as e:
        print(f"❌ Error sending Telegram message: {e}")

send_telegram_message("📰 New articles for labeling are now ready!\nUse /label to begin reviewing.")

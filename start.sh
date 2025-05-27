#!/bin/bash

# Force clean install of correct telegram bot
pip uninstall -y telegram telegram-bot python-telegram-bot || true
pip install python-telegram-bot==13.15 pandas python-dotenv requests

# Start your bot
python label_bot.py
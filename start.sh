#!/bin/bash

# Uninstall broken versions
pip uninstall -y telegram telegram-bot || true

# Install only the correct one
pip install python-telegram-bot==13.15 pandas python-dotenv requests urllib3

# Start bot
python label_bot.py

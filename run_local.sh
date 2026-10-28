#!/bin/bash
cd "$(dirname "$0")"
echo "🚀 Instagram Post Telegram Botu Yerelde Başlatılıyor..."
if [ -d "venv" ]; then
    source venv/bin/activate
fi
exec python3 bot.py

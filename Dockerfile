FROM python:3.11-slim

WORKDIR /app

# Node.js ve Chromium kurulumu (TweetShot headless capture için)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    gnupg \
    chromium \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# TweetShot bağımlılıkları ve kodları
COPY shots/tweet-shot/package*.json ./shots/tweet-shot/
RUN cd shots/tweet-shot && npm install --omit=dev

COPY shots/ ./shots/
COPY bot.py .

ENV PYTHONUNBUFFERED=1
ENV PUPPETEER_EXECUTABLE_PATH=/usr/bin/chromium

CMD ["python", "bot.py"]

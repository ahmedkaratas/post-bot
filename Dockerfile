FROM python:3.11-slim

WORKDIR /app

# Node.js, Chromium, FFmpeg ve yazı tipleri (TweetShot headless capture, video kurgu ve Türkçe/Emoji desteği)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    gnupg \
    ffmpeg \
    chromium \
    fonts-liberation \
    fonts-noto-color-emoji \
    fonts-dejavu-core \
    fonts-freefont-ttf \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# TweetShot bağımlılıkları ve kodları
COPY shots/tweet-shot/package*.json ./shots/tweet-shot/
RUN cd shots/tweet-shot && npm install --omit=dev

COPY shots/ ./shots/
COPY comment_video/ ./comment_video/
COPY *.py ./

ENV PYTHONUNBUFFERED=1
ENV PUPPETEER_EXECUTABLE_PATH=/usr/bin/chromium
ENV PORT=8080

VOLUME ["/app/data"]

EXPOSE 8080

CMD ["python", "bot.py"]

FROM python:3.11-slim

WORKDIR /app

# Sistem gereksinimleri ve bağımlılıklar
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot.py .

ENV PYTHONUNBUFFERED=1

CMD ["python", "bot.py"]

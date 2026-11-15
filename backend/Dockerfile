FROM python:3.12-slim

WORKDIR /app

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Основной сайт
COPY backend/app ./app
COPY web ./web

# Telegram-бот
COPY bot/requirements.txt ./bot/requirements.txt
RUN pip install --no-cache-dir -r ./bot/requirements.txt
COPY bot/main.py ./bot/main.py

RUN mkdir -p /app/uploads

# Запуск сайта остаётся прежним
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
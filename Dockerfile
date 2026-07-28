FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

COPY . .

# bothost.ru persists /app/data across redeploys. The app resolves relative
# DB_PATH/JOBS_DB_PATH inside DATA_DIR, so setting DATA_DIR is enough to keep
# poll history and scheduled reminders in the persistent volume. (Absolute
# ENV DB_PATH here would be overridden by the panel's env vars anyway.)
ENV DATA_DIR=/app/data
RUN mkdir -p /app/data

CMD ["python", "-m", "bot.main"]

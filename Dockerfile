FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

COPY . .

# bothost.ru persists /app/data across redeploys; keep the sqlite databases there
# so poll history and scheduled reminders survive a rebuild.
ENV DATA_DIR=/app/data
ENV DB_PATH=/app/data/poll_bot.sqlite3
ENV JOBS_DB_PATH=/app/data/jobs.sqlite3
RUN mkdir -p /app/data

CMD ["python", "-m", "bot.main"]

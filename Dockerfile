FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    NEWSFEED_DB=/data/newsfeed.db \
    TZ=Europe/Berlin

WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend/app backend/app
COPY frontend frontend
COPY config config

RUN useradd --system --uid 1000 newsfeed && mkdir -p /data && chown newsfeed /data
USER newsfeed

WORKDIR /app/backend
EXPOSE 8080
HEALTHCHECK --interval=60s --timeout=5s --start-period=20s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/api/health', timeout=4)"

# --no-access-log: keine IP-Adressen im Log. --workers 1: genau ein Scheduler.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1", "--no-access-log", "--proxy-headers"]

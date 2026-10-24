FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg fonts-dejavu-core && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY content_manager ./content_manager
COPY alembic.ini ./alembic.ini
COPY migrations ./migrations
RUN useradd -r -m -u 10001 appuser && mkdir -p /tmp/content_manager && chown -R appuser:appuser /tmp/content_manager /app
USER appuser
CMD ["sh", "-c", "if [ \"$RUN_MODE\" = worker ]; then rq worker -u \"$REDIS_URL\" media; else uvicorn content_manager.app:app --host 0.0.0.0 --port \"${PORT:-8000}\"; fi"]

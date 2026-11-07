# Development image: Python + dependencies only. The source code is NOT
# copied in; compose.yaml mounts the project folder at /app, so edits on
# the host are visible immediately without rebuilding.
# Rebuild only when requirements.txt changes: docker compose build
FROM python:3.14-slim

WORKDIR /app
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

ENV PYTHONPATH=/app \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

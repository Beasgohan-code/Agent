# Agent — Telegram bot (Render Background Worker)
FROM python:3.11-slim

# Unbuffered output so Render shows logs immediately; no .pyc clutter.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app

WORKDIR /app

# Dependencies first so code edits do not invalidate this layer.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir --no-deps richgram==0.2.0

# Application code only — no secrets are ever baked into the image.
COPY start.py ./
COPY agent ./agent

# Run unprivileged — and give that user the data directory it writes to.
# Without the chown, the lease and every store fail with PermissionError.
RUN useradd --create-home --uid 10001 agent \
    && mkdir -p /app/data \
    && chown -R agent:agent /app
USER agent

# Long polling: the process must stay in the foreground and handle SIGTERM.
STOPSIGNAL SIGTERM
CMD ["python", "start.py"]

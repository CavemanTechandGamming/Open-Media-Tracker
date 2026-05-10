# Lightweight production image — Python 3.14 slim (~ suitable for low-power homelab hosts)
FROM python:3.14-slim-bookworm

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_PORT=8383 \
    CONFIG_PATH=/config

RUN groupadd --gid 1000 appuser \
    && useradd --uid 1000 --gid appuser --no-create-home --shell /bin/bash appuser

COPY requirements.txt .
RUN pip install --no-cache-dir --no-compile -r requirements.txt

COPY . .

RUN sed -i 's/\r$//' /app/docker-entrypoint.sh \
    && chmod +x /app/docker-entrypoint.sh \
    && mkdir -p /config/cache/posters /config/logs \
    && chown -R appuser:appuser /app

EXPOSE 8383

# Entrypoint runs as root long enough to fix /config ownership on the mounted volume, then drops privileges.
ENTRYPOINT ["/bin/sh", "/app/docker-entrypoint.sh"]
# Port is read from APP_PORT at runtime (no rebuild required to change it).
CMD ["sh", "-c", "exec uvicorn main:app --host 0.0.0.0 --port \"${APP_PORT:-8383}\""]

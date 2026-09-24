FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PPU_STATE_DIR=/data/state

# umbrelOS runs the containers as uid/gid 1000 and owns the bind mounts.
RUN groupadd --gid 1000 ppu \
    && useradd --uid 1000 --gid 1000 --create-home --shell /usr/sbin/nologin ppu \
    && mkdir -p /data/archive /data/staging /data/control /data/state \
    && chown -R 1000:1000 /data

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app

USER 1000:1000
EXPOSE 8000

# docker-compose.yml overrides this per service: uvicorn for the web UI,
# watch for the worker. A bare 'docker run' gives the loop.
CMD ["python", "-m", "app.cli", "watch", "--poll-seconds", "60"]

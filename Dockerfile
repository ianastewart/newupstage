FROM ghcr.io/astral-sh/uv:trixie-slim

# uv, which installs the requirements from pyproject.toml and uv.lock
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_PYTHON_INSTALL_DIR=/opt/python \
    PATH="/opt/venv/bin:$PATH" \
    MEDIA_ROOT=/data/media

WORKDIR /app

# Install system dependencies needed by our app
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Requirements first, so this layer is rebuilt only when they change
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --locked --no-dev

COPY upstage ./upstage
COPY docker-entrypoint.sh /docker-entrypoint.sh

WORKDIR /app/upstage

# The static files go in the image (served by WhiteNoise); the key here is only for this step.
RUN DJANGO_DEBUG=0 DJANGO_SECRET_KEY=build-only python manage.py collectstatic --noinput

# Not run as root; /data/media is where uploaded images are kept (a volume in docker-compose.yml)
RUN useradd --system --uid 1000 --home-dir /app upstage \
    && mkdir -p /data/media && chown upstage /data/media \
    && chmod +x /docker-entrypoint.sh
USER upstage

EXPOSE 8000
ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--access-logfile", "-", "--no-control-socket"]

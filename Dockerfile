# ---------- Stage 1: Frontend (Build static assets) ----------
FROM node:18-alpine AS frontend-builder
WORKDIR /app/theme

# ---------- Stage 2: Backend (Create the final production image) ----------
# Use a more recent and secure base image
FROM python:3.11-slim-bookworm AS backend-builder

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PATH="/py/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1

# Create a non-root user and directories first
RUN adduser \
    --disabled-password \
    --no-create-home \
    django-user
WORKDIR /app

# postgresql-client: admin full backup/restore (pg_dump / pg_restore)
# gosu: drop root -> django-user after fixing /vol/web permissions for nginx
RUN apt-get update && \
    apt-get install -y --no-install-recommends postgresql-client gosu && \
    rm -rf /var/lib/apt/lists/*

# Create virtualenv and install dependencies
RUN python -m venv /py
# 1. Install dependencies BEFORE copying the application code to optimize caching
COPY ./requirements.txt /tmp/requirements.txt

RUN /py/bin/pip install --upgrade pip && \
    /py/bin/pip install -r /tmp/requirements.txt

# Copy application code
COPY ./app /app
COPY ./scripts/docker-entrypoint.sh /docker-entrypoint.sh
# Set ownership and permissions for the non-root user
RUN mkdir -p /vol/web/media && \
    mkdir -p /vol/web/static && \
    chown -R django-user:django-user /vol /app /py && \
    chmod -R 755 /vol && \
    sed -i 's/\r$//' /docker-entrypoint.sh && \
    chmod +x /docker-entrypoint.sh

# Stay root so the entrypoint can chown/chmod the runtime volume, then gosu.
ENTRYPOINT ["/docker-entrypoint.sh"]

# Expose the port
EXPOSE 8324

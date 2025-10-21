# distributorplatform/Dockerfile

# ---------- Stage 1: Frontend (Build static assets) ----------
FROM node:18-alpine AS frontend-builder
WORKDIR /app/theme
# Create the static directory
RUN mkdir -p /app/theme/static


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

# Create virtualenv and install dependencies
RUN python -m venv /py
# 1. Install dependencies BEFORE copying the application code to optimize caching
COPY ./requirements.txt /tmp/requirements.txt
RUN pip install --upgrade pip && \
    pip install -r /tmp/requirements.txt

# Copy application code
COPY ./app /app
# Copy built frontend assets from the first stage
COPY --from=frontend-builder /app/theme/static ./theme/static

# Set ownership and permissions for the non-root user
RUN mkdir -p /vol/web/media && \
    mkdir -p /vol/web/static && \
    chown -R django-user:django-user /vol /app && \
    chmod -R 755 /vol

# Switch to the non-root user
USER django-user

# Expose the port
EXPOSE 8000

FROM python:3.11-slim

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Install system dependencies
RUN apt-get update && apt-get install -y\
    build-essential \
    libsndfile1 \
    ffmpeg \
    pkg-config \
    libavcodec-dev \
    libavformat-dev \
    libavutil-dev \
    libswscale-dev \
    libswresample-dev \
    libavdevice-dev \
    libavfilter-dev \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Create a non-root user
RUN adduser --disabled-password --gecos "" appuser

# Install dependencies using uv
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

# Copy application code
COPY agent.py .

# Ensure appuser owns the app directory
RUN chown -R appuser:appuser /app

# Switch to non-root user
USER appuser

# Entry point for livekit-agents
CMD ["uv", "run", "python", "agent.py", "dev"]

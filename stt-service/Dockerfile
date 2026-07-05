FROM python:3.11

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
RUN apt-get autoclean
# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    git \
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
COPY pyproject.toml ./
RUN uv pip install --no-cache --system -r pyproject.toml

# Copy application code
COPY server.py whisper_online.py line_packet.py ./

# Create cache directory and set permissions
RUN mkdir -p /model-cache && chown appuser:appuser /model-cache

# Switch to non-root user
USER appuser

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]

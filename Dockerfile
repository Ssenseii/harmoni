FROM python:3.13-slim

# Prevent Python from writing .pyc files and ensure logs flush immediately
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# System dependencies:
# - ffmpeg: required for yt-dlp audio extraction/post-processing
# - curl: useful for health checks and diagnostics
# - ca-certificates: required for HTTPS downloads
# - tini: proper signal handling (especially for long-running downloads)
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ffmpeg \
        curl \
        ca-certificates \
        tini \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies first to leverage Docker layer caching
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r /app/requirements.txt

# Copy the application code
COPY . /app

# Create necessary directories and set appropriate permissions
RUN mkdir -p /app/data /app/data/exportify /app/music /app/export \
    && useradd -m -u 10001 appuser \
    && chown -R appuser:appuser /app

USER appuser

# Reserved for potential future web interface
EXPOSE 8000

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "main.py"]

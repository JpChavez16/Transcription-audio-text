FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    ffmpeg \
    redis-tools \
    wget \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Verificar FFmpeg
RUN ffmpeg -version && ffprobe -version

# Set working directory
WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY src/ ./src/
COPY config/ ./config/

# Environment variables
ENV PYTHONUNBUFFERED=1
ENV REDIS_HOST=localhost
ENV REDIS_PORT=6379
ENV AWS_DEFAULT_REGION=us-east-1

# STREAMING MODE - No necesita descargar Whisper models
# Solo usa FFmpeg para procesamiento

# Expose port
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

# Run application
CMD ["python", "-m", "src.fog_node.main"]
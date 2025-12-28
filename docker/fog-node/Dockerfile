FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    ffmpeg \
    curl \
    wget \
    git \
    && rm -rf /var/lib/apt/lists/*

# Verify FFmpeg installation
RUN ffmpeg -version && ffprobe -version

# Set working directory
WORKDIR /app

# Copy requirements first (for caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# Force install latest yt-dlp from master to fix YouTube bot detection issues
RUN pip install --no-cache-dir --force-reinstall https://github.com/yt-dlp/yt-dlp/archive/master.zip

# Copy application code
COPY src/ ./src/

# Create logs directory
RUN mkdir -p /app/logs

# Environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app
ENV AWS_DEFAULT_REGION=us-east-1

# Expose port
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

# Run application
CMD ["python", "-m", "src.main"]
# Use Python slim (CPU version - GPU optional)
FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    ffmpeg \
    curl \
    wget \
    git \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Install Whisper (CPU version)
RUN pip install --no-cache-dir openai-whisper==20231117

# Pre-download Whisper models (optional, speeds up first run)
RUN python -c "import whisper; whisper.load_model('small', download_root='/root/.cache/whisper')" || true

# Copy application code
COPY src/ ./src/

# Environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app
ENV WHISPER_MODEL=small
ENV AWS_DEFAULT_REGION=us-east-1

# Expose port
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=30s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

# Run application
CMD ["python", "-m", "src.main"]
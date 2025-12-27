FROM nvidia/cuda:11.8.0-cudnn8-runtime-ubuntu22.04

# Install system dependencies
RUN apt-get update && apt-get install -y \
    python3.11 \
    python3-pip \
    ffmpeg \
    git \
    wget \
    portaudio19-dev \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements
COPY requirements.txt .

# Install Python dependencies
RUN pip3 install --no-cache-dir -r requirements.txt

# Install Whisper and faster-whisper for GPU acceleration
RUN pip3 install --no-cache-dir \
    openai-whisper \
    faster-whisper \
    whisper-live \
    torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118

# Pre-download Whisper models
RUN python3 -c "import whisper; \
    whisper.load_model('small'); \
    whisper.load_model('medium'); \
    whisper.load_model('large-v3')"

# Copy application code
COPY src/ ./src/

# Environment variables
ENV PYTHONUNBUFFERED=1
ENV CUDA_VISIBLE_DEVICES=0
ENV WHISPER_MODEL=medium
ENV AWS_DEFAULT_REGION=us-east-1
ENV WHISPER_LIVE_ENABLED=true

# Expose ports
EXPOSE 8080 9090

# Health check
HEALTHCHECK --interval=30s --timeout=30s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

# Run both services (HTTP API + WhisperLive)
CMD ["python3", "-m", "src.whisper_service.main"]
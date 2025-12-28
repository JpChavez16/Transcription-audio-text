"""
Fog Node Main Application - STREAMING VERSION
Procesa video/audio SIN descargar archivo completo
Usa FFmpeg pipe para streaming directo
"""
import os
import logging
import subprocess
import hashlib
import json
from typing import Dict, Optional
from datetime import datetime

from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel, HttpUrl
import boto3
import yt_dlp

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize FastAPI
app = FastAPI(
    title="Fog Node Streaming Service",
    version="3.0.0",
    description="Processes media using FFmpeg streaming (no full download)"
)

# Initialize AWS services
s3_client = boto3.client('s3')
dynamodb = boto3.resource('dynamodb')

# Configuration from environment
PROCESSED_BUCKET = os.getenv('PROCESSED_AUDIO_BUCKET')
JOBS_TABLE_NAME = os.getenv('JOBS_TABLE')
CHUNK_DURATION = 30  # seconds per chunk
SAMPLE_RATE = 16000  # Hz
CHANNELS = 1  # Mono

# DynamoDB table
jobs_table = dynamodb.Table(JOBS_TABLE_NAME) if JOBS_TABLE_NAME else None


class ProcessRequest(BaseModel):
    url: HttpUrl
    job_id: str
    model_size: str = "medium"


class ProcessStatus(BaseModel):
    job_id: str
    status: str
    progress: float
    message: str
    chunks_processed: int = 0


@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "service": "Fog Node Streaming Service",
        "version": "3.0.0",
        "status": "running",
        "features": ["streaming", "no-download", "ffmpeg-pipe"]
    }


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    try:
        # Check FFmpeg
        ffmpeg_ok = check_ffmpeg()

        # Check S3 access
        s3_ok = check_s3_access()

        # Check DynamoDB access
        dynamodb_ok = check_dynamodb_access()

        all_healthy = ffmpeg_ok and s3_ok and dynamodb_ok

        return {
            "status": "healthy" if all_healthy else "degraded",
            "version": "3.0.0",
            "services": {
                "ffmpeg": "ok" if ffmpeg_ok else "error",
                "s3": "ok" if s3_ok else "error",
                "dynamodb": "ok" if dynamodb_ok else "error"
            },
            "processing_method": "streaming_no_download"
        }
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(status_code=503, detail="Service unhealthy")


def check_ffmpeg() -> bool:
    """Verify FFmpeg is installed"""
    try:
        subprocess.run(
            ['ffmpeg', '-version'],
            capture_output=True,
            check=True,
            timeout=5
        )
        return True
    except:
        return False


def check_s3_access() -> bool:
    """Verify S3 access"""
    try:
        if not PROCESSED_BUCKET:
            return False
        s3_client.head_bucket(Bucket=PROCESSED_BUCKET)
        return True
    except:
        return False


def check_dynamodb_access() -> bool:
    """Verify DynamoDB access"""
    try:
        if not jobs_table:
            return False
        jobs_table.table_status
        return True
    except:
        return False


@app.post("/process")
async def process_media(request: ProcessRequest, background_tasks: BackgroundTasks):
    """
    Process media SIN descargar completo
    Usa FFmpeg pipe para streaming directo
    """
    url = str(request.url)
    job_id = request.job_id

    logger.info(f"Received processing request for job {job_id}")

    # Start processing in background
    background_tasks.add_task(
        process_streaming_task,
        url,
        job_id,
        request.model_size
    )

    return {
        "job_id": job_id,
        "status": "processing",
        "message": "Streaming processing started - NO full download",
        "processing_method": "streaming"
    }
    return {
        "job_id": job_id,
        "status": "processing",
        "message": "Streaming processing started - NO full download",
        "processing_method": "streaming"
    }


def get_stream_url(url: str) -> str:
    """
    Extract direct stream URL using yt-dlp
    """
    try:
        ydl_opts = {
            'format': 'bestaudio/best',
            'quiet': True,
            'no_warnings': True,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            return info['url']
    except Exception as e:
        logger.warning(f"yt-dlp extraction failed: {e}. using original URL.")
        return url


async def process_streaming_task(url: str, job_id: str, model_size: str):
    """
    Background task para procesamiento streaming
    NO descarga el archivo completo
    """
    try:
        logger.info(f"Starting streaming processing for job {job_id}")
        update_job_status(job_id, "streaming", 5,
                          "Starting FFmpeg pipe streaming")

        # 1. Obtener metadata sin descargar
        logger.info(f"Resolving stream URL for {url}")
        stream_url = get_stream_url(url)

        logger.info(f"Getting metadata for stream")
        metadata = get_media_metadata(stream_url)
        duration = metadata.get('duration', 0)

        logger.info(f"Media duration: {duration}s")
        update_job_status(job_id, "streaming", 10,
                          f"Media duration: {duration}s")

        # 2. Procesar con FFmpeg pipe (NO descarga completa)
        logger.info(f"Starting FFmpeg streaming for {url}")
        chunks_info = stream_and_chunk_audio(stream_url, job_id, duration)

        logger.info(
            f"Streaming completed. Processed {len(chunks_info)} chunks")
        update_job_status(
            job_id,
            "completed",
            100,
            f"Streaming processing completed - {len(chunks_info)} chunks created"
        )

        # 3. Store metadata
        result = {
            "job_id": job_id,
            "status": "completed",
            "audio_duration": duration,
            "chunks_count": len(chunks_info),
            "chunks": chunks_info,
            "processing_method": "streaming_no_download",
            "model_size": model_size
        }

        logger.info(f"Job {job_id} completed successfully")
        return result

    except Exception as e:
        logger.error(f"Error processing job {job_id}: {e}", exc_info=True)
        update_job_status(job_id, "failed", 0, f"Processing failed: {str(e)}")
        raise


def get_media_metadata(url: str) -> Dict:
    """
    Obtiene metadata del video SIN descargarlo
    Usa ffprobe
    """
    cmd = [
        'ffprobe',
        '-v', 'quiet',
        '-print_format', 'json',
        '-show_format',
        '-show_streams',
        url
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
            timeout=30
        )

        data = json.loads(result.stdout)

        # Extract duration
        duration = float(data.get('format', {}).get('duration', 0))

        return {
            'duration': duration,
            'format': data.get('format', {}).get('format_name'),
            'has_audio': any(
                s.get('codec_type') == 'audio'
                for s in data.get('streams', [])
            )
        }
    except subprocess.TimeoutExpired:
        logger.error("FFprobe timeout")
        raise Exception("Timeout getting media metadata")
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON from ffprobe: {e}")
        raise Exception("Invalid media format")
    except Exception as e:
        logger.error(f"Error getting metadata: {e}")
        return {'duration': 0, 'has_audio': True}


    """
    Procesa audio usando FFmpeg pipe
    NO descarga el archivo completo - streaming directo
    """
    chunks_info = []

    # FFmpeg command for streaming RAW PCM (no header issues)
    ffmpeg_cmd = [
        'ffmpeg',
        '-i', url,
        '-f', 's16le',       # Raw PCM signed 16-bit little-endian
        '-acodec', 'pcm_s16le',
        '-ar', str(SAMPLE_RATE),
        '-ac', str(CHANNELS),
        '-loglevel', 'error',
        'pipe:1'
    ]

    logger.info(f"Starting FFmpeg pipe for {job_id}")

    try:
        process = subprocess.Popen(
            ffmpeg_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=10**8
        )

        # Calculate chunk size in bytes
        # 30 seconds * 16000 Hz * 2 bytes * 1 channel
        chunk_size_bytes = CHUNK_DURATION * SAMPLE_RATE * 2 * CHANNELS

        chunk_num = 0
        total_chunks = int(total_duration / CHUNK_DURATION) + 1

        logger.info(f"Starting to process chunks (expected: {total_chunks})")

        while True:
            # Read raw PCM chunk
            pcm_data = process.stdout.read(chunk_size_bytes)

            if not pcm_data:
                break

            # Create distinct WAV header for THIS chunk
            wav_header = create_wav_header(len(pcm_data))
            chunk_wav = wav_header + pcm_data

            chunk_key = f"audio/{job_id}/chunks/chunk_{chunk_num:03d}.wav"

            logger.info(
                f"Uploading chunk {chunk_num} ({len(chunk_wav)} bytes)")

            s3_client.put_object(
                Bucket=PROCESSED_BUCKET,
                Key=chunk_key,
                Body=chunk_wav,
                ContentType='audio/wav'
            )

            chunks_info.append({
                'chunk_id': chunk_num,
                's3_key': chunk_key,
                'duration': len(pcm_data) / (SAMPLE_RATE * 2 * CHANNELS),
                'size_bytes': len(chunk_wav)
            })

            chunk_num += 1

            # Update progress
            progress = min(90, 10 + (chunk_num / total_chunks) * 80)
            update_job_status(
                job_id,
                "streaming",
                progress,
                f"Processed {chunk_num}/{total_chunks} chunks via streaming"
            )

        process.wait(timeout=30)

        if process.returncode != 0:
            stderr = process.stderr.read().decode()
            logger.error(f"FFmpeg error: {stderr}")
            raise Exception(f"FFmpeg failed: {stderr}")

        return chunks_info

    except Exception as e:
        if 'process' in locals():
            process.kill()
        raise Exception(f"Streaming error: {str(e)}")


def create_wav_header(data_size: int) -> bytes:
    """Create a valid WAV header for 16-bit Mono 16kHz PCM"""
    import struct
    
    # RIFF chunk
    header = b'RIFF'
    header += struct.pack('<I', data_size + 36)   # ChunkSize (Total - 8)
    header += b'WAVE'
    
    # fmt subchunk
    header += b'fmt '
    header += struct.pack('<I', 16)               # Subchunk1Size (16 for PCM)
    header += struct.pack('<H', 1)                # AudioFormat (1 = PCM)
    header += struct.pack('<H', CHANNELS)         # NumChannels
    header += struct.pack('<I', SAMPLE_RATE)      # SampleRate
    
    byte_rate = SAMPLE_RATE * CHANNELS * 2        # 16-bit = 2 bytes
    header += struct.pack('<I', byte_rate)        # ByteRate
    
    block_align = CHANNELS * 2
    header += struct.pack('<H', block_align)      # BlockAlign
    header += struct.pack('<H', 16)               # BitsPerSample
    
    # data subchunk
    header += b'data'
    header += struct.pack('<I', data_size)        # Subchunk2Size
    
    return header


def update_job_status(job_id: str, status: str, progress: float, message: str):
    """Update job status in DynamoDB"""
    if not jobs_table:
        logger.warning("DynamoDB table not configured, skipping status update")
        return

    try:
        jobs_table.update_item(
            Key={"jobId": job_id},
            UpdateExpression="SET #status = :status, progress = :progress, message = :message, updatedAt = :updated",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={
                ":status": status,
                ":progress": int(progress),
                ":message": message,
                ":updated": int(datetime.utcnow().timestamp())
            }
        )
        logger.info(
            f"Updated job {job_id}: {status} - {progress}% - {message}")
    except Exception as e:
        logger.error(f"Error updating job status: {e}")


@app.get("/status/{job_id}")
async def get_status(job_id: str):
    """Get processing status"""
    if not jobs_table:
        raise HTTPException(status_code=503, detail="DynamoDB not configured")

    try:
        response = jobs_table.get_item(Key={"jobId": job_id})

        if "Item" not in response:
            raise HTTPException(status_code=404, detail="Job not found")

        return response["Item"]
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/metrics")
async def get_metrics():
    """Get fog node metrics"""
    return {
        "processing_method": "streaming_no_download",
        "version": "3.0.0",
        "chunk_duration": CHUNK_DURATION,
        "sample_rate": SAMPLE_RATE,
        "channels": CHANNELS
    }

if __name__ == "__main__":
    import uvicorn

    logger.info("Starting Fog Node Streaming Service v3.0.0")
    logger.info(f"Processed bucket: {PROCESSED_BUCKET}")
    logger.info(f"Jobs table: {JOBS_TABLE_NAME}")

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8080,
        log_level="info"
    )

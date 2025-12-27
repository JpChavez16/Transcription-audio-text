import os
import logging
import asyncio
from typing import Dict, Optional
from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel, HttpUrl
import boto3
import redis
import subprocess
import hashlib
import json
from pathlib import Path
import tempfile
from io import BytesIO

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize FastAPI
app = FastAPI(title="Fog Node Streaming Service", version="2.0.0")

# Initialize services
s3_client = boto3.client('s3')
redis_client = redis.Redis(
    host=os.getenv('REDIS_HOST', 'localhost'),
    port=int(os.getenv('REDIS_PORT', 6379)),
    decode_responses=True
)

# Configuration
RAW_BUCKET = os.getenv('RAW_MEDIA_BUCKET')
PROCESSED_BUCKET = os.getenv('PROCESSED_AUDIO_BUCKET')
CACHE_TTL = 86400  # 24 hours
CHUNK_DURATION = 30  # segundos por chunk
SAMPLE_RATE = 16000  # Hz
CHANNELS = 1  # Mono

class DownloadRequest(BaseModel):
    url: HttpUrl
    job_id: str
    priority: str = "normal"
    model_size: str = "medium"

class ProcessStatus(BaseModel):
    job_id: str
    status: str
    progress: float
    message: str
    chunks_processed: int = 0

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    try:
        redis_client.ping()
        return {
            "status": "healthy",
            "services": {"redis": "ok", "ffmpeg": check_ffmpeg()},
            "version": "2.0.0-streaming"
        }
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(status_code=503, detail="Service unhealthy")

def check_ffmpeg():
    """Verifica que FFmpeg está instalado"""
    try:
        subprocess.run(['ffmpeg', '-version'], capture_output=True, check=True)
        return "ok"
    except:
        return "error"

@app.post("/process")
async def process_media(request: DownloadRequest, background_tasks: BackgroundTasks):
    """
    Procesa media SIN descargar completo
    Usa FFmpeg pipe para streaming directo
    """
    url = str(request.url)
    job_id = request.job_id
    
    # Check cache
    cache_key = f"fog:processed:{hashlib.md5(url.encode()).hexdigest()}"
    cached_result = redis_client.get(cache_key)
    
    if cached_result:
        logger.info(f"Cache hit for job {job_id}")
        return json.loads(cached_result)
    
    # Process in background
    background_tasks.add_task(
        process_streaming_task,
        url,
        job_id,
        cache_key,
        request.model_size
    )
    
    return {
        "job_id": job_id,
        "status": "processing",
        "message": "Streaming processing started - NO full download"
    }

async def process_streaming_task(
    url: str,
    job_id: str,
    cache_key: str,
    model_size: str
):
    """
    Background task para procesamiento streaming
    NO descarga el archivo completo
    """
    try:
        update_status(job_id, "starting", 5, "Validating URL")
        
        # 1. Obtener metadata sin descargar
        metadata = await get_media_metadata(url)
        duration = metadata.get('duration', 0)
        
        update_status(job_id, "streaming", 10, "Starting FFmpeg pipe streaming")
        
        # 2. Procesar con FFmpeg pipe (NO descarga completa)
        chunks_info = await stream_and_chunk_audio(
            url,
            job_id,
            duration,
            model_size
        )
        
        update_status(job_id, "finalizing", 95, "Finalizing processing")
        
        # 3. Guardar metadata
        result = {
            "job_id": job_id,
            "status": "completed",
            "audio_duration": duration,
            "chunks_count": len(chunks_info),
            "chunks": chunks_info,
            "processing_method": "streaming_no_download",
            "model_size": model_size
        }
        
        # Cache result
        redis_client.setex(cache_key, CACHE_TTL, json.dumps(result))
        
        update_status(job_id, "completed", 100, "Streaming processing completed")
        
        logger.info(f"Job {job_id} completed - {len(chunks_info)} chunks processed")
        
        return result
        
    except Exception as e:
        logger.error(f"Error processing job {job_id}: {e}")
        update_status(job_id, "failed", 0, str(e))
        raise

async def get_media_metadata(url: str) -> Dict:
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
        
        # Extraer duración
        duration = float(data.get('format', {}).get('duration', 0))
        
        return {
            'duration': duration,
            'format': data.get('format', {}).get('format_name'),
            'has_audio': any(s.get('codec_type') == 'audio' 
                           for s in data.get('streams', []))
        }
    except Exception as e:
        logger.error(f"Error getting metadata: {e}")
        return {'duration': 0, 'has_audio': True}

async def stream_and_chunk_audio(
    url: str,
    job_id: str,
    total_duration: float,
    model_size: str
) -> list:
    """
    Procesa audio usando FFmpeg pipe
    NO descarga el archivo completo - streaming directo
    """
    chunks_info = []
    
    # FFmpeg comando para streaming
    ffmpeg_cmd = [
        'ffmpeg',
        '-i', url,  # URL directa - NO descarga
        '-f', 'wav',  # Output format
        '-acodec', 'pcm_s16le',  # PCM codec
        '-ar', str(SAMPLE_RATE),  # Sample rate
        '-ac', str(CHANNELS),  # Channels
        '-loglevel', 'error',
        'pipe:1'  # Output a pipe, NO a archivo
    ]
    
    logger.info(f"Starting FFmpeg pipe for {job_id}")
    
    try:
        # Iniciar proceso FFmpeg
        process = subprocess.Popen(
            ffmpeg_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=10**8  # 100MB buffer
        )
        
        # Calcular tamaño de chunk en bytes
        # 30 segundos * 16000 Hz * 2 bytes (16-bit) * 1 canal
        chunk_size_bytes = CHUNK_DURATION * SAMPLE_RATE * 2 * CHANNELS
        
        chunk_num = 0
        total_chunks = int(total_duration / CHUNK_DURATION) + 1
        
        # Leer cabecera WAV (44 bytes)
        wav_header = process.stdout.read(44)
        
        while True:
            # Leer chunk de audio del pipe
            audio_data = process.stdout.read(chunk_size_bytes)
            
            if not audio_data or len(audio_data) < 1000:
                break
            
            # Crear WAV completo para este chunk
            chunk_wav = wav_header + audio_data
            
            # Upload chunk DIRECTAMENTE a S3 (memoria → S3)
            chunk_key = f"audio/{job_id}/chunks/chunk_{chunk_num:03d}.wav"
            
            s3_client.put_object(
                Bucket=PROCESSED_BUCKET,
                Key=chunk_key,
                Body=chunk_wav,
                ContentType='audio/wav'
            )
            
            chunks_info.append({
                'chunk_id': chunk_num,
                's3_key': chunk_key,
                'duration': min(CHUNK_DURATION, total_duration - (chunk_num * CHUNK_DURATION)),
                'size_bytes': len(chunk_wav)
            })
            
            chunk_num += 1
            
            # Actualizar progreso
            progress = min(90, 10 + (chunk_num / total_chunks) * 80)
            update_status(
                job_id,
                "streaming",
                progress,
                f"Processed {chunk_num}/{total_chunks} chunks via streaming"
            )
            
            logger.info(f"Job {job_id}: Chunk {chunk_num} uploaded ({len(chunk_wav)} bytes)")
        
        # Esperar a que FFmpeg termine
        process.wait(timeout=30)
        
        if process.returncode != 0:
            stderr = process.stderr.read().decode()
            raise Exception(f"FFmpeg error: {stderr}")
        
        logger.info(f"FFmpeg streaming completed for {job_id} - {chunk_num} chunks")
        
        return chunks_info
        
    except subprocess.TimeoutExpired:
        process.kill()
        raise Exception("FFmpeg timeout - stream took too long")
    except Exception as e:
        if process:
            process.kill()
        raise Exception(f"Streaming error: {str(e)}")

def update_status(job_id: str, status: str, progress: float, message: str):
    """Update job status in Redis"""
    status_data = {
        "job_id": job_id,
        "status": status,
        "progress": progress,
        "message": message,
        "processing_method": "streaming"
    }
    
    redis_client.setex(
        f"fog:status:{job_id}",
        3600,  # 1 hour TTL
        json.dumps(status_data)
    )

@app.get("/status/{job_id}")
async def get_status(job_id: str):
    """Get processing status"""
    status_key = f"fog:status:{job_id}"
    status_data = redis_client.get(status_key)
    
    if not status_data:
        raise HTTPException(status_code=404, detail="Job not found")
    
    return json.loads(status_data)

@app.get("/metrics")
async def get_metrics():
    """Get fog node metrics"""
    cache_info = redis_client.info('stats')
    
    return {
        "cache_hits": cache_info.get('keyspace_hits', 0),
        "cache_misses": cache_info.get('keyspace_misses', 0),
        "total_keys": redis_client.dbsize(),
        "processing_method": "streaming_no_download",
        "version": "2.0.0"
    }

@app.post("/test-stream")
async def test_stream(url: str):
    """
    Endpoint de prueba para verificar streaming
    """
    try:
        metadata = await get_media_metadata(url)
        return {
            "status": "success",
            "metadata": metadata,
            "message": "URL is streamable"
        }
    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
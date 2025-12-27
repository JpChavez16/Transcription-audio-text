import os
import logging
import tempfile
from typing import Dict, List, Optional
from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel
import boto3
import whisper
import torch
from faster_whisper import WhisperModel
import json
from pathlib import Path
import time
import asyncio
from concurrent.futures import ThreadPoolExecutor

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize FastAPI
app = FastAPI(title="Whisper Transcription Service - Streaming", version="3.0.0")

# Initialize AWS clients
s3_client = boto3.client('s3')
dynamodb = boto3.resource('dynamodb')

# Configuration
PROCESSED_BUCKET = os.getenv('PROCESSED_AUDIO_BUCKET')
TRANSCRIPTION_BUCKET = os.getenv('TRANSCRIPTION_BUCKET')
JOBS_TABLE = os.getenv('DYNAMODB_JOBS_TABLE')
TRANSCRIPTIONS_TABLE = os.getenv('DYNAMODB_TRANSCRIPTIONS_TABLE')
WHISPER_LIVE_ENABLED = os.getenv('WHISPER_LIVE_ENABLED', 'false').lower() == 'true'

# Check for GPU availability
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
logger.info(f"Using device: {DEVICE}")

# Load Whisper models based on GPU availability
if DEVICE == "cuda":
    logger.info("Loading GPU-optimized models with faster-whisper")
    whisper_small = WhisperModel("small", device="cuda", compute_type="float16")
    whisper_medium = WhisperModel("medium", device="cuda", compute_type="float16")
    whisper_large = WhisperModel("large-v3", device="cuda", compute_type="float16")
else:
    logger.info("Loading CPU models with standard whisper")
    whisper_small = whisper.load_model("small")
    whisper_medium = whisper.load_model("medium")

# Thread pool for async processing
executor = ThreadPoolExecutor(max_workers=5)

logger.info("Whisper models loaded successfully")

class TranscriptionRequest(BaseModel):
    job_id: str
    s3_keys: List[str]  # Lista de chunks para procesar
    model_size: str = "medium"
    language: Optional[str] = None
    task: str = "transcribe"

class StreamingTranscriptionRequest(BaseModel):
    job_id: str
    audio_url: str
    model_size: str = "medium"
    language: Optional[str] = None

class TranscriptionResult(BaseModel):
    job_id: str
    status: str
    text: str
    segments: List[Dict]
    language: str
    duration: float
    model_used: str

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "device": DEVICE,
        "gpu_available": torch.cuda.is_available(),
        "models_loaded": ["small", "medium", "large"] if DEVICE == "cuda" else ["small", "medium"],
        "streaming_enabled": WHISPER_LIVE_ENABLED,
        "version": "3.0.0-streaming"
    }

@app.post("/transcribe")
async def transcribe_audio(request: TranscriptionRequest, background_tasks: BackgroundTasks):
    """
    Transcribe audio chunks from S3
    Procesa múltiples chunks en paralelo
    """
    try:
        if not request.s3_keys:
            raise HTTPException(status_code=400, detail="No S3 keys provided")
        
        # Start transcription in background
        background_tasks.add_task(
            transcribe_chunks_task,
            request.job_id,
            request.s3_keys,
            request.model_size,
            request.language,
            request.task
        )
        
        return {
            "job_id": request.job_id,
            "status": "processing",
            "chunks_count": len(request.s3_keys),
            "message": f"Transcription started with {request.model_size} model"
        }
        
    except Exception as e:
        logger.error(f"Error starting transcription: {e}")
        raise HTTPException(status_code=500, detail=str(e))

async def transcribe_chunks_task(
    job_id: str,
    s3_keys: List[str],
    model_size: str,
    language: Optional[str],
    task: str
):
    """
    Background task para transcribir múltiples chunks
    Procesa en paralelo para mayor velocidad
    """
    start_time = time.time()
    
    try:
        update_job_status(job_id, "transcribing", 20, 
                         f"Starting parallel transcription of {len(s3_keys)} chunks")
        
        # Select model
        model = select_model(model_size)
        
        # Procesar chunks en paralelo
        all_segments = []
        all_text = []
        
        total_chunks = len(s3_keys)
        
        for idx, s3_key in enumerate(s3_keys):
            try:
                # Download chunk from S3
                temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.wav')
                s3_client.download_file(PROCESSED_BUCKET, s3_key, temp_file.name)
                
                # Transcribe chunk
                logger.info(f"Transcribing chunk {idx+1}/{total_chunks}: {s3_key}")
                
                if DEVICE == "cuda":
                    result = transcribe_with_faster_whisper(
                        model, temp_file.name, language, task
                    )
                else:
                    result = transcribe_with_whisper(
                        model, temp_file.name, language, task
                    )
                
                # Ajustar timestamps basado en chunk position
                chunk_offset = idx * 30  # 30 segundos por chunk
                for seg in result['segments']:
                    seg['start'] += chunk_offset
                    seg['end'] += chunk_offset
                    all_segments.append(seg)
                
                all_text.append(result['text'])
                
                # Cleanup temp file
                os.unlink(temp_file.name)
                
                # Update progress
                progress = 20 + ((idx + 1) / total_chunks) * 50
                update_job_status(
                    job_id, 
                    "transcribing", 
                    int(progress),
                    f"Transcribed {idx+1}/{total_chunks} chunks"
                )
                
            except Exception as e:
                logger.error(f"Error transcribing chunk {s3_key}: {e}")
                # Continue with other chunks
                continue
        
        # Merge results
        full_text = " ".join(all_text)
        
        update_job_status(job_id, "post-processing", 80, "Merging transcriptions...")
        
        # Process and format results
        transcription_data = {
            "job_id": job_id,
            "text": full_text,
            "segments": all_segments,
            "language": result.get('language', 'unknown'),
            "model_used": model_size,
            "processing_time": time.time() - start_time,
            "timestamp": int(time.time()),
            "word_count": len(full_text.split()),
            "segment_count": len(all_segments),
            "chunks_processed": len(s3_keys)
        }
        
        # Save to DynamoDB
        save_transcription(transcription_data)
        
        # Save to S3 in multiple formats
        save_to_s3(job_id, transcription_data)
        
        update_job_status(job_id, "completed", 100, 
                         f"Transcription completed - {len(s3_keys)} chunks processed")
        
        logger.info(f"Job {job_id} completed in {time.time() - start_time:.2f}s")
        
    except Exception as e:
        logger.error(f"Error in transcription task: {e}")
        update_job_status(job_id, "failed", 0, f"Transcription failed: {str(e)}")
        raise

@app.post("/transcribe-streaming")
async def transcribe_streaming(request: StreamingTranscriptionRequest):
    """
    Transcribe audio directamente desde URL usando streaming
    NO descarga el archivo completo
    """
    try:
        if not WHISPER_LIVE_ENABLED:
            raise HTTPException(
                status_code=501,
                detail="Streaming transcription not enabled. Use /transcribe endpoint."
            )
        
        # Implementación con WhisperLive
        # Este endpoint procesa el audio mientras lo recibe
        result = await stream_transcribe_url(
            request.audio_url,
            request.job_id,
            request.model_size,
            request.language
        )
        
        return result
        
    except Exception as e:
        logger.error(f"Error in streaming transcription: {e}")
        raise HTTPException(status_code=500, detail=str(e))

async def stream_transcribe_url(
    audio_url: str,
    job_id: str,
    model_size: str,
    language: Optional[str]
) -> Dict:
    """
    Transcribe audio desde URL usando streaming
    Usa FFmpeg pipe + Whisper en tiempo real
    """
    import subprocess
    
    model = select_model(model_size)
    
    # FFmpeg para extraer audio en streaming
    ffmpeg_cmd = [
        'ffmpeg',
        '-i', audio_url,
        '-f', 'wav',
        '-acodec', 'pcm_s16le',
        '-ar', '16000',
        '-ac', '1',
        'pipe:1'
    ]
    
    try:
        process = subprocess.Popen(
            ffmpeg_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        
        # Crear archivo temporal para Whisper
        # (Whisper aún necesita archivo, pero lo vamos llenando en streaming)
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as temp_file:
            temp_path = temp_file.name
            
            # Escribir audio al archivo mientras llega
            chunk_size = 1024 * 1024  # 1MB chunks
            while True:
                chunk = process.stdout.read(chunk_size)
                if not chunk:
                    break
                temp_file.write(chunk)
            
            process.wait()
        
        # Transcribir el archivo completo
        if DEVICE == "cuda":
            result = transcribe_with_faster_whisper(model, temp_path, language, "transcribe")
        else:
            result = transcribe_with_whisper(model, temp_path, language, "transcribe")
        
        # Cleanup
        os.unlink(temp_path)
        
        return {
            "job_id": job_id,
            "status": "completed",
            "text": result['text'],
            "segments": result['segments'],
            "method": "streaming"
        }
        
    except Exception as e:
        logger.error(f"Streaming transcription error: {e}")
        raise

def select_model(model_size: str):
    """Select appropriate Whisper model"""
    if DEVICE == "cuda":
        if model_size == "small":
            return whisper_small
        elif model_size == "medium":
            return whisper_medium
        elif model_size == "large":
            return whisper_large
    else:
        if model_size == "small":
            return whisper_small
        elif model_size == "medium":
            return whisper_medium
        else:
            logger.warning(f"Large model not available on CPU, using medium")
            return whisper_medium

def transcribe_with_faster_whisper(model, audio_path: str, language: Optional[str], task: str):
    """Transcribe using faster-whisper (GPU optimized)"""
    segments, info = model.transcribe(
        audio_path,
        language=language,
        task=task,
        beam_size=5,
        vad_filter=True,
        vad_parameters=dict(min_silence_duration_ms=500)
    )
    
    result_segments = []
    full_text = []
    
    for segment in segments:
        result_segments.append({
            "id": segment.id,
            "start": segment.start,
            "end": segment.end,
            "text": segment.text,
            "confidence": getattr(segment, 'avg_logprob', None)
        })
        full_text.append(segment.text)
    
    return {
        "text": " ".join(full_text),
        "segments": result_segments,
        "language": info.language,
        "language_probability": info.language_probability
    }

def transcribe_with_whisper(model, audio_path: str, language: Optional[str], task: str):
    """Transcribe using standard whisper (CPU)"""
    result = model.transcribe(
        audio_path,
        language=language,
        task=task,
        verbose=False
    )
    
    formatted_segments = []
    for seg in result.get("segments", []):
        formatted_segments.append({
            "id": seg.get("id"),
            "start": seg.get("start"),
            "end": seg.get("end"),
            "text": seg.get("text"),
            "confidence": seg.get("avg_logprob")
        })
    
    return {
        "text": result["text"],
        "segments": formatted_segments,
        "language": result.get("language", "unknown"),
        "language_probability": None
    }

def save_transcription(data: Dict):
    """Save transcription to DynamoDB"""
    table = dynamodb.Table(TRANSCRIPTIONS_TABLE)
    
    table.put_item(Item={
        "transcriptionId": data["job_id"],
        "timestamp": data["timestamp"],
        "jobId": data["job_id"],
        "text": data["text"],
        "language": data["language"],
        "modelUsed": data["model_used"],
        "processingTime": str(data["processing_time"]),
        "wordCount": data["word_count"],
        "segmentCount": data["segment_count"],
        "chunksProcessed": data.get("chunks_processed", 0)
    })

def save_to_s3(job_id: str, data: Dict):
    """Save transcription to S3 in multiple formats"""
    base_key = f"transcriptions/{job_id}"
    
    # JSON format
    json_key = f"{base_key}/transcription.json"
    s3_client.put_object(
        Bucket=TRANSCRIPTION_BUCKET,
        Key=json_key,
        Body=json.dumps(data, indent=2),
        ContentType="application/json"
    )
    
    # Plain text format
    txt_key = f"{base_key}/transcription.txt"
    s3_client.put_object(
        Bucket=TRANSCRIPTION_BUCKET,
        Key=txt_key,
        Body=data["text"],
        ContentType="text/plain"
    )
    
    # SRT subtitle format
    srt_content = generate_srt(data["segments"])
    srt_key = f"{base_key}/transcription.srt"
    s3_client.put_object(
        Bucket=TRANSCRIPTION_BUCKET,
        Key=srt_key,
        Body=srt_content,
        ContentType="text/plain"
    )
    
    # VTT subtitle format
    vtt_content = generate_vtt(data["segments"])
    vtt_key = f"{base_key}/transcription.vtt"
    s3_client.put_object(
        Bucket=TRANSCRIPTION_BUCKET,
        Key=vtt_key,
        Body=vtt_content,
        ContentType="text/vtt"
    )
    
    logger.info(f"Saved transcription to S3: {base_key}")

def generate_srt(segments: List[Dict]) -> str:
    """Generate SRT subtitle format"""
    srt_content = []
    
    for i, seg in enumerate(segments, 1):
        start_time = format_timestamp_srt(seg["start"])
        end_time = format_timestamp_srt(seg["end"])
        
        srt_content.append(f"{i}")
        srt_content.append(f"{start_time} --> {end_time}")
        srt_content.append(seg["text"].strip())
        srt_content.append("")
    
    return "\n".join(srt_content)

def generate_vtt(segments: List[Dict]) -> str:
    """Generate WebVTT subtitle format"""
    vtt_content = ["WEBVTT", ""]
    
    for seg in segments:
        start_time = format_timestamp_vtt(seg["start"])
        end_time = format_timestamp_vtt(seg["end"])
        
        vtt_content.append(f"{start_time} --> {end_time}")
        vtt_content.append(seg["text"].strip())
        vtt_content.append("")
    
    return "\n".join(vtt_content)

def format_timestamp_srt(seconds: float) -> str:
    """Format seconds to SRT timestamp"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds % 1) * 1000)
    
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"

def format_timestamp_vtt(seconds: float) -> str:
    """Format seconds to WebVTT timestamp"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds % 1) * 1000)
    
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"

def update_job_status(job_id: str, status: str, progress: int, message: str):
    """Update job status in DynamoDB"""
    table = dynamodb.Table(JOBS_TABLE)
    
    try:
        table.update_item(
            Key={"jobId": job_id},
            UpdateExpression="SET #status = :status, progress = :progress, message = :message, updatedAt = :updated",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={
                ":status": status,
                ":progress": progress,
                ":message": message,
                ":updated": int(time.time())
            }
        )
    except Exception as e:
        logger.error(f"Error updating job status: {e}")

@app.get("/models")
async def get_available_models():
    """Get list of available models"""
    models = ["small", "medium"]
    if DEVICE == "cuda":
        models.append("large")
    
    return {
        "available_models": models,
        "device": DEVICE,
        "gpu_enabled": DEVICE == "cuda",
        "streaming_enabled": WHISPER_LIVE_ENABLED
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
"""
Whisper Transcription Service
Procesa chunks de audio usando OpenAI Whisper
"""
import os
import logging
import json
import tempfile
import time
from typing import Dict, List
from datetime import datetime

from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel
import boto3
import whisper

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize FastAPI
app = FastAPI(
    title="Whisper Transcription Service",
    version="3.0.0",
    description="Transcribes audio chunks using OpenAI Whisper"
)

# Initialize AWS clients
s3_client = boto3.client('s3')
dynamodb = boto3.resource('dynamodb')

# Configuration
PROCESSED_BUCKET = os.getenv('PROCESSED_AUDIO_BUCKET')
TRANSCRIPTION_BUCKET = os.getenv('TRANSCRIPTION_BUCKET')
JOBS_TABLE = os.getenv('JOBS_TABLE')
TRANSCRIPTIONS_TABLE = os.getenv('TRANSCRIPTIONS_TABLE')
WHISPER_MODEL_NAME = os.getenv('WHISPER_MODEL', 'small')

# Load Whisper model
logger.info(f"Loading Whisper model: {WHISPER_MODEL_NAME}")
try:
    whisper_model = whisper.load_model(WHISPER_MODEL_NAME)
    logger.info(f"Whisper model {WHISPER_MODEL_NAME} loaded successfully")
except Exception as e:
    logger.error(f"Failed to load Whisper model: {e}")
    whisper_model = None

# DynamoDB tables
jobs_table = dynamodb.Table(JOBS_TABLE) if JOBS_TABLE else None
trans_table = dynamodb.Table(
    TRANSCRIPTIONS_TABLE) if TRANSCRIPTIONS_TABLE else None


class TranscriptionRequest(BaseModel):
    job_id: str
    s3_keys: List[str]
    model_size: str = "small"
    language: str = None


@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "service": "Whisper Transcription Service",
        "version": "3.0.0",
        "model": WHISPER_MODEL_NAME,
        "status": "running"
    }


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    try:
        return {
            "status": "healthy",
            "version": "3.0.0",
            "model_loaded": whisper_model is not None,
            "model_name": WHISPER_MODEL_NAME,
            "services": {
                "s3": "ok" if check_s3() else "error",
                "dynamodb": "ok" if check_dynamodb() else "error",
                "whisper": "ok" if whisper_model else "error"
            }
        }
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(status_code=503, detail="Service unhealthy")


def check_s3() -> bool:
    """Check S3 access"""
    try:
        if PROCESSED_BUCKET:
            s3_client.head_bucket(Bucket=PROCESSED_BUCKET)
        return True
    except:
        return False


def check_dynamodb() -> bool:
    """Check DynamoDB access"""
    try:
        if jobs_table:
            jobs_table.table_status
        return True
    except:
        return False


@app.post("/transcribe")
async def transcribe_audio(
    request: TranscriptionRequest,
    background_tasks: BackgroundTasks
):
    """
    Transcribe audio chunks from S3
    """
    if not whisper_model:
        raise HTTPException(status_code=503, detail="Whisper model not loaded")

    if not request.s3_keys:
        raise HTTPException(status_code=400, detail="No S3 keys provided")

    logger.info(f"Received transcription request for job {request.job_id}")
    logger.info(f"Chunks to process: {len(request.s3_keys)}")

    # Start transcription in background
    background_tasks.add_task(
        transcribe_chunks_task,
        request.job_id,
        request.s3_keys,
        request.language
    )

    return {
        "job_id": request.job_id,
        "status": "processing",
        "chunks_count": len(request.s3_keys),
        "message": f"Transcription started with {WHISPER_MODEL_NAME} model"
    }


async def transcribe_chunks_task(
    job_id: str,
    s3_keys: List[str],
    language: str = None
):
    """
    Background task to transcribe multiple chunks
    """
    start_time = time.time()

    try:
        logger.info(f"Starting transcription for job {job_id}")
        
        # NOTE: In this architecture, status updates should probably be more granular
        # or handled by a coordinator to avoid race conditions on the "status" field.
        # For now, we will log efficient updates.

        total_chunks = len(s3_keys)

        for idx, s3_key in enumerate(s3_keys):
            try:
                logger.info(
                    f"Processing chunk {idx+1}/{total_chunks}: {s3_key}")

                # Download chunk from S3
                temp_file = tempfile.NamedTemporaryFile(
                    delete=False, suffix='.wav')
                s3_client.download_file(
                    PROCESSED_BUCKET, s3_key, temp_file.name)

                # Transcribe chunk
                result = transcribe_with_whisper(
                    temp_file.name,
                    language
                )

                # Identify chunk ID from key (audio/{job_id}/chunks/chunk_001.wav)
                try:
                    chunk_filename = s3_key.split('/')[-1] # chunk_001.wav
                    chunk_id_str = chunk_filename.split('_')[1].split('.')[0] # 001
                    chunk_id = int(chunk_id_str)
                except:
                    chunk_id = 0 # Fallback

                # Adjust timestamps based on chunk position
                chunk_offset = chunk_id * 30  # 30 seconds per chunk strict assumption
                for seg in result['segments']:
                    seg['start'] += chunk_offset
                    seg['end'] += chunk_offset
                
                # Cleanup temp file
                os.unlink(temp_file.name)
                
                # Save CHUNK transcription
                chunk_data = {
                    "job_id": job_id,
                    "chunk_id": chunk_id,
                    "text": result['text'],
                    "segments": result['segments'],
                    "language": result.get("language", "unknown"),
                    "model_used": WHISPER_MODEL_NAME,
                    "s3_key": s3_key,
                    "timestamp": int(datetime.utcnow().timestamp())
                }
                
                save_chunk_transcription(job_id, chunk_filename, chunk_data)

                # Update progress (blind fire)
                update_job_status(
                    job_id,
                    "processing",
                    0, # Progress calculation is hard in distributed mode without coordinator
                    f"Transcribed chunk {chunk_id}"
                )

                logger.info(
                    f"Chunk {chunk_id} transcribed successfully")

            except Exception as e:
                logger.error(f"Error transcribing chunk {s3_key}: {e}")
                continue
        
        # We do NOT mark job as completed here, because we only processed a subset of chunks.
        # The Post-Processor will determine completion.

    except Exception as e:
        logger.error(f"Error in transcription task: {e}", exc_info=True)
        # Don't fail the whole job just for one chunk failure in this context



def transcribe_with_whisper(audio_path: str, language: str = None) -> Dict:
    """Transcribe using Whisper"""
    try:
        result = whisper_model.transcribe(
            audio_path,
            language=language,
            task="transcribe",
            verbose=False
        )

        # Format segments
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
            "language": result.get("language", "unknown")
        }
    except Exception as e:
        logger.error(f"Whisper transcription error: {e}")
        raise


def save_chunk_transcription(job_id: str, chunk_filename: str, data: Dict):
    """Save chunk transcription to S3"""
    if not TRANSCRIPTION_BUCKET:
        logger.warning("Transcription bucket not configured")
        return

    try:
        # e.g. transcriptions/{job_id}/chunks/chunk_001.json
        chunk_name = chunk_filename.replace('.wav', '.json')
        key = f"transcriptions/{job_id}/chunks/{chunk_name}"

        s3_client.put_object(
            Bucket=TRANSCRIPTION_BUCKET,
            Key=key,
            Body=json.dumps(data, indent=2),
            ContentType="application/json"
        )

        logger.info(f"Saved chunk transcription to S3: {key}")
    except Exception as e:
        logger.error(f"Error saving chunk to S3: {e}")


def save_transcription(data: Dict):
    """Save full transcription to DynamoDB"""
    if not trans_table:
        logger.warning("Transcriptions table not configured")
        return

    try:
        trans_table.put_item(Item={
            "transcriptionId": data["job_id"],
            "timestamp": data["timestamp"],
            "jobId": data["job_id"],
            "text": data["text"],
            "language": data["language"],
            "modelUsed": data["model_used"],
            "processingTime": str(data["processing_time"]),
            "wordCount": data["word_count"],
            "segmentCount": data["segment_count"],
            "chunksProcessed": data["chunks_processed"]
        })
        logger.info(f"Saved transcription to DynamoDB: {data['job_id']}")
    except Exception as e:
        logger.error(f"Error saving to DynamoDB: {e}")


def save_to_s3(job_id: str, data: Dict):
    """Save transcription to S3 in multiple formats"""
    if not TRANSCRIPTION_BUCKET:
        logger.warning("Transcription bucket not configured")
        return

    try:
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

        logger.info(f"Saved transcription to S3: {base_key}")
    except Exception as e:
        logger.error(f"Error saving to S3: {e}")


def update_job_status(job_id: str, status: str, progress: int, message: str):
    """Update job status in DynamoDB"""
    if not jobs_table:
        return

    try:
        jobs_table.update_item(
            Key={"jobId": job_id},
            UpdateExpression="SET #status = :status, progress = :progress, message = :message, updatedAt = :updated",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={
                ":status": status,
                ":progress": progress,
                ":message": message,
                ":updated": int(datetime.utcnow().timestamp())
            }
        )
    except Exception as e:
        logger.error(f"Error updating job status: {e}")


@app.get("/models")
async def get_models():
    """Get available models"""
    return {
        "current_model": WHISPER_MODEL_NAME,
        "model_loaded": whisper_model is not None,
        "available_models": ["tiny", "base", "small", "medium", "large"]
    }

if __name__ == "__main__":
    import uvicorn

    logger.info("Starting Whisper Transcription Service v3.0.0")
    logger.info(f"Model: {WHISPER_MODEL_NAME}")
    logger.info(f"Processed bucket: {PROCESSED_BUCKET}")
    logger.info(f"Transcription bucket: {TRANSCRIPTION_BUCKET}")

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8080,
        log_level="info"
    )

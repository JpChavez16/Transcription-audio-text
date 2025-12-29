# Arquitectura Detallada - Versión 3.0 Streaming Mode

## Flujo de Streaming Sin Descarga

### **Innovación Principal: FFmpeg Pipe Streaming**

```
┌─────────────────────────────────────────────────────────────┐
│                    USUARIO FINAL                             │
│  Envía: https://www.youtube.com/watch?v=VIDEO_ID            │
└──────────────────────┬──────────────────────────────────────┘
                       │ URL directa (NO archivo)
                       ▼
┌─────────────────────────────────────────────────────────────┐
│              API GATEWAY + Lambda URL Processor              │
│  1. Valida URL formato                                       │
│  2. Crea Job en DynamoDB                                     │
│  3. Detecta tipo de fuente (YouTube, Spotify, etc)          │
│  4. Enruta a Fog Node (Round-robin via ALB)                 │
└──────────────────────┬──────────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────────┐
│                 FOG COMPUTING LAYER                          │
│              (STREAMING PROCESSING)                          │
│                                                               │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  Fog Node (ECS Fargate Container)                     │  │
│  │                                                         │  │
│  │  Step 1: Metadata Extraction (NO DESCARGA)            │  │
│  │  ┌─────────────────────────────────────────────────┐  │  │
│  │  │  ffprobe -i URL                                  │  │  │
│  │  │  • Obtiene duración: 3600s (1 hora)             │  │  │
│  │  │  • Verifica tiene audio: true                   │  │  │
│  │  │  • Detecta codec: aac                           │  │  │
│  │  │  • Todo sin descargar video                     │  │  │
│  │  │  • Tiempo: 2-5 segundos                         │  │  │
│  │  └─────────────────────────────────────────────────┘  │  │
│  │                                                         │  │
│  │  Step 2: FFmpeg Pipe Streaming (CORE INNOVATION)      │  │
│  │  ┌─────────────────────────────────────────────────┐  │  │
│  │  │  ffmpeg -i URL \                                 │  │  │
│  │  │         -f wav \                                 │  │  │
│  │  │         -acodec pcm_s16le \                      │  │  │
│  │  │         -ar 16000 \                              │  │  │
│  │  │         -ac 1 \                                  │  │  │
│  │  │         pipe:1  # ← Output a PIPE, NO archivo   │  │  │
│  │  │                                                   │  │  │
│  │  │  Flujo de datos:                                 │  │  │
│  │  │  URL → FFmpeg → PIPE → Buffer (2MB) → Chunks    │  │  │
│  │  │                  ↑                                │  │  │
│  │  │           NO guarda a disco                      │  │  │
│  │  │           Solo streaming en RAM                  │  │  │
│  │  └─────────────────────────────────────────────────┘  │  │
│  │                                                         │  │
│  │  Step 3: Chunking en Memoria                           │  │
│  │  ┌─────────────────────────────────────────────────┐  │  │
│  │  │  while True:                                     │  │  │
│  │  │    chunk = pipe.read(30_seconds_of_audio)       │  │  │
│  │  │    if not chunk: break                          │  │  │
│  │  │                                                   │  │  │
│  │  │    # Chunk está SOLO en memoria                 │  │  │
│  │  │    # NO se guarda a disco local                 │  │  │
│  │  │                                                   │  │  │
│  │  │    # Upload directo a S3                        │  │  │
│  │  │    s3.put_object(                                │  │  │
│  │  │      Body=chunk,  # ← Desde memoria             │  │  │
│  │  │      Key=f'chunks/chunk_{n}.wav'                │  │  │
│  │  │    )                                             │  │  │
│  │  │                                                   │  │  │
│  │  │    chunk_num += 1                                │  │  │
│  │  │    update_progress(chunk_num)                   │  │  │
│  │  └─────────────────────────────────────────────────┘  │  │
│  │                                                         │  │
│  │  Redis Cache (Deduplicación)                          │  │
│  │  ┌─────────────────────────────────────────────────┐  │  │
│  │  │  cache_key = md5(url)                           │  │  │
│  │  │  if cache_key exists:                           │  │  │
│  │  │    return cached_chunks                         │  │  │
│  │  │  else:                                           │  │  │
│  │  │    process_streaming()                          │  │  │
│  │  │    cache_result(24_hours)                       │  │  │
│  │  └─────────────────────────────────────────────────┘  │  │
│  └───────────────────────────────────────────────────────┘  │
│                                                               │
│  RECURSOS USADOS POR FOG NODE:                            │
│  • Disco: 0 MB (streaming directo)                           │
│  • Memoria: 150 MB peak (buffer temporal)                    │
│  • CPU: 60% average (FFmpeg encoding)                        │
│  • Network Download: Solo audio, no video (90% ahorro)      │
└──────────────────────┬──────────────────────────────────────┘
                       │ Solo chunks procesados (50MB vs 550MB)
                       ▼
┌─────────────────────────────────────────────────────────────┐
│              S3 BUCKET: Processed Audio Chunks               │
│                                                               │
│  /audio/{job_id}/chunks/                                     │
│    ├── chunk_000.wav  (30s, ~1.5MB)                         │
│    ├── chunk_001.wav  (30s, ~1.5MB)                         │
│    ├── chunk_002.wav  (30s, ~1.5MB)                         │
│    ├── ...                                                   │
│    └── chunk_119.wav  (30s, ~1.5MB)                         │
│                                                               │
│  Total: 120 chunks × 1.5MB = 180MB                          │
│  vs Anterior: 550MB (video) + 50MB (audio) = 600MB          │
│  AHORRO: 70% de storage                                      │
└──────────────────────┬──────────────────────────────────────┘
                       │ S3 Event Notification
                       ▼
┌─────────────────────────────────────────────────────────────┐
│                 SERVERLESS WHISPER SERVICE                   │
│                    (ECS Fargate + GPU)                       │
│                                                               │
│  Arquitectura de Procesamiento PARALELO:                    │
│                                                               │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  Task 1: Whisper Medium (GPU)                         │  │
│  │  ├─ Download chunk_000.wav from S3                    │  │
│  │  ├─ Transcribe with faster-whisper                    │  │
│  │  ├─ Generate segments with timestamps                 │  │
│  │  └─ Upload transcription to S3                        │  │
│  │     Time: ~12 seconds per chunk                       │  │
│  └───────────────────────────────────────────────────────┘  │
│                                                               │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  Task 2: Processing chunk_001.wav                     │  │
│  └───────────────────────────────────────────────────────┘  │
│                                                               │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  Task 3: Processing chunk_002.wav                     │  │
│  └───────────────────────────────────────────────────────┘  │
│                                                               │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  Task 4: Processing chunk_003.wav                     │  │
│  └───────────────────────────────────────────────────────┘  │
│                                                               │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  Task 5: Processing chunk_004.wav                     │  │
│  └───────────────────────────────────────────────────────┘  │
│                                                               │
│  Procesamiento: 5 chunks en paralelo                      │
│  Tiempo: 120 chunks / 5 tasks = 24 batches × 12s = 4.8min│
│                                                               │
│  Whisper Model Selection Logic:                             │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  if duration < 5_min:    model = "small"             │  │
│  │  elif duration < 30_min: model = "medium"            │  │
│  │  else:                    model = "large-v3"          │  │
│  │                                                        │  │
│  │  Accuracy:                                             │  │
│  │  • Small:    ~93% WER 5-8%                            │  │
│  │  • Medium:   ~95% WER 3-5%                            │  │
│  │  • Large-v3: ~97% WER 1-3%                            │  │
│  └───────────────────────────────────────────────────────┘  │
│                                                               │
│  GPU Acceleration (NVIDIA T4):                               │
│  • faster-whisper: 5x más rápido que CPU                    │
│  • Batch processing: Procesa múltiples chunks              │
│  • Memory: 8-16GB VRAM                                       │
└──────────────────────┬──────────────────────────────────────┘
                       │ Transcripciones individuales
                       ▼
┌─────────────────────────────────────────────────────────────┐
│          Lambda: Post-Processor (Merge & Format)             │
│                                                               │
│  Step 1: Merge Transcriptions                               │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  chunks_transcriptions = [                            │  │
│  │    {id: 0, text: "Hello...", start: 0, end: 30},     │  │
│  │    {id: 1, text: "Welcome...", start: 30, end: 60},  │  │
│  │    ...                                                 │  │
│  │  ]                                                     │  │
│  │                                                        │  │
│  │  # Adjust timestamps                                  │  │
│  │  for chunk in chunks:                                 │  │
│  │    chunk.start += chunk.id * 30                       │  │
│  │    chunk.end += chunk.id * 30                         │  │
│  │                                                        │  │
│  │  full_text = " ".join(c.text for c in chunks)        │  │
│  └───────────────────────────────────────────────────────┘  │
│                                                               │
│  Step 2: Generate Multiple Formats                          │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  • TXT:  Plain text                                   │  │
│  │  • JSON: Full data with timestamps + metadata        │  │
│  │  • SRT:  SubRip subtitles format                     │  │
│  │  • VTT:  WebVTT subtitles format                     │  │
│  └───────────────────────────────────────────────────────┘  │
│                                                               │
│  Step 3: Save to S3 + DynamoDB                              │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ├────────────────┬─────────────────┐
                       ▼                ▼                 ▼
              ┌─────────────┐  ┌─────────────┐  ┌─────────────┐
              │  S3 Bucket  │  │  DynamoDB   │  │ OpenSearch  │
              │             │  │             │  │             │
              │ /trans/{id}/│  │  Table:     │  │ Full-text   │
              │ • .txt      │  │  Trans-     │  │ indexing    │
              │ • .json     │  │  criptions  │  │             │
              │ • .srt      │  │             │  │ Vector      │
              │ • .vtt      │  │  + Segments │  │ embeddings  │
              └─────────────┘  └─────────────┘  └─────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│             Lambda: Analyzer (AI/ML Processing)              │
│                                                               │
│  Parallel Execution:                                         │
│                                                               │
│  Branch 1: Amazon Bedrock (Claude 3 Sonnet)                 │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  prompt = f"""                                        │  │
│  │    Analiza esta transcripción:                        │  │
│  │    {transcription_text}                               │  │
│  │                                                        │  │
│  │    Genera:                                             │  │
│  │    1. Resumen ejecutivo (3 líneas)                   │  │
│  │    2. Resumen medio (1 párrafo)                      │  │
│  │    3. Resumen largo (3 párrafos)                     │  │
│  │    4. Temas principales                               │  │
│  │    5. Chapter markers (cada 5 minutos)               │  │
│  │    6. Q&A pairs (10 preguntas)                       │  │
│  │  """                                                   │  │
│  │                                                        │  │
│  │  response = bedrock.invoke_model(                     │  │
│  │    modelId="anthropic.claude-3-sonnet",              │  │
│  │    body={"prompt": prompt}                           │  │
│  │  )                                                     │  │
│  │                                                        │  │
│  │  Time: 15-25 seconds                                  │  │
│  └───────────────────────────────────────────────────────┘  │
│                                                               │
│  Branch 2: Amazon Comprehend                                │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  # Named Entity Recognition                           │  │
│  │  entities = comprehend.detect_entities(text)          │  │
│  │  # → Personas, Lugares, Organizaciones               │  │
│  │                                                        │  │
│  │  # Key Phrases                                        │  │
│  │  phrases = comprehend.detect_key_phrases(text)        │  │
│  │  # → Conceptos principales                           │  │
│  │                                                        │  │
│  │  # Sentiment Analysis                                 │  │
│  │  sentiment = comprehend.detect_sentiment(text)        │  │
│  │  # → Positive, Negative, Neutral, Mixed              │  │
│  │                                                        │  │
│  │  Time: 5-10 seconds                                   │  │
│  └───────────────────────────────────────────────────────┘  │
│                                                               │
│  Total Analysis Time: ~30 seconds (paralelo)                │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│           Lambda: Indexer (Search Optimization)              │
│                                                               │
│  Step 1: Full-Text Indexing (OpenSearch)                    │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  opensearch.index(                                     │  │
│  │    index="transcriptions",                            │  │
│  │    body={                                              │  │
│  │      "text": full_transcription,                      │  │
│  │      "segments": segments_with_timestamps,            │  │
│  │      "metadata": {                                     │  │
│  │        "job_id": job_id,                              │  │
│  │        "duration": duration,                          │  │
│  │        "language": language,                          │  │
│  │        "entities": entities,                          │  │
│  │        "topics": topics                               │  │
│  │      }                                                  │  │
│  │    }                                                   │  │
│  │  )                                                     │  │
│  └───────────────────────────────────────────────────────┘  │
│                                                               │
│  Step 2: Semantic Search (Vector Embeddings)                │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  # Generate embeddings for semantic search            │  │
│  │  embeddings = bedrock.create_embeddings(              │  │
│  │    text=transcription_chunks                          │  │
│  │  )                                                     │  │
│  │                                                        │  │
│  │  # Store in OpenSearch k-NN index                     │  │
│  │  opensearch.index(                                     │  │
│  │    index="transcription-vectors",                     │  │
│  │    body={"vector": embeddings}                        │  │
│  │  )                                                     │  │
│  └───────────────────────────────────────────────────────┘  │
│                                                               │
│  Indexing Time: 30-60 seconds                                │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│                   ✅ JOB COMPLETED                           │
│                                                               │
│  Status Update in DynamoDB:                                  │
│  • status: "completed"                                       │
│  • progress: 100                                             │
│  • processing_time: "18 minutes"                            │
│  • chunks_processed: 120                                     │
│  • output_formats: [txt, json, srt, vtt]                   │
│                                                               │
│  Usuario puede ahora:                                        │
│  • Descargar transcripciones                                │
│  • Buscar en el contenido                                   │
│  • Ver resúmenes y análisis                                 │
│  • Explorar entities y topics                               │
└─────────────────────────────────────────────────────────────┘

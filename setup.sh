#!/bin/bash

###############################################################################
# Script de Setup Inicial
# Crea toda la estructura del proyecto y archivos base
###############################################################################

set -e

echo "🚀 Iniciando setup del proyecto..."

# Colores
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

# Función para crear archivos
create_file() {
    local file=$1
    local content=$2

    mkdir -p "$(dirname "$file")"
    echo "$content" > "$file"
    echo -e "${GREEN}✓${NC} Creado: $file"
}

###############################################################################
# 1. TERRAFORM - Archivos Principales
###############################################################################

echo -e "\n${BLUE}[1/6]${NC} Creando archivos Terraform..."

# terraform/variables.tf
create_file "terraform/variables.tf" 'variable "aws_region" {
  description = "AWS Region"
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Project name"
  type        = string
  default     = "podcast-transcription"
}

variable "environment" {
  description = "Environment"
  type        = string
  default     = "production"
}

variable "fog_node_count" {
  description = "Number of fog nodes"
  type        = number
  default     = 3
}'

# terraform/terraform.tfvars
create_file "terraform/terraform.tfvars" '# Configuración del Proyecto
aws_region   = "us-east-1"
project_name = "podcast-transcription"
environment  = "production"

# Fog Computing
fog_node_count = 3

# Configuración (ajustar según necesidad)
# fog_node_count = 1  # Para desarrollo/testing
# fog_node_count = 3  # Para producción'

# terraform/backend.tf
create_file "terraform/backend.tf" 'terraform {
  backend "s3" {
    bucket = "REEMPLAZAR-CON-TU-BUCKET"
    key    = "terraform.tfstate"
    region = "us-east-1"

    # Descomentar después de crear el bucket
    # dynamodb_table = "terraform-state-lock"
  }
}'

###############################################################################
# 2. DOCKER - Archivos Base
###############################################################################

echo -e "\n${BLUE}[2/6]${NC} Creando archivos Docker..."

# Fog Node Dockerfile
create_file "docker/fog-node/Dockerfile" 'FROM python:3.11-slim

RUN apt-get update && apt-get install -y \\
    ffmpeg \\
    redis-tools \\
    curl \\
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/

ENV PYTHONUNBUFFERED=1

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=10s CMD curl -f http://localhost:8080/health || exit 1

CMD ["python", "-m", "src.main"]'

# Fog Node requirements.txt
create_file "docker/fog-node/requirements.txt" 'fastapi==0.104.1
uvicorn[standard]==0.24.0
boto3==1.29.7
redis==5.0.1
pydantic==2.5.0'

# Fog Node main.py (versión simplificada para empezar)
create_file "docker/fog-node/src/main.py" 'from fastapi import FastAPI
import os

app = FastAPI(title="Fog Node Service")

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "version": "3.0.0-streaming"
    }

@app.post("/process")
async def process_media(data: dict):
    return {
        "status": "processing",
        "message": "Streaming mode activated"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)'

# Whisper Service Dockerfile
create_file "docker/whisper-service/Dockerfile" 'FROM python:3.11-slim

RUN apt-get update && apt-get install -y \\
    ffmpeg \\
    curl \\
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/

ENV PYTHONUNBUFFERED=1

EXPOSE 8080

CMD ["python", "-m", "src.main"]'

# Whisper Service requirements.txt
create_file "docker/whisper-service/requirements.txt" 'fastapi==0.104.1
uvicorn[standard]==0.24.0
boto3==1.29.7
openai-whisper==20231117
torch==2.1.0
pydantic==2.5.0'

###############################################################################
# 3. LAMBDA - Funciones Base
###############################################################################

echo -e "\n${BLUE}[3/6]${NC} Creando Lambda functions..."

# URL Processor
create_file "lambda/url_processor/main.py" 'import json
import os
import boto3
import uuid
from datetime import datetime

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(os.getenv("JOBS_TABLE", "jobs"))

def handler(event, context):
    try:
        body = json.loads(event.get("body", "{}"))
        url = body.get("url")

        if not url:
            return {
                "statusCode": 400,
                "body": json.dumps({"error": "URL required"})
            }

        job_id = str(uuid.uuid4())

        # Crear job en DynamoDB
        table.put_item(Item={
            "jobId": job_id,
            "url": url,
            "status": "pending",
            "createdAt": int(datetime.utcnow().timestamp())
        })

        return {
            "statusCode": 200,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*"
            },
            "body": json.dumps({
                "jobId": job_id,
                "status": "pending",
                "message": "Job created successfully"
            })
        }

    except Exception as e:
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)})
        }'

create_file "lambda/url_processor/requirements.txt" 'boto3==1.29.7'

# Query Handler
create_file "lambda/query_handler/main.py" 'import json
import os
import boto3

dynamodb = boto3.resource("dynamodb")
jobs_table = dynamodb.Table(os.getenv("JOBS_TABLE", "jobs"))

def handler(event, context):
    try:
        job_id = event["pathParameters"]["jobId"]

        response = jobs_table.get_item(Key={"jobId": job_id})

        if "Item" not in response:
            return {
                "statusCode": 404,
                "body": json.dumps({"error": "Job not found"})
            }

        return {
            "statusCode": 200,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*"
            },
            "body": json.dumps(response["Item"], default=str)
        }

    except Exception as e:
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)})
        }'

create_file "lambda/query_handler/requirements.txt" 'boto3==1.29.7'

###############################################################################
# 4. FRONTEND - React App Base
###############################################################################

echo -e "\n${BLUE}[4/6]${NC} Creando frontend base..."

create_file "frontend/package.json" '{
  "name": "podcast-transcription-frontend",
  "version": "3.0.0",
  "private": true,
  "dependencies": {
    "react": "^18.2.0",
    "react-dom": "^18.2.0",
    "react-scripts": "5.0.1"
  },
  "scripts": {
    "start": "react-scripts start",
    "build": "react-scripts build",
    "test": "react-scripts test",
    "eject": "react-scripts eject"
  },
  "browserslist": {
    "production": [">0.2%", "not dead", "not op_mini all"],
    "development": ["last 1 chrome version", "last 1 firefox version", "last 1 safari version"]
  }
}'

create_file "frontend/public/index.html" '<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Podcast Transcription System</title>
  </head>
  <body>
    <noscript>You need to enable JavaScript to run this app.</noscript>
    <div id="root"></div>
  </body>
</html>'

create_file "frontend/src/index.js" 'import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";

const root = ReactDOM.createRoot(document.getElementById("root"));
root.render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);'

create_file "frontend/src/App.js" 'import React from "react";

function App() {
  return (
    <div style={{ padding: "2rem", fontFamily: "sans-serif" }}>
      <h1>🎙️ Podcast Transcription System</h1>
      <p>Versión 3.0 - Streaming Mode</p>
      <p>Frontend en construcción...</p>
    </div>
  );
}

export default App;'

###############################################################################
# 5. DOCUMENTACIÓN
###############################################################################

echo -e "\n${BLUE}[5/6]${NC} Creando documentación..."

create_file "README.md" '# 🎙️ Sistema de Transcripción de Podcasts/Videos

## Versión 3.0 - Streaming Mode

Sistema de transcripción usando Whisper AI en arquitectura Fog + Serverless.

## 🚀 Quick Start

```bash
# 1. Configurar AWS
aws configure

# 2. Personalizar variables
cp terraform/terraform.tfvars.example terraform/terraform.tfvars
# Editar terraform.tfvars

# 3. Desplegar
cd terraform
terraform init
terraform plan
terraform apply

# 4. Obtener URLs
terraform output
```

## 📚 Documentación Completa

Ver `/docs` para documentación detallada.

## 🎯 Características

- ✅ Streaming sin descarga completa
- ✅ Fog Computing + Serverless
- ✅ OpenAI Whisper AI
- ✅ Multi-formato output
- ✅ 100% Infrastructure as Code

## 📄 Licencia

MIT License'

create_file ".gitignore" '# Terraform
*.tfstate
*.tfstate.*
.terraform/
*.tfvars
!terraform.tfvars.example

# Python
__pycache__/
*.py[cod]
*.so
*.egg
*.egg-info/
dist/
build/
venv/
env/

# Node
node_modules/
npm-debug.log*
build/
.env.local

# IDE
.vscode/
.idea/
*.swp
*.swo

# OS
.DS_Store
Thumbs.db

# AWS
*.pem
.aws/

# Logs
*.log'

###############################################################################
# 6. SCRIPTS DE AYUDA
###############################################################################

echo -e "\n${BLUE}[6/6]${NC} Creando scripts de ayuda..."

create_file "scripts/build-docker.sh" '#!/bin/bash

echo "🐳 Building Docker images..."

cd docker/fog-node
docker build -t podcast-fog-node:latest .

cd ../whisper-service
docker build -t podcast-whisper:latest .

cd ../..

echo "✅ Docker images built successfully"'

chmod +x scripts/build-docker.sh

create_file "scripts/package-lambdas.sh" '#!/bin/bash

echo "📦 Packaging Lambda functions..."

mkdir -p lambda/dist

for func in url_processor query_handler; do
    echo "Packaging $func..."
    cd lambda/$func

    if [ -f requirements.txt ]; then
        pip install -r requirements.txt -t .
    fi

    zip -r ../dist/${func}.zip . -x "*.pyc" "*__pycache__*"
    cd ../..
done

echo "✅ Lambda functions packaged"'

chmod +x scripts/package-lambdas.sh

###############################################################################
# FINALIZAR
###############################################################################

echo -e "\n${GREEN}✅ Setup completado!${NC}"
echo ""
echo "📁 Estructura creada en: $(pwd)"
echo ""
echo "🎯 Próximos pasos:"
echo "1. Editar terraform/terraform.tfvars con tus valores"
echo "2. Ejecutar: cd terraform && terraform init"
echo "3. Ejecutar: terraform plan"
echo "4. Ejecutar: terraform apply"
echo ""
echo "📚 Documentación: README.md"

# 🎙️ Sistema de Transcripción de Podcasts/Videos

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

MIT License

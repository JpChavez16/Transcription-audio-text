terraform {
  required_version = ">= 1.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = var.project_name
      Environment = var.environment
      ManagedBy   = "Terraform"
    }
  }
}

# Data sources
data "aws_caller_identity" "current" {}
data "aws_availability_zones" "available" {
  state = "available"
}

# Local variables
locals {
  common_tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "Terraform"
  }
}

# Networking Module
module "networking" {
  source = "./modules/networking"

  project_name = var.project_name
  aws_region   = var.aws_region
  vpc_cidr     = "10.0.0.0/16"
  az_count     = 2
  tags         = local.common_tags
}

# Storage Module
module "storage" {
  source = "./modules/storage"

  project_name = var.project_name
  tags         = local.common_tags
}

# Fog Nodes Module (SIN Load Balancer)
module "fog_nodes" {
  source = "./modules/fog-nodes"

  project_name             = var.project_name
  aws_region               = var.aws_region
  vpc_id                   = module.networking.vpc_id
  private_subnet_ids       = module.networking.private_subnet_ids
  lambda_security_group_id = module.networking.lambda_security_group_id
  processed_bucket_name    = module.storage.s3_buckets.processed
  processed_bucket_arn     = module.storage.s3_bucket_arns.processed
  jobs_table_name          = module.storage.dynamodb_tables.jobs
  jobs_table_arn           = module.storage.dynamodb_table_arns.jobs
  fog_node_count           = var.fog_node_count
  tags                     = local.common_tags
}

# Lambda Module
module "lambda" {
  source = "./modules/lambda"

  project_name              = var.project_name
  jobs_table_name           = module.storage.dynamodb_tables.jobs
  jobs_table_arn            = module.storage.dynamodb_table_arns.jobs
  transcriptions_table_name = module.storage.dynamodb_tables.transcriptions
  transcriptions_table_arn  = module.storage.dynamodb_table_arns.transcriptions
  transcriptions_bucket_arn = module.storage.s3_bucket_arns.transcriptions
  fog_nodes_dns             = module.fog_nodes.service_discovery_dns
  ecs_cluster_name          = module.fog_nodes.cluster_name
  ecs_service_name          = module.fog_nodes.service_name
  private_subnet_ids        = module.networking.private_subnet_ids
  lambda_security_group_id  = module.networking.lambda_security_group_id

  whisper_service_dns  = module.whisper_service.service_discovery_dns
  processed_bucket_arn = module.storage.s3_bucket_arns.processed

  tags = local.common_tags
}

# Whisper Service Module
module "whisper_service" {
  source = "./modules/whisper-service"

  project_name = var.project_name
  aws_region   = var.aws_region
  tags         = local.common_tags

  ecs_cluster_id                 = module.fog_nodes.cluster_id
  service_discovery_namespace_id = module.fog_nodes.service_discovery_namespace_id
  private_subnet_ids             = module.networking.private_subnet_ids
  security_group_id              = module.networking.ecs_tasks_security_group_id # Use the ECS SG that allows incoming traffic

  processed_bucket_name      = module.storage.s3_buckets.processed
  processed_bucket_arn       = module.storage.s3_bucket_arns.processed
  transcriptions_bucket_name = module.storage.s3_buckets.transcriptions
  transcriptions_bucket_arn  = module.storage.s3_bucket_arns.transcriptions

  jobs_table_name           = module.storage.dynamodb_tables.jobs
  jobs_table_arn            = module.storage.dynamodb_table_arns.jobs
  transcriptions_table_name = module.storage.dynamodb_tables.transcriptions
  transcriptions_table_arn  = module.storage.dynamodb_table_arns.transcriptions
}

# S3 Notification (Root to avoid circular dependency)
resource "aws_s3_bucket_notification" "processed_audio_trigger" {
  bucket = module.storage.s3_buckets.processed

  lambda_function {
    lambda_function_arn = module.lambda.trigger_transcription_function_arn
    events              = ["s3:ObjectCreated:*"]
    filter_prefix       = "audio/"
    filter_suffix       = ".wav"
  }

  depends_on = [module.lambda] # Explicit dependency
}

# API Gateway Module
module "api_gateway" {
  source = "./modules/api-gateway"

  project_name                = var.project_name
  url_processor_function_name = module.lambda.url_processor_function_name
  url_processor_invoke_arn    = module.lambda.url_processor_invoke_arn
  query_handler_function_name = module.lambda.query_handler_function_name
  query_handler_invoke_arn    = module.lambda.query_handler_invoke_arn
  tags                        = local.common_tags
}

# Outputs
output "account_id" {
  description = "AWS Account ID"
  value       = data.aws_caller_identity.current.account_id
}

output "region" {
  description = "AWS Region"
  value       = var.aws_region
}

output "vpc_id" {
  description = "VPC ID"
  value       = module.networking.vpc_id
}

output "s3_buckets" {
  description = "S3 Bucket names"
  value       = module.storage.s3_buckets
}

output "dynamodb_tables" {
  description = "DynamoDB table names"
  value       = module.storage.dynamodb_tables
}

output "fog_nodes_dns" {
  description = "Fog Nodes Service Discovery DNS"
  value       = module.fog_nodes.service_discovery_dns
}

output "ecs_cluster_name" {
  description = "ECS Cluster Name"
  value       = module.fog_nodes.cluster_name
}

output "fog_node_ecr_url" {
  description = "ECR Repository URL for Fog Node"
  value       = module.fog_nodes.ecr_repository_url
}

output "whisper_service_ecr_url" {
  description = "ECR Repository URL for Whisper Service"
  value       = module.whisper_service.ecr_repository_url
}

output "api_gateway_url" {
  description = "API Gateway URL"
  value       = module.api_gateway.api_endpoint
}

output "web_bucket_name" {
  description = "Web bucket name"
  value       = module.storage.web_bucket_name
}

output "web_bucket_endpoint" {
  description = "Web bucket website endpoint"
  value       = module.storage.web_bucket_website_endpoint
}

output "deployment_summary" {
  description = "Deployment Summary"
  value       = <<-EOT
  
  ========================================
  🎉 DEPLOYMENT SUCCESSFUL!
  ========================================
  
  📡 API Gateway:
     ${module.api_gateway.api_endpoint}
  
  🌐 Frontend:
     http://${module.storage.web_bucket_website_endpoint}
  
  🔧 Fog Nodes:
     DNS: ${module.fog_nodes.service_discovery_dns}
     Cluster: ${module.fog_nodes.cluster_name}
  
  📦 ECR:
     ${module.fog_nodes.ecr_repository_url}
  
  ========================================
  📝 Next Steps:
  1. Push Docker image to ECR
  2. Update ECS service
  3. Deploy frontend
  ========================================
  
  EOT
}

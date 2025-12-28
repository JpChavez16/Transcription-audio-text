# modules/whisper-service/main.tf

# ECS Log Group
resource "aws_cloudwatch_log_group" "whisper_service" {
  name              = "/ecs/${var.project_name}/whisper-service"
  retention_in_days = 7
  
  tags = var.tags
}

# ECR Repository
resource "aws_ecr_repository" "whisper_service" {
  name                 = "${var.project_name}-whisper-service"
  image_tag_mutability = "MUTABLE"
  
  image_scanning_configuration {
    scan_on_push = true
  }
  
  tags = var.tags
}

# Service Discovery Service
resource "aws_service_discovery_service" "whisper_service" {
  name = "whisper-service"
  
  dns_config {
    namespace_id = var.service_discovery_namespace_id
    
    dns_records {
      ttl  = 10
      type = "A"
    }
    
    routing_policy = "MULTIVALUE"
  }
  
  health_check_custom_config {
    failure_threshold = 1
  }
  
  tags = var.tags
}

# IAM Role for ECS Task Execution
resource "aws_iam_role" "ecs_execution" {
  name = "${var.project_name}-whisper-ecs-execution-role"
  
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "ecs-tasks.amazonaws.com"
      }
    }]
  })
  
  tags = var.tags
}

resource "aws_iam_role_policy_attachment" "ecs_execution" {
  role       = aws_iam_role.ecs_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# IAM Role for ECS Task
resource "aws_iam_role" "ecs_task" {
  name = "${var.project_name}-whisper-ecs-task-role"
  
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "ecs-tasks.amazonaws.com"
      }
    }]
  })
  
  tags = var.tags
}

# S3 Access Policy
resource "aws_iam_role_policy" "ecs_task_s3" {
  name = "s3-access"
  role = aws_iam_role.ecs_task.id
  
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:ListBucket"
        ]
        Resource = [
          "${var.processed_bucket_arn}/*",
          var.processed_bucket_arn
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "s3:PutObject",
          "s3:GetObject",
          "s3:ListBucket"
        ]
        Resource = [
          "${var.transcriptions_bucket_arn}/*",
          var.transcriptions_bucket_arn
        ]
      }
    ]
  })
}

# DynamoDB Access Policy
resource "aws_iam_role_policy" "ecs_task_dynamodb" {
  name = "dynamodb-access"
  role = aws_iam_role.ecs_task.id
  
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "dynamodb:GetItem",
        "dynamodb:PutItem",
        "dynamodb:UpdateItem",
        "dynamodb:Query"
      ]
      Resource = [
        var.jobs_table_arn,
        var.transcriptions_table_arn
      ]
    }]
  })
}

# ECS Task Definition
resource "aws_ecs_task_definition" "whisper_service" {
  family                   = "${var.project_name}-whisper-service"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "2048" # Needs more CPU for Whisper
  memory                   = "4096" # Needs more RAM
  execution_role_arn       = aws_iam_role.ecs_execution.arn
  task_role_arn            = aws_iam_role.ecs_task.arn
  
  container_definitions = jsonencode([{
    name  = "whisper-service"
    image = "${aws_ecr_repository.whisper_service.repository_url}:latest"
    
    portMappings = [{
      containerPort = 8080
      protocol      = "tcp"
    }]
    
    environment = [
      {
        name  = "PROCESSED_AUDIO_BUCKET"
        value = var.processed_bucket_name
      },
      {
        name  = "TRANSCRIPTION_BUCKET"
        value = var.transcriptions_bucket_name
      },
      {
        name  = "JOBS_TABLE"
        value = var.jobs_table_name
      },
      {
        name  = "TRANSCRIPTIONS_TABLE"
        value = var.transcriptions_table_name
      },
      {
        name  = "WHISPER_MODEL"
        value = "small" # Start small for cost/speed
      },
      {
        name  = "AWS_DEFAULT_REGION"
        value = var.aws_region
      }
    ]
    
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.whisper_service.name
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "whisper-service"
      }
    }
    
    healthCheck = {
      command     = ["CMD-SHELL", "curl -f http://localhost:8080/health || exit 1"]
      interval    = 30
      timeout     = 5
      retries     = 3
      startPeriod = 60
    }
  }])
  
  tags = var.tags
}

# ECS Service
resource "aws_ecs_service" "whisper_service" {
  name            = "${var.project_name}-whisper-service"
  cluster         = var.ecs_cluster_id
  task_definition = aws_ecs_task_definition.whisper_service.arn
  desired_count   = var.service_count
  launch_type     = "FARGATE"
  
  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [var.security_group_id]
    assign_public_ip = false
  }
  
  service_registries {
    registry_arn = aws_service_discovery_service.whisper_service.arn
  }
  
  tags = var.tags
}

# Variables
variable "project_name" {}
variable "aws_region" {}
variable "tags" { type = map(string) }

variable "ecs_cluster_id" {}
variable "service_discovery_namespace_id" {}
variable "private_subnet_ids" { type = list(string) }
variable "security_group_id" {}

variable "processed_bucket_name" {}
variable "processed_bucket_arn" {}
variable "transcriptions_bucket_name" {}
variable "transcriptions_bucket_arn" {}

variable "jobs_table_name" {}
variable "jobs_table_arn" {}
variable "transcriptions_table_name" {}
variable "transcriptions_table_arn" {}

variable "service_count" {
  default = 1
}

# Outputs
output "service_name" {
  value = aws_ecs_service.whisper_service.name
}

output "service_discovery_dns" {
  value = "whisper-service.${var.project_name}.local"
}

output "ecr_repository_url" {
  value = aws_ecr_repository.whisper_service.repository_url
}

# modules/fog-nodes/main.tf - SIN LOAD BALANCER

# ECS Cluster
resource "aws_ecs_cluster" "main" {
  name = "${var.project_name}-fog-cluster"
  
  setting {
    name  = "containerInsights"
    value = "enabled"
  }
  
  tags = var.tags
}

# CloudWatch Log Group
resource "aws_cloudwatch_log_group" "fog_nodes" {
  name              = "/ecs/${var.project_name}/fog-nodes"
  retention_in_days = 7
  
  tags = var.tags
}

# ECR Repository
resource "aws_ecr_repository" "fog_node" {
  name                 = "${var.project_name}-fog-node"
  image_tag_mutability = "MUTABLE"
  
  image_scanning_configuration {
    scan_on_push = true
  }
  
  tags = var.tags
}

# Service Discovery Namespace
resource "aws_service_discovery_private_dns_namespace" "main" {
  name = "${var.project_name}.local"
  vpc  = var.vpc_id
  
  tags = var.tags
}

# Service Discovery Service
resource "aws_service_discovery_service" "fog_nodes" {
  name = "fog-nodes"
  
  dns_config {
    namespace_id = aws_service_discovery_private_dns_namespace.main.id
    
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
  name = "${var.project_name}-ecs-execution-role"
  
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
  name = "${var.project_name}-ecs-task-role"
  
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

resource "aws_iam_role_policy" "ecs_task_s3" {
  name = "s3-access"
  role = aws_iam_role.ecs_task.id
  
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "s3:GetObject",
        "s3:PutObject",
        "s3:DeleteObject",
        "s3:ListBucket"
      ]
      Resource = [
        "${var.processed_bucket_arn}/*",
        var.processed_bucket_arn
      ]
    }]
  })
}

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
        var.jobs_table_arn
      ]
    }]
  })
}

# Security Group for Fog Nodes (permite acceso desde Lambda)
resource "aws_security_group" "fog_nodes" {
  name_prefix = "${var.project_name}-fog-nodes-"
  description = "Security group for Fog Nodes"
  vpc_id      = var.vpc_id
  
  ingress {
    from_port       = 8080
    to_port         = 8080
    protocol        = "tcp"
    security_groups = [var.lambda_security_group_id]
    description     = "From Lambda"
  }
  
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
  
  tags = merge(var.tags, {
    Name = "${var.project_name}-fog-nodes-sg"
  })
}

# ECS Task Definition
resource "aws_ecs_task_definition" "fog_node" {
  family                   = "${var.project_name}-fog-node"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "1024"
  memory                   = "2048"
  execution_role_arn       = aws_iam_role.ecs_execution.arn
  task_role_arn            = aws_iam_role.ecs_task.arn
  
  container_definitions = jsonencode([{
    name  = "fog-node"
    image = "${aws_ecr_repository.fog_node.repository_url}:latest"
    
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
        name  = "JOBS_TABLE"
        value = var.jobs_table_name
      },
      {
        name  = "AWS_DEFAULT_REGION"
        value = var.aws_region
      }
    ]
    
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.fog_nodes.name
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "fog-node"
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

# ECS Service (SIN Load Balancer)
resource "aws_ecs_service" "fog_nodes" {
  name            = "${var.project_name}-fog-nodes"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.fog_node.arn
  desired_count   = var.fog_node_count
  launch_type     = "FARGATE"
  
  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [aws_security_group.fog_nodes.id]
    assign_public_ip = false
  }
  
  # Service Discovery en lugar de Load Balancer
  service_registries {
    registry_arn = aws_service_discovery_service.fog_nodes.arn
  }
  
  tags = var.tags
}

# Variables
variable "project_name" {
  type = string
}

variable "aws_region" {
  type = string
}

variable "vpc_id" {
  type = string
}

variable "private_subnet_ids" {
  type = list(string)
}

variable "lambda_security_group_id" {
  type = string
}

variable "processed_bucket_name" {
  type = string
}

variable "processed_bucket_arn" {
  type = string
}

variable "jobs_table_name" {
  type = string
}

variable "jobs_table_arn" {
  type = string
}

variable "fog_node_count" {
  type    = number
  default = 1
}

variable "tags" {
  type = map(string)
}

# Outputs
output "cluster_id" {
  value = aws_ecs_cluster.main.id
}

output "cluster_name" {
  value = aws_ecs_cluster.main.name
}

output "service_name" {
  value = aws_ecs_service.fog_nodes.name
}

output "service_discovery_dns" {
  value = "fog-nodes.${var.project_name}.local"
}

output "ecr_repository_url" {
  value = aws_ecr_repository.fog_node.repository_url
}

output "fog_nodes_security_group_id" {
  value = aws_security_group.fog_nodes.id
}
# modules/lambda/main.tf - CON VPC CONFIG

# IAM Role for Lambda
resource "aws_iam_role" "lambda" {
  name = "${var.project_name}-lambda-role"
  
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "lambda.amazonaws.com"
      }
    }]
  })
  
  tags = var.tags
}

resource "aws_iam_role_policy_attachment" "lambda_basic" {
  role       = aws_iam_role.lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# VPC Access (para comunicarse con ECS)
resource "aws_iam_role_policy_attachment" "lambda_vpc" {
  role       = aws_iam_role.lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}

resource "aws_iam_role_policy" "lambda_dynamodb" {
  name = "dynamodb-access"
  role = aws_iam_role.lambda.id
  
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "dynamodb:GetItem",
        "dynamodb:PutItem",
        "dynamodb:UpdateItem",
        "dynamodb:Query",
        "dynamodb:Scan"
      ]
      Resource = [
        var.jobs_table_arn,
        var.transcriptions_table_arn,
        "${var.jobs_table_arn}/index/*"
      ]
    }]
  })
}

resource "aws_iam_role_policy" "lambda_s3" {
  name = "s3-and-dynamodb-access"
  role = aws_iam_role.lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:ListBucket"
        ]
        Resource = [
          var.transcriptions_bucket_arn,
          "${var.transcriptions_bucket_arn}/*"
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "dynamodb:GetItem",
          "dynamodb:UpdateItem"
        ]
        Resource = [
          var.transcriptions_table_arn
        ]
      }
    ]
  })
}



resource "aws_iam_role_policy" "lambda_ecs" {
  name = "ecs-access"
  role = aws_iam_role.lambda.id
  
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "ecs:DescribeTasks",
        "ecs:ListTasks",
        "ecs:DescribeServices"
      ]
      Resource = "*"
    }]
  })
}

# URL Processor Lambda (CON VPC)
resource "aws_lambda_function" "url_processor" {
  filename         = "${path.module}/../../../lambda/dist/url_processor.zip"
  function_name    = "${var.project_name}-url-processor"
  role             = aws_iam_role.lambda.arn
  handler          = "main.handler"
  source_code_hash = filebase64sha256("${path.module}/../../../lambda/dist/url_processor.zip")
  runtime          = "python3.11"
  timeout          = 60
  memory_size      = 512
  
  environment {
    variables = {
      JOBS_TABLE           = var.jobs_table_name
      FOG_NODES_DNS        = var.fog_nodes_dns
      ECS_CLUSTER_NAME     = var.ecs_cluster_name
      ECS_SERVICE_NAME     = var.ecs_service_name
    }
  }
  
  # VPC Configuration
  vpc_config {
    subnet_ids         = var.private_subnet_ids
    security_group_ids = [var.lambda_security_group_id]
  }
  
  tags = var.tags
}

# Query Handler Lambda (SIN VPC - más rápido)
resource "aws_lambda_function" "query_handler" {
  filename         = "${path.module}/../../../lambda/dist/query_handler.zip"
  function_name    = "${var.project_name}-query-handler"
  role             = aws_iam_role.lambda.arn
  handler          = "main.handler"
  source_code_hash = filebase64sha256("${path.module}/../../../lambda/dist/query_handler.zip")
  runtime          = "python3.11"
  timeout          = 30
  memory_size      = 512
  
  environment {
    variables = {
      JOBS_TABLE           = var.jobs_table_name
      TRANSCRIPTIONS_TABLE = var.transcriptions_table_name
    }
  }
  
  tags = var.tags
}

# Trigger Transcription Lambda (CON VPC to access Whisper Service)
resource "aws_lambda_function" "trigger_transcription" {
  filename         = "${path.module}/../../../lambda/dist/trigger_transcription.zip"
  function_name    = "${var.project_name}-trigger-transcription"
  role             = aws_iam_role.lambda.arn
  handler          = "main.handler"
  source_code_hash = filebase64sha256("${path.module}/../../../lambda/dist/trigger_transcription.zip")
  runtime          = "python3.11"
  timeout          = 30
  memory_size      = 128
  
  environment {
    variables = {
      WHISPER_SERVICE_DNS = var.whisper_service_dns
    }
  }
  
  # VPC Config required to talk to ECS Fargate in private subnet associated with Service Discovery
  vpc_config {
    subnet_ids         = var.private_subnet_ids
    security_group_ids = [var.lambda_security_group_id]
  }
  
  tags = var.tags
}

resource "aws_lambda_permission" "allow_s3" {
  statement_id  = "AllowExecutionFromS3"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.trigger_transcription.function_name
  principal     = "s3.amazonaws.com"
  source_arn    = var.processed_bucket_arn
}

resource "aws_lambda_function" "post_processor" {
  filename         = "${path.module}/../../../lambda/dist/post_processor.zip"
  function_name    = "${var.project_name}-post-processor"
  role             = aws_iam_role.lambda.arn
  handler          = "main.handler"
  source_code_hash = filebase64sha256("${path.module}/../../../lambda/dist/post_processor.zip")
  runtime          = "python3.11"
  timeout          = 120
  memory_size      = 512

  environment {
    variables = {
      TRANSCRIPTIONS_BUCKET = var.transcriptions_bucket_name
      JOBS_TABLE           = var.jobs_table_name
      TRANSCRIPTIONS_TABLE = var.transcriptions_table_name
    }
  }

  tags = var.tags
}

resource "aws_lambda_permission" "allow_s3_post_processor" {
  statement_id  = "AllowExecutionFromS3PostProcessor"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.post_processor.function_name
  principal     = "s3.amazonaws.com"
  source_arn    = var.transcriptions_bucket_arn
}

resource "aws_s3_bucket_notification" "post_processor_trigger" {
  bucket = var.transcriptions_bucket_name

  lambda_function {
    lambda_function_arn = aws_lambda_function.post_processor.arn
    events              = ["s3:ObjectCreated:*"]
    filter_prefix       = "transcriptions/"
    filter_suffix       = ".json"
  }

  depends_on = [
    aws_lambda_permission.allow_s3_post_processor
  ]
}





# Variables
variable "project_name" {
  type = string
}

variable "jobs_table_name" {
  type = string
}

variable "jobs_table_arn" {
  type = string
}

variable "transcriptions_table_name" {
  type = string
}

variable "transcriptions_table_arn" {
  type = string
}

variable "transcriptions_bucket_arn" {
  type = string
}

variable "processed_bucket_arn" {
  type = string
}



variable "whisper_service_dns" {
  type = string
}

variable "fog_nodes_dns" {
  type = string
}

variable "ecs_cluster_name" {
  type = string
}

variable "ecs_service_name" {
  type = string
}

variable "private_subnet_ids" {
  type = list(string)
}

variable "lambda_security_group_id" {
  type = string
}

variable "tags" {
  type = map(string)
}

variable "transcriptions_bucket_name" {
  type = string
}


# Outputs
output "url_processor_function_name" {
  value = aws_lambda_function.url_processor.function_name
}

output "url_processor_arn" {
  value = aws_lambda_function.url_processor.arn
}

output "url_processor_invoke_arn" {
  value = aws_lambda_function.url_processor.invoke_arn
}

output "query_handler_function_name" {
  value = aws_lambda_function.query_handler.function_name
}

output "query_handler_arn" {
  value = aws_lambda_function.query_handler.arn
}

output "query_handler_invoke_arn" {
  value = aws_lambda_function.query_handler.invoke_arn
}

output "trigger_transcription_function_arn" {
  value = aws_lambda_function.trigger_transcription.arn
}

output "post_processor_function_name" {
  value = aws_lambda_function.post_processor.function_name
}

output "post_processor_arn" {
  value = aws_lambda_function.post_processor.arn
}

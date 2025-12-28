# modules/storage/main.tf

# S3 Bucket for Raw Media
resource "aws_s3_bucket" "raw_media" {
  bucket = "${var.project_name}-raw-${data.aws_caller_identity.current.account_id}"
  
  tags = merge(var.tags, {
    Name = "Raw Media Storage"
  })
}

resource "aws_s3_bucket_versioning" "raw_media" {
  bucket = aws_s3_bucket.raw_media.id
  
  versioning_configuration {
    status = "Enabled"
  }
}

# S3 Bucket for Processed Audio
resource "aws_s3_bucket" "processed" {
  bucket = "${var.project_name}-processed-${data.aws_caller_identity.current.account_id}"
  
  tags = merge(var.tags, {
    Name = "Processed Audio Storage"
  })
}

# S3 Bucket for Transcriptions
resource "aws_s3_bucket" "transcriptions" {
  bucket = "${var.project_name}-transcriptions-${data.aws_caller_identity.current.account_id}"
  
  tags = merge(var.tags, {
    Name = "Transcriptions Storage"
  })
}

resource "aws_s3_bucket_versioning" "transcriptions" {
  bucket = aws_s3_bucket.transcriptions.id
  
  versioning_configuration {
    status = "Enabled"
  }
}

# S3 Bucket for Web App
resource "aws_s3_bucket" "web_app" {
  bucket = "${var.project_name}-web-${data.aws_caller_identity.current.account_id}"
  
  tags = merge(var.tags, {
    Name = "Web Application"
  })
}

resource "aws_s3_bucket_website_configuration" "web_app" {
  bucket = aws_s3_bucket.web_app.id
  
  index_document {
    suffix = "index.html"
  }
  
  error_document {
    key = "error.html"
  }
}

resource "aws_s3_bucket_public_access_block" "web_app" {
  bucket = aws_s3_bucket.web_app.id
  
  block_public_acls       = false
  block_public_policy     = false
  ignore_public_acls      = false
  restrict_public_buckets = false
}

resource "aws_s3_bucket_policy" "web_app" {
  bucket = aws_s3_bucket.web_app.id
  
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "PublicReadGetObject"
        Effect    = "Allow"
        Principal = "*"
        Action    = "s3:GetObject"
        Resource  = "${aws_s3_bucket.web_app.arn}/*"
      }
    ]
  })
}

# DynamoDB Table for Jobs
resource "aws_dynamodb_table" "jobs" {
  name           = "${var.project_name}-jobs"
  billing_mode   = "PAY_PER_REQUEST"
  hash_key       = "jobId"
  
  attribute {
    name = "jobId"
    type = "S"
  }
  
  attribute {
    name = "status"
    type = "S"
  }
  
  attribute {
    name = "createdAt"
    type = "N"
  }
  
  global_secondary_index {
    name            = "StatusIndex"
    hash_key        = "status"
    range_key       = "createdAt"
    projection_type = "ALL"
  }
  
  ttl {
    attribute_name = "ttl"
    enabled        = true
  }
  
  point_in_time_recovery {
    enabled = true
  }
  
  tags = merge(var.tags, {
    Name = "Jobs Table"
  })
}

# DynamoDB Table for Transcriptions
resource "aws_dynamodb_table" "transcriptions" {
  name           = "${var.project_name}-transcriptions"
  billing_mode   = "PAY_PER_REQUEST"
  hash_key       = "transcriptionId"
  
  attribute {
    name = "transcriptionId"
    type = "S"
  }
  
  attribute {
    name = "jobId"
    type = "S"
  }
  
  global_secondary_index {
    name            = "JobIndex"
    hash_key        = "jobId"
    projection_type = "ALL"
  }
  
  ttl {
    attribute_name = "ttl"
    enabled        = true
  }
  
  tags = merge(var.tags, {
    Name = "Transcriptions Table"
  })
}

data "aws_caller_identity" "current" {}

# Variables
variable "project_name" {
  type = string
}

variable "tags" {
  type = map(string)
}

# Outputs
output "s3_buckets" {
  value = {
    raw_media      = aws_s3_bucket.raw_media.id
    processed      = aws_s3_bucket.processed.id
    transcriptions = aws_s3_bucket.transcriptions.id
    web_app        = aws_s3_bucket.web_app.id
  }
}

output "s3_bucket_arns" {
  value = {
    raw_media      = aws_s3_bucket.raw_media.arn
    processed      = aws_s3_bucket.processed.arn
    transcriptions = aws_s3_bucket.transcriptions.arn
    web_app        = aws_s3_bucket.web_app.arn
  }
}

output "dynamodb_tables" {
  value = {
    jobs           = aws_dynamodb_table.jobs.name
    transcriptions = aws_dynamodb_table.transcriptions.name
  }
}

output "dynamodb_table_arns" {
  value = {
    jobs           = aws_dynamodb_table.jobs.arn
    transcriptions = aws_dynamodb_table.transcriptions.arn
  }
}

output "web_bucket_name" {
  value = aws_s3_bucket.web_app.id
}

output "web_bucket_website_endpoint" {
  value = aws_s3_bucket_website_configuration.web_app.website_endpoint
}
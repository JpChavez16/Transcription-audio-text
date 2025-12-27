variable "aws_region" {
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
}

# variables.tf
# =============
# These are the configurable parameters for the infrastructure.
# Override them with a terraform.tfvars file or -var flags.

variable "project_name" {
  description = "Project name used as prefix for all resources"
  type        = string
  default     = "stockpulse"
}

variable "aws_region" {
  description = "AWS region to deploy into"
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Environment name (dev, staging, prod)"
  type        = string
  default     = "dev"
}

variable "redshift_admin_user" {
  description = "Admin username for Redshift Serverless"
  type        = string
  default     = "admin"
}

variable "redshift_admin_password" {
  description = "Admin password for Redshift Serverless (min 8 chars, must include uppercase, lowercase, and number)"
  type        = string
  sensitive   = true  # Won't be shown in plan output
}

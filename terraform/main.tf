# ============================================================================
# StockPulse — Terraform Infrastructure
# ============================================================================
# This file defines ALL the AWS resources needed for the pipeline.
# Run 'terraform apply' to create everything at once.
#
# WHAT IS TERRAFORM?
#   Instead of clicking through the AWS Console to create resources,
#   you define them in code. Benefits:
#   - Reproducible: anyone can recreate the same environment
#   - Version controlled: infrastructure changes are tracked in Git
#   - Destroyable: 'terraform destroy' cleans up everything
#
# HOW TO USE:
#   cd terraform
#   terraform init      # Download AWS provider
#   terraform plan      # Preview changes
#   terraform apply     # Create resources
#   terraform destroy   # Tear everything down when done
# ============================================================================

terraform {
  required_version = ">= 1.5.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

# Get the current AWS account ID (used in resource naming)
data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

locals {
  account_id  = data.aws_caller_identity.current.account_id
  bucket_name = "${var.project_name}-data-${local.account_id}"
  mwaa_bucket = "${var.project_name}-mwaa-${local.account_id}"
}


# ============================================================================
# S3 — Data Lake
# ============================================================================
# This bucket holds ALL pipeline data:
#   bronze/  — raw JSON from Alpha Vantage
#   silver/  — cleaned Parquet from Glue
#   athena-results/ — Athena query output

resource "aws_s3_bucket" "data_lake" {
  bucket = local.bucket_name

  tags = {
    Project     = var.project_name
    Environment = var.environment
  }
}

resource "aws_s3_bucket_versioning" "data_lake" {
  bucket = aws_s3_bucket.data_lake.id
  versioning_configuration {
    status = "Enabled"  # Protects against accidental deletion
  }
}

# Block all public access (security best practice)
resource "aws_s3_bucket_public_access_block" "data_lake" {
  bucket = aws_s3_bucket.data_lake.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}


# ============================================================================
# IAM — Lambda Execution Role
# ============================================================================
# Lambda needs permissions to: read Secrets Manager, write to S3

resource "aws_iam_role" "lambda_role" {
  name = "${var.project_name}-lambda-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy" "lambda_policy" {
  name = "${var.project_name}-lambda-policy"
  role = aws_iam_role.lambda_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = ["s3:PutObject", "s3:GetObject"]
        Resource = "${aws_s3_bucket.data_lake.arn}/*"
      },
      {
        Effect = "Allow"
        Action = ["secretsmanager:GetSecretValue"]
        Resource = "arn:aws:secretsmanager:${var.aws_region}:${local.account_id}:secret:${var.project_name}/*"
      },
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "arn:aws:logs:*:*:*"
      }
    ]
  })
}


# ============================================================================
# Lambda — Ingestion Function
# ============================================================================

# Package the Lambda code into a zip file
data "archive_file" "lambda_zip" {
  type        = "zip"
  source_dir  = "${path.module}/../lambda"
  output_path = "${path.module}/lambda_package.zip"
}

resource "aws_lambda_function" "ingest" {
  function_name = "${var.project_name}-ingest"
  role          = aws_iam_role.lambda_role.arn
  handler       = "ingest_stock_data.lambda_handler"
  runtime       = "python3.11"

  filename         = data.archive_file.lambda_zip.output_path
  source_code_hash = data.archive_file.lambda_zip.output_base64sha256

  timeout     = 300  # 5 minutes (10 tickers × 15s rate limit = ~150s)
  memory_size = 256

  environment {
    variables = {
      S3_BUCKET = aws_s3_bucket.data_lake.id
      TICKERS   = "AAPL,MSFT,GOOGL,JPM,BAC,JNJ,UNH,XOM,CVX,PG"
    }
  }

  tags = {
    Project = var.project_name
  }
}


# ============================================================================
# EventBridge — Daily Schedule
# ============================================================================
# Triggers Lambda every weekday at 10:30 PM UTC (6:30 PM ET)

resource "aws_cloudwatch_event_rule" "daily_trigger" {
  name                = "${var.project_name}-daily-trigger"
  description         = "Trigger stock data ingestion daily after market close"
  schedule_expression = "cron(30 22 ? * MON-FRI *)"

  tags = {
    Project = var.project_name
  }
}

resource "aws_cloudwatch_event_target" "lambda_target" {
  rule = aws_cloudwatch_event_rule.daily_trigger.name
  arn  = aws_lambda_function.ingest.arn
}

resource "aws_lambda_permission" "allow_eventbridge" {
  statement_id  = "AllowEventBridgeInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.ingest.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.daily_trigger.arn
}


# ============================================================================
# IAM — Glue Role
# ============================================================================

resource "aws_iam_role" "glue_role" {
  name = "${var.project_name}-glue-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = { Service = "glue.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "glue_service" {
  role       = aws_iam_role.glue_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSGlueServiceRole"
}

resource "aws_iam_role_policy" "glue_s3_policy" {
  name = "${var.project_name}-glue-s3-policy"
  role = aws_iam_role.glue_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["s3:GetObject", "s3:PutObject", "s3:ListBucket", "s3:DeleteObject"]
      Resource = [
        aws_s3_bucket.data_lake.arn,
        "${aws_s3_bucket.data_lake.arn}/*"
      ]
    }]
  })
}


# ============================================================================
# Glue — ETL Job (Bronze -> Silver)
# ============================================================================

# Upload Glue script to S3
resource "aws_s3_object" "glue_script" {
  bucket = aws_s3_bucket.data_lake.id
  key    = "scripts/glue/bronze_to_silver.py"
  source = "${path.module}/../glue_jobs/bronze_to_silver.py"
  etag   = filemd5("${path.module}/../glue_jobs/bronze_to_silver.py")
}

resource "aws_glue_job" "bronze_to_silver" {
  name     = "${var.project_name}-bronze-to-silver"
  role_arn = aws_iam_role.glue_role.arn

  command {
    name            = "glueetl"
    script_location = "s3://${aws_s3_bucket.data_lake.id}/scripts/glue/bronze_to_silver.py"
    python_version  = "3"
  }

  default_arguments = {
    "--job-language"               = "python"
    "--enable-continuous-cloudwatch-log" = "true"
    "--S3_BUCKET"                  = aws_s3_bucket.data_lake.id
  }

  # 2 DPUs is the minimum — keeps costs low (~$0.44/hour × 2 DPU)
  number_of_workers = 2
  worker_type       = "G.1X"
  glue_version      = "4.0"
  timeout           = 30  # minutes

  tags = {
    Project = var.project_name
  }
}


# ============================================================================
# Glue Data Catalog — Database
# ============================================================================
# The catalog acts as a schema registry. Athena uses it to know
# what columns exist in the S3 Parquet files.

resource "aws_glue_catalog_database" "stockpulse" {
  name = "${var.project_name}_catalog"

  description = "StockPulse data catalog for Athena queries"
}


# ============================================================================
# Redshift Serverless
# ============================================================================

resource "aws_redshiftserverless_namespace" "stockpulse" {
  namespace_name      = "${var.project_name}-namespace"
  db_name             = "stockpulse"
  admin_username      = var.redshift_admin_user
  admin_user_password = var.redshift_admin_password

  iam_roles = [aws_iam_role.redshift_role.arn]

  tags = {
    Project = var.project_name
  }
}

resource "aws_redshiftserverless_workgroup" "stockpulse" {
  namespace_name = aws_redshiftserverless_namespace.stockpulse.namespace_name
  workgroup_name = "${var.project_name}-workgroup"

  # Base capacity: 8 RPUs is the minimum (cheapest option)
  base_capacity = 8

  tags = {
    Project = var.project_name
  }
}

# IAM role for Redshift to read S3
resource "aws_iam_role" "redshift_role" {
  name = "${var.project_name}-redshift-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = { Service = "redshift.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy" "redshift_s3_policy" {
  name = "${var.project_name}-redshift-s3-policy"
  role = aws_iam_role.redshift_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["s3:GetObject", "s3:ListBucket"]
      Resource = [
        aws_s3_bucket.data_lake.arn,
        "${aws_s3_bucket.data_lake.arn}/*"
      ]
    }]
  })
}

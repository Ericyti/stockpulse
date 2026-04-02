# ============================================================================
# StockPulse — Orchestration (Step Functions + EventBridge)
# ============================================================================

# Redshift Loader Lambda
data "archive_file" "loader_zip" {
  type        = "zip"
  source_file = "${path.module}/../lambda/redshift_loader.py"
  output_path = "${path.module}/loader_package.zip"
}

resource "aws_lambda_function" "redshift_loader" {
  function_name = "${var.project_name}-redshift-loader"
  role          = aws_iam_role.loader_lambda_role.arn
  handler       = "redshift_loader.lambda_handler"
  runtime       = "python3.11"

  filename         = data.archive_file.loader_zip.output_path
  source_code_hash = data.archive_file.loader_zip.output_base64sha256

  timeout     = 300
  memory_size = 256

  environment {
    variables = {
      REDSHIFT_WORKGROUP = aws_redshiftserverless_workgroup.stockpulse.workgroup_name
      REDSHIFT_DATABASE  = "stockpulse"
      S3_BUCKET          = aws_s3_bucket.data_lake.id
      REDSHIFT_ROLE_ARN  = aws_iam_role.redshift_role.arn
    }
  }

  tags = {
    Project = var.project_name
  }
}

resource "aws_iam_role" "loader_lambda_role" {
  name = "${var.project_name}-loader-lambda-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy" "loader_lambda_policy" {
  name = "${var.project_name}-loader-lambda-policy"
  role = aws_iam_role.loader_lambda_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = [
          "redshift-data:ExecuteStatement",
          "redshift-data:DescribeStatement",
          "redshift-data:GetStatementResult",
          "redshift-serverless:GetCredentials",
        ]
        Resource = "*"
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
# Step Functions State Machine
# ============================================================================

resource "aws_sfn_state_machine" "pipeline" {
  name     = "${var.project_name}-daily-pipeline"
  role_arn = aws_iam_role.step_functions_role.arn

  definition = templatefile("${path.module}/pipeline.json", {
    ingest_lambda_arn = aws_lambda_function.ingest.arn
    loader_lambda_arn = aws_lambda_function.redshift_loader.arn
    glue_job_name     = aws_glue_job.bronze_to_silver.name
    s3_bucket         = aws_s3_bucket.data_lake.id
  })

  tags = {
    Project = var.project_name
  }
}

resource "aws_iam_role" "step_functions_role" {
  name = "${var.project_name}-step-functions-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "states.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy" "step_functions_policy" {
  name = "${var.project_name}-step-functions-policy"
  role = aws_iam_role.step_functions_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = "lambda:InvokeFunction"
        Resource = [
          aws_lambda_function.ingest.arn,
          aws_lambda_function.redshift_loader.arn,
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "glue:StartJobRun",
          "glue:GetJobRun",
          "glue:GetJobRuns",
          "glue:BatchStopJobRun",
        ]
        Resource = "*"
      }
    ]
  })
}

# ============================================================================
# EventBridge → Step Functions (daily trigger)
# ============================================================================

resource "aws_cloudwatch_event_target" "step_functions_target" {
  rule = aws_cloudwatch_event_rule.daily_trigger.name
  arn  = aws_sfn_state_machine.pipeline.arn

  role_arn = aws_iam_role.eventbridge_sfn_role.arn

  input = jsonencode({
    processing_date = "2026-04-01"
  })
}

resource "aws_iam_role" "eventbridge_sfn_role" {
  name = "${var.project_name}-eventbridge-sfn-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "events.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy" "eventbridge_sfn_policy" {
  name = "${var.project_name}-eventbridge-sfn-policy"
  role = aws_iam_role.eventbridge_sfn_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "states:StartExecution"
      Resource = aws_sfn_state_machine.pipeline.arn
    }]
  })
}
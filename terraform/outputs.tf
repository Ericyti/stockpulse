# outputs.tf
# ===========
# After 'terraform apply', these values are printed to the console.
# Save them — you'll need them for dbt profiles, Airflow config, etc.

output "s3_bucket_name" {
  description = "S3 data lake bucket name"
  value       = aws_s3_bucket.data_lake.id
}

output "lambda_function_name" {
  description = "Lambda ingestion function name"
  value       = aws_lambda_function.ingest.function_name
}

output "glue_job_name" {
  description = "Glue ETL job name"
  value       = aws_glue_job.bronze_to_silver.name
}

output "redshift_workgroup_endpoint" {
  description = "Redshift Serverless endpoint (use this in dbt profiles.yml)"
  value       = aws_redshiftserverless_workgroup.stockpulse.endpoint
}

output "redshift_iam_role_arn" {
  description = "Redshift IAM role ARN (use in COPY commands)"
  value       = aws_iam_role.redshift_role.arn
}

output "glue_catalog_database" {
  description = "Glue Data Catalog database name (use in Athena)"
  value       = aws_glue_catalog_database.stockpulse.name
}

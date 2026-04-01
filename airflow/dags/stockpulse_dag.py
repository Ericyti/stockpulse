"""
StockPulse — Airflow DAG
==========================
Orchestrates the entire daily batch pipeline.

EXECUTION ORDER:
    1. Trigger Lambda (ingest stock data from Alpha Vantage)
    2. Wait for bronze data to land in S3
    3. Run Glue job (bronze -> silver: PySpark ETL)
    4. Load silver data into Redshift (COPY from S3)
    5. Run dbt (staging -> intermediate -> marts)
    6. Run dbt tests (data quality checks)
    7. Log completion

SCHEDULE:
    Daily at 10:30 PM UTC (6:30 PM ET) — weekdays only.
    US stock market closes at 4 PM ET. We wait 2.5 hours for
    Alpha Vantage to update their data.

DEPLOYMENT:
    Upload to MWAA S3 DAGs folder:
    aws s3 cp stockpulse_dag.py s3://stockpulse-mwaa-ACCOUNT_ID/dags/

HOW TO READ THIS DAG:
    Each "task" is one step in the pipeline. The >> operator defines
    dependencies: A >> B means "run B after A completes."
    TaskGroups visually group related tasks in the Airflow UI.
"""

from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.bash import BashOperator
from airflow.operators.python import PythonOperator
from airflow.providers.amazon.aws.operators.glue import GlueJobOperator
from airflow.providers.amazon.aws.operators.lambda_function import (
    LambdaInvokeFunctionOperator,
)
from airflow.providers.amazon.aws.sensors.s3 import S3KeySensor
from airflow.utils.task_group import TaskGroup

# ---------------------------------------------------------------------------
# Configuration — update these for your environment
# ---------------------------------------------------------------------------
S3_BUCKET = "stockpulse-data-YOUR_ACCOUNT_ID"
REDSHIFT_CONN_ID = "redshift_default"  # Set up in Airflow Connections UI
AWS_CONN_ID = "aws_default"

TICKERS = ["AAPL", "MSFT", "GOOGL", "JPM", "BAC", "JNJ", "UNH", "XOM", "CVX", "PG"]

# ---------------------------------------------------------------------------
# Default arguments (apply to all tasks)
# ---------------------------------------------------------------------------
default_args = {
    "owner": "data-engineering",
    "depends_on_past": False,
    "email_on_failure": True,
    "email": ["your-email@example.com"],
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
    "execution_timeout": timedelta(hours=1),
}


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------
def log_start(**context):
    execution_date = context["ds"]
    print(f"StockPulse pipeline starting for {execution_date}")


def log_complete(**context):
    execution_date = context["ds"]
    print(f"StockPulse pipeline complete for {execution_date}")


# ---------------------------------------------------------------------------
# DAG Definition
# ---------------------------------------------------------------------------
with DAG(
    dag_id="stockpulse_daily_pipeline",
    description="Daily batch pipeline: ingest -> transform -> model -> test",
    schedule_interval="30 22 * * 1-5",  # 6:30 PM ET = 22:30 UTC, Mon-Fri
    start_date=datetime(2025, 1, 1),
    catchup=False,          # Don't backfill historical dates
    max_active_runs=1,      # Only one pipeline run at a time
    tags=["stockpulse", "finance", "batch"],
    default_args=default_args,
) as dag:

    # ---- Step 1: Log start ----
    start = PythonOperator(
        task_id="log_pipeline_start",
        python_callable=log_start,
    )

    # ---- Step 2: Trigger Lambda ingestion ----
    ingest = LambdaInvokeFunctionOperator(
        task_id="invoke_lambda_ingestion",
        function_name="stockpulse-ingest",
        payload='{"tickers": ' + str(TICKERS).replace("'", '"') + '}',
        aws_conn_id=AWS_CONN_ID,
    )

    # ---- Step 3: Wait for data in S3 ----
    wait_for_data = S3KeySensor(
        task_id="wait_for_bronze_data",
        bucket_key=(
            "bronze/stocks/"
            "year={{ ds_nodash[:4] }}/"
            "month={{ ds_nodash[4:6] }}/"
            "day={{ ds_nodash[6:8] }}/"
            "AAPL_*.json"
        ),
        bucket_name=S3_BUCKET,
        aws_conn_id=AWS_CONN_ID,
        poke_interval=60,
        timeout=600,
    )

    # ---- Step 4: Glue ETL (bronze -> silver) ----
    glue_etl = GlueJobOperator(
        task_id="glue_bronze_to_silver",
        job_name="stockpulse-bronze-to-silver",
        script_args={
            "--S3_BUCKET": S3_BUCKET,
            "--PROCESSING_DATE": "{{ ds }}",
        },
        aws_conn_id=AWS_CONN_ID,
        wait_for_completion=True,
        num_of_dpus=2,
    )

    # ---- Step 5: Load silver into Redshift ----
    # Uses BashOperator to run a COPY command via psql or aws redshift-data
    load_to_redshift = BashOperator(
        task_id="load_silver_to_redshift",
        bash_command=f"""
            aws redshift-data execute-statement \
                --workgroup-name stockpulse-workgroup \
                --database stockpulse \
                --sql "
                    TRUNCATE TABLE raw.stock_prices;
                    COPY raw.stock_prices
                    FROM 's3://{S3_BUCKET}/silver/stocks/'
                    IAM_ROLE 'arn:aws:iam::YOUR_ACCOUNT_ID:role/stockpulse-redshift-role'
                    FORMAT AS PARQUET;
                "
        """,
    )

    # ---- Step 6: dbt transformations ----
    with TaskGroup(group_id="dbt_transforms") as dbt_group:

        dbt_seed = BashOperator(
            task_id="dbt_seed",
            bash_command="cd /usr/local/airflow/dbt/stockpulse_dbt && dbt seed --profiles-dir .",
        )

        dbt_run = BashOperator(
            task_id="dbt_run",
            bash_command="cd /usr/local/airflow/dbt/stockpulse_dbt && dbt run --profiles-dir .",
        )

        dbt_test = BashOperator(
            task_id="dbt_test",
            bash_command="cd /usr/local/airflow/dbt/stockpulse_dbt && dbt test --profiles-dir .",
        )

        dbt_seed >> dbt_run >> dbt_test

    # ---- Step 7: Log completion ----
    complete = PythonOperator(
        task_id="log_pipeline_complete",
        python_callable=log_complete,
    )

    # ---- Pipeline dependency chain ----
    # Read this left to right: each >> means "then run"
    start >> ingest >> wait_for_data >> glue_etl >> load_to_redshift >> dbt_group >> complete

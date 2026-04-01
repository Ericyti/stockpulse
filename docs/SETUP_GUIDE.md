# StockPulse — Setup Guide

This guide walks you through deploying the entire pipeline from scratch.
Each section corresponds to one layer of the architecture.

## Prerequisites

Before starting, make sure you have:

- **AWS Account** — sign up at https://aws.amazon.com (free tier eligible)
- **AWS CLI v2** — install from https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html
- **Terraform v1.5+** — install from https://developer.hashicorp.com/terraform/install
- **Python 3.9+** — for local testing
- **dbt-core + dbt-redshift** — `pip install dbt-core dbt-redshift`
- **Git** — for version control

---

## Step 1: Alpha Vantage API Key

Alpha Vantage provides free stock market data. The free tier allows 25 API
requests per day, which is enough for our 10 tickers.

1. Go to https://www.alphavantage.co/support/#api-key
2. Enter your email and get a free API key
3. Save the key — you'll need it in Step 3

**Test the API locally** (optional):

```bash
curl "https://www.alphavantage.co/query?function=TIME_SERIES_DAILY&symbol=AAPL&apikey=YOUR_KEY&outputsize=compact"
```

You should see a JSON response with AAPL price data.

---

## Step 2: Configure AWS CLI

```bash
# Configure your credentials
aws configure

# You'll be prompted for:
#   AWS Access Key ID:     (from IAM console)
#   AWS Secret Access Key: (from IAM console)
#   Default region:        us-east-1 (recommended)
#   Default output format: json

# Verify it works
aws sts get-caller-identity
```

If you don't have access keys yet, create them in the AWS Console under
IAM → Users → your user → Security credentials → Create access key.

---

## Step 3: Store API Key in AWS Secrets Manager

We store the Alpha Vantage key in Secrets Manager so Lambda can access
it securely (never hardcode API keys).

```bash
# Set your key as an environment variable
export ALPHA_VANTAGE_API_KEY="your_key_here"

# Run the setup script
bash scripts/setup_alpha_vantage.sh
```

Or manually:

```bash
aws secretsmanager create-secret \
  --name "stockpulse/alpha-vantage-api-key" \
  --secret-string '{"api_key":"YOUR_KEY_HERE"}' \
  --region us-east-1
```

---

## Step 4: Deploy Infrastructure with Terraform

Terraform creates all the AWS resources automatically.

```bash
cd terraform

# Initialize Terraform (downloads AWS provider)
terraform init

# Preview what will be created
terraform plan

# Deploy everything (type 'yes' when prompted)
terraform apply
```

**What gets created:**

- S3 bucket: `stockpulse-data-{account_id}`
- Lambda function: `stockpulse-ingest`
- Glue job: `stockpulse-bronze-to-silver`
- Glue database: `stockpulse_catalog`
- Redshift Serverless namespace + workgroup
- MWAA environment (Airflow)
- EventBridge rule (daily trigger)
- IAM roles with least-privilege policies

> **Note**: Terraform outputs will print the resource ARNs and endpoints
> you'll need for later steps. Save these.

---

## Step 5: Test the Lambda Ingestion

Before running the full pipeline, verify Lambda works:

```bash
# Invoke Lambda manually with 2 tickers (to test quickly)
aws lambda invoke \
  --function-name stockpulse-ingest \
  --payload '{"tickers": ["AAPL", "MSFT"]}' \
  --cli-binary-format raw-in-base64-out \
  response.json

# Check the response
cat response.json

# Verify files landed in S3
aws s3 ls s3://stockpulse-data-YOUR_ACCOUNT_ID/bronze/stocks/ --recursive
```

You should see JSON files partitioned by `year/month/day/`.

---

## Step 6: Run the Glue Job (Bronze → Silver)

The Glue job reads raw JSON from bronze, cleans it, and writes Parquet
to the silver layer.

```bash
# Start the Glue job
aws glue start-job-run \
  --job-name stockpulse-bronze-to-silver \
  --arguments '{
    "--S3_BUCKET": "stockpulse-data-YOUR_ACCOUNT_ID",
    "--PROCESSING_DATE": "2025-06-15"
  }'

# Check job status (takes ~3-5 minutes)
aws glue get-job-runs --job-name stockpulse-bronze-to-silver

# Verify Parquet files in silver layer
aws s3 ls s3://stockpulse-data-YOUR_ACCOUNT_ID/silver/stocks/ --recursive
```

---

## Step 7: Load Silver Data into Redshift

The silver Parquet files need to be loaded into Redshift so dbt can
transform them.

1. **Connect to Redshift** using the Query Editor v2 in the AWS Console
   (Redshift → Query editor v2)

2. **Run the schema setup** — copy and execute `redshift/setup_schemas.sql`

3. **Load data from S3**:

```sql
-- Load silver stock prices into raw schema
COPY raw.stock_prices
FROM 's3://stockpulse-data-YOUR_ACCOUNT_ID/silver/stocks/'
IAM_ROLE 'arn:aws:iam::YOUR_ACCOUNT_ID:role/stockpulse-redshift-role'
FORMAT AS PARQUET;

-- Verify
SELECT COUNT(*) FROM raw.stock_prices;
SELECT * FROM raw.stock_prices LIMIT 10;
```

---

## Step 8: Set Up and Run dbt

dbt transforms the raw data in Redshift into analytics-ready tables.

```bash
# Navigate to the dbt project
cd dbt/stockpulse_dbt

# Edit profiles.yml with your Redshift endpoint
# (Get the endpoint from Terraform outputs or Redshift console)

# Test the connection
dbt debug

# Load seed data (static ticker metadata)
dbt seed

# Run all models
dbt run

# Run data quality tests
dbt test

# Generate documentation
dbt docs generate
dbt docs serve  # Opens a browser with your data lineage graph
```

**What dbt creates in Redshift:**

- `analytics.stg_stock_prices` — cleaned staging model
- `analytics.int_stock_indicators` — daily returns, moving averages, volatility
- `analytics.fct_daily_trading` — fact table for dashboards
- `analytics.fct_sector_performance` — sector-level aggregations
- `analytics.dim_stocks` — stock dimension with metadata

---

## Step 9: Configure Airflow (MWAA)

MWAA needs the DAG file uploaded to its S3 bucket.

```bash
# Upload the DAG (MWAA bucket was created by Terraform)
aws s3 cp airflow/dags/stockpulse_dag.py \
  s3://stockpulse-mwaa-YOUR_ACCOUNT_ID/dags/

# Upload requirements for Airflow providers
echo "apache-airflow-providers-amazon>=8.0.0
dbt-core>=1.7.0
dbt-redshift>=1.7.0" > /tmp/requirements.txt

aws s3 cp /tmp/requirements.txt \
  s3://stockpulse-mwaa-YOUR_ACCOUNT_ID/requirements.txt
```

Then in the MWAA console, verify the DAG appears and trigger it manually
to test the full pipeline end-to-end.

---

## Step 10: Connect Power BI

1. Open Power BI Desktop
2. Get Data → Amazon Redshift
3. Enter your Redshift Serverless endpoint (from Terraform outputs)
4. Database: `stockpulse`
5. Select the `analytics` schema tables:
   - `fct_daily_trading`
   - `fct_sector_performance`
   - `dim_stocks`
6. Build your dashboards

**Suggested dashboards:**

- **Sector Heatmap**: Average daily returns by sector over time
- **Top Movers**: Stocks with highest daily return today
- **Moving Average Crossovers**: SMA20 vs SMA50 signals
- **Volatility Tracker**: 20-day rolling volatility by stock
- **Volume Analysis**: Relative volume spikes

---

## Step 11: Set Up GitHub CI/CD

Push the project to GitHub and enable the CI workflow:

```bash
# Initialize git repo
cd /path/to/stockpulse
git init
git add .
git commit -m "Initial commit: StockPulse pipeline"

# Create repo on GitHub, then:
git remote add origin https://github.com/yourusername/stockpulse.git
git branch -M main
git push -u origin main
```

The `.github/workflows/dbt_ci.yml` workflow will automatically lint and
test your dbt models on every pull request.

---

## Troubleshooting

**Lambda timeout**: Increase timeout to 300 seconds (5 min) in Terraform.
The rate limiter sleeps 15s between API calls, so 10 tickers = ~150s.

**Glue job fails**: Check CloudWatch Logs at `/aws-glue/jobs/output`.
Common issue: wrong S3 path or missing IAM permissions.

**dbt connection fails**: Verify the Redshift endpoint in `profiles.yml`
and ensure the security group allows inbound on port 5439.

**MWAA DAG not showing**: DAG files must be valid Python. Check the MWAA
logs in CloudWatch under `/aws/mwaa/environments/stockpulse/`.

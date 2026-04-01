# StockPulse — Stock Market Batch Analytics Pipeline

An end-to-end **batch** data engineering pipeline that ingests daily stock market data, processes it through a medallion architecture on AWS, models it with dbt, and serves analytics dashboards via Power BI.

## Architecture

```
                        ┌─────────────────────────────────┐
                        │     Amazon MWAA (Airflow)       │
                        │     Orchestrates daily batch     │
                        └──────────┬──────────────────────┘
                                   │ triggers
                        ┌──────────▼──────────┐
                        │   AWS Lambda         │
                        │   Batch pull from    │
                        │   Alpha Vantage API  │
                        └──────────┬──────────┘
                                   │ writes JSON
                     ┌─────────────▼─────────────────┐
                     │        Amazon S3 Data Lake     │
                     │  ┌──────────┐   ┌──────────┐  │
                     │  │  Bronze  │──▶│  Silver  │  │──── Amazon Athena
                     │  │ Raw JSON │   │ Parquet  │  │     (ad-hoc queries)
                     │  └──────────┘   └──────────┘  │
                     └─────────────┬─────────────────┘
                           AWS Glue│(PySpark batch ETL)
                                   │ COPY into
                     ┌─────────────▼─────────────────┐
                     │    Redshift Serverless         │
                     │  ┌──────────┐   ┌──────────┐  │
                     │  │ Staging  │──▶│  Marts   │  │──── Power BI
                     │  │ stg_     │   │ fct/dim  │  │     (dashboards)
                     │  └──────────┘   └──────────┘  │
                     │         dbt transforms         │
                     └────────────────────────────────┘
```

## Tech Stack

| Layer              | Tool                    | Role                                         |
|--------------------|-------------------------|----------------------------------------------|
| Data Source         | Alpha Vantage API       | Daily OHLCV stock prices (free tier)         |
| Ingestion          | AWS Lambda (Python)     | Batch pull, triggered on schedule            |
| Data Lake          | Amazon S3               | Bronze (raw JSON) + Silver (cleaned Parquet) |
| Batch ETL          | AWS Glue (PySpark)      | Flatten JSON, type-cast, write Parquet       |
| Data Catalog       | AWS Glue Data Catalog   | Schema registry for Athena + Glue            |
| Data Warehouse     | Redshift Serverless     | Hosts dbt models, serves BI queries          |
| Data Modeling      | dbt                     | SQL transforms: staging → marts              |
| Ad-hoc Queries     | Amazon Athena           | SQL directly on S3 (no Redshift needed)      |
| Orchestration      | Amazon MWAA (Airflow)   | Schedules the full daily batch pipeline      |
| Visualization      | Power BI                | Dashboards connected to Redshift             |
| Infrastructure     | Terraform               | Reproducible AWS deployment                  |

## Why This Stack?

**"Why Glue AND dbt?"** — They handle different problems:
- **Glue (PySpark)** is for the heavy lifting that SQL can't do well: flattening deeply nested JSON, handling schema drift, type-casting, and writing optimized Parquet files. It operates on the *data lake* layer (S3).
- **dbt** is for the business logic that SQL excels at: joins, aggregations, window functions, and building analytics-ready tables. It operates on the *warehouse* layer (Redshift).

**"Why batch, not streaming?"** — 95% of real-world data engineering is batch. Stock prices update once per day (at market close), so streaming would add complexity with zero benefit. The pipeline runs once daily at 6:30 PM ET.

**"Why Redshift Serverless?"** — Pay-per-query pricing (no idle cluster costs), native S3/Glue/Athena integration, and Redshift is the most common AWS warehouse on job postings.

## Project Structure

```
stockpulse/
├── README.md                           # You are here
├── lambda/
│   ├── ingest_stock_data.py            # Lambda: pulls from Alpha Vantage
│   └── requirements.txt
├── glue_jobs/
│   └── bronze_to_silver.py             # PySpark: raw JSON → clean Parquet
├── dbt/stockpulse_dbt/
│   ├── dbt_project.yml                 # dbt project config
│   ├── profiles.yml                    # Redshift connection
│   ├── models/
│   │   ├── staging/
│   │   │   ├── _staging__sources.yml   # Source definitions
│   │   │   └── stg_stock_prices.sql    # Clean + rename raw data
│   │   ├── intermediate/
│   │   │   └── int_stock_indicators.sql # Technical indicators
│   │   └── marts/
│   │       ├── fct_daily_trading.sql   # Fact table
│   │       ├── fct_sector_performance.sql
│   │       └── dim_stocks.sql          # Dimension table
│   ├── tests/                          # Data quality tests
│   ├── macros/                         # Reusable SQL snippets
│   └── seeds/
│       └── seed_stock_tickers.csv      # Static ticker metadata
├── airflow/dags/
│   └── stockpulse_dag.py              # Airflow DAG
├── redshift/
│   └── setup_schemas.sql              # Initial Redshift setup
├── athena/
│   └── sample_queries.sql             # Ad-hoc Athena queries
├── terraform/
│   ├── main.tf                        # Core infrastructure
│   ├── variables.tf                   # Configurable parameters
│   └── outputs.tf                     # Resource ARNs
├── scripts/
│   └── setup_alpha_vantage.sh         # Store API key in Secrets Manager
├── docs/
│   └── SETUP_GUIDE.md                 # Full deployment walkthrough
└── .github/workflows/
    └── dbt_ci.yml                     # CI: lint + test dbt models on PR
```

## Tickers Tracked

10 stocks across 5 sectors (fits Alpha Vantage free tier of 25 requests/day):

| Ticker | Company          | Sector           |
|--------|------------------|------------------|
| AAPL   | Apple            | Technology       |
| MSFT   | Microsoft        | Technology       |
| GOOGL  | Alphabet         | Technology       |
| JPM    | JPMorgan Chase   | Financials       |
| BAC    | Bank of America  | Financials       |
| JNJ    | Johnson & Johnson| Healthcare       |
| UNH    | UnitedHealth     | Healthcare       |
| XOM    | ExxonMobil       | Energy           |
| CVX    | Chevron          | Energy           |
| PG     | Procter & Gamble | Consumer Staples |

## Getting Started

See [`docs/SETUP_GUIDE.md`](docs/SETUP_GUIDE.md) for a complete step-by-step deployment walkthrough.

**Quick overview:**

1. Get a free Alpha Vantage API key
2. Configure AWS CLI credentials
3. Deploy infrastructure with Terraform
4. Run the pipeline manually to verify
5. Connect Power BI to Redshift

## Monthly Cost Estimate

| Service              | Estimated Cost          |
|----------------------|-------------------------|
| Lambda               | ~$0 (free tier)         |
| S3                   | ~$0.50                  |
| Glue                 | ~$2–5 (2 DPU, daily)   |
| Redshift Serverless  | ~$3–10 (pay-per-query)  |
| Athena               | ~$0.01 per query        |
| MWAA                 | ~$0.49/hr (smallest)    |
| **Total**            | **~$10–20/month**       |

> **Cost tip**: Pause MWAA when not in use, and use Redshift Serverless
> auto-pause to avoid idle charges.

## License

MIT

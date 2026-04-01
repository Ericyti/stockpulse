# StockPulse — Day 0: Complete Environment Setup

Everything you need to install, configure, and create before touching
the pipeline code. Follow these sections in order.

---

## Part 1: Accounts to create

You need three accounts. All have free tiers.

### 1.1 — GitHub account

If you don't already have one:

1. Go to https://github.com
2. Click "Sign up" and create an account
3. Choose the free plan (it's all you need)

### 1.2 — AWS account

This is where your entire pipeline runs.

1. Go to https://aws.amazon.com and click "Create an AWS Account"
2. Enter your email, set a password, and choose an account name
3. Choose "Personal" account type
4. Enter a credit/debit card (required, but free tier covers most usage)
5. Verify your phone number
6. Select the "Basic Support — Free" plan
7. Sign in to the AWS Console at https://console.aws.amazon.com

**Important**: AWS Free Tier gives you 12 months of free usage for many
services. Our pipeline is designed to stay within or near free tier limits.
Set up a billing alert so you don't get surprised:

- Go to AWS Console → Billing → Budgets → Create budget
- Choose "Zero spend budget" — this emails you if you spend anything
- Or choose "Monthly cost budget" and set $20 as your threshold

### 1.3 — Alpha Vantage account

This is our stock data source.

1. Go to https://www.alphavantage.co/support/#api-key
2. Enter your name and email
3. Click "Get Free API Key"
4. Copy and save your API key somewhere safe (you'll need it later)

The free tier gives you 25 API requests per day and 5 per minute.
Our pipeline uses 10 requests per day (one per ticker), so this is plenty.

---

## Part 2: Software to install on your computer

### 2.1 — VS Code

This is your code editor. Download from https://code.visualstudio.com

After installing, open VS Code and install these extensions (click the
Extensions icon in the left sidebar, or press Ctrl+Shift+X):

**Essential extensions:**

- **Python** (by Microsoft) — Python language support, linting, debugging
- **Pylance** (by Microsoft) — Python IntelliSense (auto-installs with Python)
- **HashiCorp Terraform** — Syntax highlighting for .tf files
- **dbt Power User** (by Innoverio) — dbt model navigation and autocomplete
- **SQL Formatter** — Format SQL files
- **GitLens** (by GitKraken) — See git blame, history, and changes inline
- **YAML** (by Red Hat) — Syntax support for YAML files (dbt configs, Airflow)

**Optional but nice to have:**

- **AWS Toolkit** — Browse AWS resources from VS Code
- **Thunder Client** — Test API calls without leaving VS Code
- **Material Icon Theme** — Better file icons

To install an extension, click the Extensions icon, search for the name,
and click "Install."

### 2.2 — Python 3.9+

Check if you already have it:

```bash
python3 --version
```

If not installed, or it's below 3.9:

- **Mac**: `brew install python@3.11` (install Homebrew first if needed: https://brew.sh)
- **Windows**: Download from https://www.python.org/downloads/
  - IMPORTANT: Check "Add Python to PATH" during installation
- **Linux**: `sudo apt update && sudo apt install python3.11 python3.11-venv python3-pip`

### 2.3 — Git

Check if installed:

```bash
git --version
```

If not:

- **Mac**: `xcode-select --install` (installs Git with Xcode command line tools)
- **Windows**: Download from https://git-scm.com/download/win
- **Linux**: `sudo apt install git`

Configure Git with your identity (use the same email as your GitHub account):

```bash
git config --global user.name "Your Name"
git config --global user.email "your.email@example.com"
```

### 2.4 — AWS CLI v2

This lets you interact with AWS from your terminal.

- **Mac**: `brew install awscli`
- **Windows**: Download the MSI installer from https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html
- **Linux**:
  ```bash
  curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"
  unzip awscliv2.zip
  sudo ./aws/install
  ```

Verify:

```bash
aws --version
# Should show: aws-cli/2.x.x ...
```

### 2.5 — Terraform

Infrastructure as code tool.

- **Mac**: `brew install terraform`
- **Windows**: Download from https://developer.hashicorp.com/terraform/install
  - Extract the .zip, put terraform.exe in a folder, add that folder to your PATH
- **Linux**:
  ```bash
  sudo apt-get update && sudo apt-get install -y gnupg software-properties-common
  wget -O- https://apt.releases.hashicorp.com/gpg | sudo gpg --dearmor -o /usr/share/keyrings/hashicorp-archive-keyring.gpg
  echo "deb [signed-by=/usr/share/keyrings/hashicorp-archive-keyring.gpg] https://apt.releases.hashicorp.com $(lsb_release -cs) main" | sudo tee /etc/apt/sources.list.d/hashicorp.list
  sudo apt update && sudo apt install terraform
  ```

Verify:

```bash
terraform --version
# Should show: Terraform v1.x.x
```

### 2.6 — dbt (data build tool)

Install dbt-core with the Redshift adapter:

```bash
pip install dbt-core dbt-redshift
```

Verify:

```bash
dbt --version
# Should show: dbt-core and dbt-redshift versions
```

---

## Part 3: Configure AWS

### 3.1 — Create an IAM user (don't use root)

Your AWS root account is like a master key — you should never use it for
day-to-day work. Create a dedicated IAM user instead.

1. Go to AWS Console → IAM (search for "IAM" in the top search bar)
2. Click "Users" in the left sidebar → "Create user"
3. Username: `stockpulse-dev` (or your name)
4. Check "Provide user access to the AWS Management Console" (optional)
5. Click "Next"
6. Select "Attach policies directly"
7. Search for and check these policies:
   - `AdministratorAccess` (for learning; in production you'd use least-privilege)
8. Click "Next" → "Create user"

### 3.2 — Create access keys for CLI

1. Click on your new user → "Security credentials" tab
2. Scroll to "Access keys" → "Create access key"
3. Select "Command Line Interface (CLI)"
4. Check the acknowledgment box → "Next" → "Create access key"
5. **COPY BOTH VALUES NOW** — you won't see the secret key again:
   - Access key ID (looks like: AKIAIOSFODNN7EXAMPLE)
   - Secret access key (looks like: wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY)

### 3.3 — Configure AWS CLI with your keys

```bash
aws configure
```

It will prompt you for four things:

```
AWS Access Key ID [None]: PASTE_YOUR_ACCESS_KEY_HERE
AWS Secret Access Key [None]: PASTE_YOUR_SECRET_KEY_HERE
Default region name [None]: us-east-1
Default output format [None]: json
```

Use `us-east-1` as the region — it has the most services available and
is cheapest for most things.

Verify it works:

```bash
aws sts get-caller-identity
```

You should see your account ID and user ARN. If you see an error,
double-check your access keys.

### 3.4 — Store your Alpha Vantage API key

```bash
aws secretsmanager create-secret \
  --name "stockpulse/alpha-vantage-api-key" \
  --secret-string '{"api_key":"PASTE_YOUR_ALPHA_VANTAGE_KEY_HERE"}' \
  --region us-east-1
```

This stores the key securely. Lambda retrieves it at runtime — you never
hardcode API keys in your code.

---

## Part 4: Set up your project in VS Code

### 4.1 — Create the GitHub repository

1. Go to https://github.com → click "+" → "New repository"
2. Repository name: `stockpulse`
3. Description: "End-to-end stock market batch analytics pipeline on AWS"
4. Select "Public" (so hiring managers can see it)
5. Check "Add a README file"
6. Add .gitignore: select "Python"
7. License: MIT
8. Click "Create repository"

### 4.2 — Clone to your computer and add the project files

```bash
# Navigate to where you keep projects
cd ~/projects  # or wherever you prefer

# Clone the repo
git clone https://github.com/YOUR_USERNAME/stockpulse.git
cd stockpulse
```

Now extract the project files you downloaded from Claude into this folder.
The structure should look like:

```
stockpulse/
├── .github/workflows/dbt_ci.yml
├── .gitignore
├── README.md
├── lambda/
├── glue_jobs/
├── dbt/
├── airflow/
├── redshift/
├── athena/
├── terraform/
├── scripts/
└── docs/
```

### 4.3 — Open in VS Code

```bash
code .
```

This opens VS Code in the project folder. You should see the full file
tree in the left sidebar.

### 4.4 — Create a Python virtual environment

A virtual environment keeps your project's Python packages isolated
from your system Python. Always use one.

```bash
# Create the virtual environment
python3 -m venv venv

# Activate it
# Mac/Linux:
source venv/bin/activate
# Windows:
venv\Scripts\activate

# Your terminal prompt should now start with (venv)

# Install project dependencies
pip install boto3 dbt-core dbt-redshift
```

In VS Code, select the Python interpreter from your venv:
1. Press Ctrl+Shift+P (Cmd+Shift+P on Mac)
2. Type "Python: Select Interpreter"
3. Choose the one in your `./venv/` folder

### 4.5 — Set up VS Code workspace settings

Create a `.vscode/settings.json` file in your project root:

```json
{
    "python.defaultInterpreterPath": "${workspaceFolder}/venv/bin/python",
    "python.analysis.typeCheckingMode": "basic",
    "editor.formatOnSave": true,
    "files.trimTrailingWhitespace": true,
    "files.associations": {
        "*.sql": "sql"
    },
    "[python]": {
        "editor.defaultFormatter": "ms-python.python"
    },
    "[sql]": {
        "editor.defaultFormatter": "ReneSaarsoo.sql-formatter-vsc"
    }
}
```

### 4.6 — Make your first commit

```bash
git add .
git commit -m "Initial commit: StockPulse pipeline scaffold"
git push origin main
```

Go check your GitHub repo — all your files should be there.

---

## Part 5: Verification checklist

Run through these checks to make sure everything is set up correctly.
Every single one should pass before you move on to deploying infrastructure.

```bash
# 1. Python
python3 --version
# Expected: Python 3.9+ ✓

# 2. Git
git --version
# Expected: git version 2.x.x ✓

# 3. AWS CLI
aws --version
# Expected: aws-cli/2.x.x ✓

# 4. AWS credentials
aws sts get-caller-identity
# Expected: Shows your account ID and user ARN ✓

# 5. Terraform
terraform --version
# Expected: Terraform v1.x.x ✓

# 6. dbt
dbt --version
# Expected: Shows dbt-core and dbt-redshift versions ✓

# 7. Alpha Vantage key stored
aws secretsmanager get-secret-value \
  --secret-id "stockpulse/alpha-vantage-api-key" \
  --query 'SecretString' --output text
# Expected: Shows {"api_key":"your_key"} ✓

# 8. Alpha Vantage API works
curl -s "https://www.alphavantage.co/query?function=TIME_SERIES_DAILY&symbol=AAPL&apikey=YOUR_KEY&outputsize=compact" | head -5
# Expected: Shows JSON with "Meta Data" ✓

# 9. Virtual environment active
which python
# Expected: Should point to your venv folder ✓

# 10. Project on GitHub
git remote -v
# Expected: Shows your GitHub repo URL ✓
```

---

## What's next?

Once everything above passes, you're ready for **Phase 2: Deploy Infrastructure**.
Go to `docs/SETUP_GUIDE.md` and start at Step 4 (Deploy with Terraform).

The order from here:

1. `terraform apply` — creates all AWS resources
2. Test Lambda — manually invoke, check S3 for JSON files
3. Test Glue — run the job, check S3 for Parquet files
4. Set up Redshift — run the SQL schema setup
5. Configure and run dbt — build your analytics models
6. Set up Airflow — orchestrate the daily batch
7. Connect Power BI — build dashboards

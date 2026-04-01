#!/bin/bash
# ============================================================================
# Store Alpha Vantage API key in AWS Secrets Manager
# ============================================================================
# Usage:
#   export ALPHA_VANTAGE_API_KEY="your_key_here"
#   bash scripts/setup_alpha_vantage.sh
# ============================================================================

set -euo pipefail

if [ -z "${ALPHA_VANTAGE_API_KEY:-}" ]; then
    echo "ERROR: ALPHA_VANTAGE_API_KEY environment variable is not set."
    echo ""
    echo "Usage:"
    echo "  export ALPHA_VANTAGE_API_KEY=\"your_key_here\""
    echo "  bash scripts/setup_alpha_vantage.sh"
    echo ""
    echo "Get a free key at: https://www.alphavantage.co/support/#api-key"
    exit 1
fi

SECRET_NAME="stockpulse/alpha-vantage-api-key"
REGION="${AWS_DEFAULT_REGION:-us-east-1}"

echo "Storing API key in Secrets Manager..."
echo "  Secret name: ${SECRET_NAME}"
echo "  Region:      ${REGION}"

# Try to create the secret, or update if it already exists
if aws secretsmanager describe-secret --secret-id "${SECRET_NAME}" --region "${REGION}" >/dev/null 2>&1; then
    echo "  Secret already exists — updating..."
    aws secretsmanager update-secret \
        --secret-id "${SECRET_NAME}" \
        --secret-string "{\"api_key\":\"${ALPHA_VANTAGE_API_KEY}\"}" \
        --region "${REGION}"
else
    echo "  Creating new secret..."
    aws secretsmanager create-secret \
        --name "${SECRET_NAME}" \
        --description "Alpha Vantage API key for StockPulse pipeline" \
        --secret-string "{\"api_key\":\"${ALPHA_VANTAGE_API_KEY}\"}" \
        --region "${REGION}"
fi

echo ""
echo "Done! API key stored securely."
echo "Lambda will retrieve it at runtime from Secrets Manager."

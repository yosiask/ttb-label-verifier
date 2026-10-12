#!/usr/bin/env bash
# Reproducible Azure deployment for the label verifier.
#
# Creates billable resources. Run only after the owner has approved the subscription,
# region, budget and model deployment. Nothing runs unless CONFIRM=yes is set.
#
#   SUBSCRIPTION_ID=... BUDGET_EMAIL=... CONFIRM=yes deploy/azure/deploy.sh
#
# Re-running is safe: every step is create-or-update.
set -euo pipefail

: "${SUBSCRIPTION_ID:?set SUBSCRIPTION_ID}"
: "${BUDGET_EMAIL:?set BUDGET_EMAIL (budget alert recipient)}"
LOCATION="${LOCATION:-eastus2}"
RG="${RG:-rg-ttb-label-verifier}"
SUFFIX="${SUFFIX:-$(echo -n "$SUBSCRIPTION_ID$RG" | sha256sum | cut -c1-6)}"
ACR="${ACR:-acrttblabel$SUFFIX}"
AOAI="${AOAI:-aoai-ttb-label-$SUFFIX}"
MODEL="${MODEL:-gpt-4.1-mini}"
MODEL_VERSION="${MODEL_VERSION:-2025-04-14}"
MODEL_SKU="${MODEL_SKU:-Standard}"            # regional pay-per-call; never provisioned throughput
MODEL_CAPACITY="${MODEL_CAPACITY:-100}"       # thousands of tokens per minute: a hard limit Azure enforces
DEPLOYMENT="${DEPLOYMENT:-label-vision}"
ENV_NAME="${ENV_NAME:-cae-ttb-label-verifier}"
APP="${APP:-ttb-label-verifier}"
MIN_REPLICAS="${MIN_REPLICAS:-0}"             # 1 during review week avoids cold starts (a few dollars)
MAX_REPLICAS="${MAX_REPLICAS:-3}"
CLOUD_DAILY_CAP="${CLOUD_DAILY_CAP:-1000}"    # per replica: worst case CLOUD_DAILY_CAP x MAX_REPLICAS calls/day
RATE_LIMIT_PER_MINUTE="${RATE_LIMIT_PER_MINUTE:-120}"
BUDGET_AMOUNT="${BUDGET_AMOUNT:-100}"         # alerts at 50% ($50) and 100% ($100)
IMAGE_TAG="${IMAGE_TAG:-$(git rev-parse --short HEAD)}"

if [[ "${CONFIRM:-}" != "yes" ]]; then
  echo "This creates billable Azure resources in subscription $SUBSCRIPTION_ID ($LOCATION). Set CONFIRM=yes to proceed." >&2
  exit 1
fi

cd "$(dirname "$0")/../.."
az account set --subscription "$SUBSCRIPTION_ID"

echo "== Resource providers"
for ns in Microsoft.App Microsoft.ContainerRegistry Microsoft.CognitiveServices; do
  az provider register --namespace "$ns" --wait
done

echo "== Resource group and budget (budget first, before anything that costs money)"
az group create -n "$RG" -l "$LOCATION" -o none
RG_ID=$(az group show -n "$RG" --query id -o tsv)
START=$(date -u +%Y-%m-01)
az rest --method put \
  --url "https://management.azure.com${RG_ID}/providers/Microsoft.Consumption/budgets/budget-ttb-label-verifier?api-version=2023-05-01" \
  --body @- -o none <<JSON
{
  "properties": {
    "category": "Cost",
    "amount": $BUDGET_AMOUNT,
    "timeGrain": "Monthly",
    "timePeriod": {"startDate": "${START}T00:00:00Z"},
    "notifications": {
      "actual50":  {"enabled": true, "operator": "GreaterThanOrEqualTo", "threshold": 50,  "contactEmails": ["$BUDGET_EMAIL"]},
      "actual100": {"enabled": true, "operator": "GreaterThanOrEqualTo", "threshold": 100, "contactEmails": ["$BUDGET_EMAIL"]},
      "forecast100": {"enabled": true, "operator": "GreaterThanOrEqualTo", "threshold": 100, "thresholdType": "Forecasted", "contactEmails": ["$BUDGET_EMAIL"]}
    }
  }
}
JSON

echo "== Container registry (Basic) and image build in Azure"
az acr create -g "$RG" -n "$ACR" --sku Basic --admin-enabled false -o none
az acr build -r "$ACR" -t "ttb-label-verifier:$IMAGE_TAG" .

echo "== Azure OpenAI resource (Entra ID auth only) and model deployment"
az cognitiveservices account create -g "$RG" -n "$AOAI" -l "$LOCATION" --kind OpenAI --sku S0 \
  --custom-domain "$AOAI" --yes -o none
az resource update -g "$RG" -n "$AOAI" --resource-type Microsoft.CognitiveServices/accounts \
  --set properties.disableLocalAuth=true -o none
az cognitiveservices account deployment create -g "$RG" -n "$AOAI" --deployment-name "$DEPLOYMENT" \
  --model-name "$MODEL" --model-version "$MODEL_VERSION" --model-format OpenAI \
  --sku-name "$MODEL_SKU" --sku-capacity "$MODEL_CAPACITY" -o none
AOAI_ENDPOINT=$(az cognitiveservices account show -g "$RG" -n "$AOAI" --query properties.endpoint -o tsv)
AOAI_ID=$(az cognitiveservices account show -g "$RG" -n "$AOAI" --query id -o tsv)

echo "== Container Apps environment (no log destination: the app keeps no request logs)"
az extension add --name containerapp --upgrade -y -o none
az containerapp env create -g "$RG" -n "$ENV_NAME" -l "$LOCATION" --logs-destination none -o none

echo "== Container app with managed identity"
az containerapp create -g "$RG" -n "$APP" --environment "$ENV_NAME" \
  --image "$ACR.azurecr.io/ttb-label-verifier:$IMAGE_TAG" \
  --registry-server "$ACR.azurecr.io" --registry-identity system \
  --system-assigned \
  --ingress external --target-port 8000 \
  --cpu 1 --memory 2Gi --min-replicas "$MIN_REPLICAS" --max-replicas "$MAX_REPLICAS" \
  --env-vars EXTRACTOR=auto AZURE_OPENAI_ENDPOINT="$AOAI_ENDPOINT" AZURE_OPENAI_DEPLOYMENT="$DEPLOYMENT" \
             MAX_UPLOAD_MB=10 CLOUD_DAILY_CAP="$CLOUD_DAILY_CAP" RATE_LIMIT_PER_MINUTE="$RATE_LIMIT_PER_MINUTE" \
             MAX_CONCURRENT_VERIFICATIONS=3 TRUSTED_PROXY_HOPS=1 AZURE_TIMEOUT_S=8 \
  -o none
PRINCIPAL=$(az containerapp show -g "$RG" -n "$APP" --query identity.principalId -o tsv)
az role assignment create --assignee-object-id "$PRINCIPAL" --assignee-principal-type ServicePrincipal \
  --role "Cognitive Services OpenAI User" --scope "$AOAI_ID" -o none

URL="https://$(az containerapp show -g "$RG" -n "$APP" --query properties.configuration.ingress.fqdn -o tsv)"
echo "== Deployed: $URL"
echo "Smoke test: curl -s $URL/api/health"

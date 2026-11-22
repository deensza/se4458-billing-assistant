#!/usr/bin/env bash
# Deploys the whole system to Azure:
#   Azure Container Registry  -> images (billing-api, mcp-server, gateway)
#   Azure Database for PostgreSQL Flexible Server (Burstable B1ms) -> server database
#   Azure Container Apps (Consumption):
#       billing-api  - ingress protected by a gateway shared secret: requests without the
#                      X-Gateway-Secret header that Kong adds are rejected (403 GATEWAY_REQUIRED)
#       gateway      - EXTERNAL ingress (Kong, public API base URL)
#       mcp-server   - EXTERNAL ingress (MCP endpoint for the agent)
#
# Prerequisites: az login; docker running. Usage:
#   ./infra/azure-deploy.sh
# Optional overrides: SUBSCRIPTION (id), LOCATION, RG, PREFIX (globally unique-ish, lowercase letters/digits).
# Note: "Azure for Students" subscriptions only allow some regions (e.g. germanywestcentral, spaincentral,
# switzerlandnorth, austriaeast, uaenorth) - check: az policy assignment list -o table
set -euo pipefail

STATE_FILE="$(dirname "$0")/.azure-deploy.env"
# Re-use names and secrets from a previous run (idempotent re-runs)
if [[ -f "$STATE_FILE" ]]; then source "$STATE_FILE"; fi

# Use the given subscription for this run only; restore the CLI default afterwards.
if [[ -n "${SUBSCRIPTION:-}" ]]; then
  PREVIOUS_SUBSCRIPTION=$(az account show --query id -o tsv)
  az account set --subscription "$SUBSCRIPTION"
  trap 'az account set --subscription "$PREVIOUS_SUBSCRIPTION"' EXIT
fi

LOCATION="${LOCATION:-germanywestcentral}"
RG="${RG:-se4458-billing-rg}"
# PostgreSQL may be restricted in some regions on student subscriptions (e.g. germanywestcentral)
PG_LOCATION="${PG_LOCATION:-spaincentral}"
PREFIX="${PREFIX:-se4458bill$RANDOM}"
ACR="${ACR:-${PREFIX}acr}"
PG="${PG:-${PREFIX}-pg}"
ENV_NAME="${ENV_NAME:-se4458-billing-env}"
TAG="${TAG:-$(date +%Y%m%d%H%M%S)}"   # new tag per run -> new revision
PG_ADMIN="billingadmin"
PG_PASSWORD="${PG_PASSWORD:-$(openssl rand -hex 16)Aa1!}"
JWT_SECRET="${JWT_SECRET:-$(openssl rand -hex 32)}"
GATEWAY_SECRET="${GATEWAY_SECRET:-$(openssl rand -hex 32)}"
cat > "$STATE_FILE" <<EOF
SUBSCRIPTION=${SUBSCRIPTION:-}
LOCATION=$LOCATION
PG_LOCATION=$PG_LOCATION
RG=$RG
PREFIX=$PREFIX
ACR=$ACR
PG=$PG
PG_PASSWORD='$PG_PASSWORD'
JWT_SECRET=$JWT_SECRET
GATEWAY_SECRET=$GATEWAY_SECRET
EOF
chmod 600 "$STATE_FILE"

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
echo ">> Resource group $RG ($LOCATION)"
az group create -n "$RG" -l "$LOCATION" -o none
az extension add --name containerapp --upgrade -o none 2>/dev/null || true
for ns in Microsoft.App Microsoft.OperationalInsights Microsoft.ContainerRegistry Microsoft.DBforPostgreSQL; do
  az provider register -n "$ns" --wait -o none
done

echo ">> Container registry $ACR"
az acr create -g "$RG" -n "$ACR" --sku Basic --admin-enabled true -o none
LOGIN_SERVER=$(az acr show -n "$ACR" --query loginServer -o tsv)
ACR_USER=$(az acr credential show -n "$ACR" --query username -o tsv)
ACR_PASS=$(az acr credential show -n "$ACR" --query 'passwords[0].value' -o tsv)
echo "$ACR_PASS" | docker login "$LOGIN_SERVER" -u "$ACR_USER" --password-stdin

for svc in billing_api:billing-api mcp_server:mcp-server gateway:gateway; do
  dir="${svc%%:*}"; img="${svc##*:}"
  echo ">> Build & push $img (linux/amd64)"
  docker buildx build --platform linux/amd64 -t "$LOGIN_SERVER/$img:$TAG" --push "$ROOT/$dir"
done

echo ">> PostgreSQL flexible server $PG ($PG_LOCATION, Burstable B1ms) - takes a few minutes"
if az postgres flexible-server show -g "$RG" -n "$PG" -o none 2>/dev/null; then
  echo "   (already exists)"
else
az postgres flexible-server create -g "$RG" -n "$PG" -l "$PG_LOCATION" \
  --tier Burstable --sku-name Standard_B1ms --storage-size 32 --version 16 \
  --admin-user "$PG_ADMIN" --admin-password "$PG_PASSWORD" \
  --public-access 0.0.0.0 --yes -o none
fi
az postgres flexible-server db create -g "$RG" --server-name "$PG" --name billing -o none
PG_HOST=$(az postgres flexible-server show -g "$RG" -n "$PG" --query fullyQualifiedDomainName -o tsv)
DATABASE_URL="postgresql+psycopg://$PG_ADMIN:$PG_PASSWORD@$PG_HOST:5432/billing?sslmode=require"

echo ">> Container Apps environment $ENV_NAME"
if ! az containerapp env show -g "$RG" -n "$ENV_NAME" -o none 2>/dev/null; then
  az containerapp env create -g "$RG" -n "$ENV_NAME" -l "$LOCATION" -o none
fi
ENV_DOMAIN=$(az containerapp env show -g "$RG" -n "$ENV_NAME" --query properties.defaultDomain -o tsv)

REG_ARGS=(--registry-server "$LOGIN_SERVER" --registry-username "$ACR_USER" --registry-password "$ACR_PASS")

# upsert_app NAME PORT CPU MEMORY "secret1=v1 secret2=v2" "ENV1=x ENV2=y"
upsert_app() {
  local name=$1 port=$2 cpu=$3 mem=$4 secrets=$5 envs=$6
  # shellcheck disable=SC2086
  if az containerapp show -g "$RG" -n "$name" -o none 2>/dev/null; then
    [[ -n "$secrets" ]] && az containerapp secret set -g "$RG" -n "$name" --secrets $secrets -o none
    az containerapp ingress enable -g "$RG" -n "$name" --type external --target-port "$port" -o none
    az containerapp update -g "$RG" -n "$name" --image "$LOGIN_SERVER/$name:$TAG" ${envs:+--set-env-vars $envs} -o none
  else
    az containerapp create -g "$RG" -n "$name" --environment "$ENV_NAME" \
      --image "$LOGIN_SERVER/$name:$TAG" "${REG_ARGS[@]}" \
      --ingress external --target-port "$port" --min-replicas 1 --max-replicas 1 --cpu "$cpu" --memory "$mem" \
      ${secrets:+--secrets $secrets} ${envs:+--env-vars $envs} -o none
  fi
}

echo ">> billing-api (only accepts requests forwarded by the gateway)"
upsert_app billing-api 8000 0.5 1.0Gi \
  "database-url=$DATABASE_URL jwt-secret=$JWT_SECRET gateway-secret=$GATEWAY_SECRET" \
  "DATABASE_URL=secretref:database-url JWT_SECRET=secretref:jwt-secret GATEWAY_SHARED_SECRET=secretref:gateway-secret SEED_DEMO_DATA=true"

echo ">> gateway (Kong, public API base URL)"
upsert_app gateway 8000 0.5 1.0Gi \
  "jwt-secret=$JWT_SECRET gateway-secret=$GATEWAY_SECRET" \
  "BILLING_API_URL=https://billing-api.$ENV_DOMAIN JWT_SECRET=secretref:jwt-secret GATEWAY_SECRET=secretref:gateway-secret"

echo ">> mcp-server (public MCP endpoint)"
upsert_app mcp-server 8001 0.25 0.5Gi "" ""

GATEWAY_FQDN=$(az containerapp show -g "$RG" -n gateway --query properties.configuration.ingress.fqdn -o tsv)
MCP_FQDN=$(az containerapp show -g "$RG" -n mcp-server --query properties.configuration.ingress.fqdn -o tsv)
echo
echo "================ DEPLOYED ================"
echo "GATEWAY_URL=https://$GATEWAY_FQDN"
echo "Swagger UI : https://$GATEWAY_FQDN/api/v1/docs"
echo "MCP_URL=https://$MCP_FQDN/mcp"
echo "PostgreSQL : $PG_HOST (database: billing)"
echo "Secrets saved (git-ignored) in $STATE_FILE"
echo "Delete everything afterwards: az group delete -n $RG --yes --no-wait"

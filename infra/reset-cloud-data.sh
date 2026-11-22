#!/usr/bin/env bash
# Resets the CLOUD database to the documented demo data (README §13): drops all tables, recreates them and
# re-seeds. Run it before recording the demo video and before submission.
#
#   ./infra/reset-cloud-data.sh
#
# It temporarily opens the PostgreSQL firewall for this machine's public IP only and removes the rule again.
set -euo pipefail
cd "$(dirname "$0")/.."
source infra/.azure-deploy.env
PG_ADMIN="billingadmin"
RULE="tmp-reset-data"

if [[ -n "${SUBSCRIPTION:-}" ]]; then
  PREVIOUS_SUBSCRIPTION=$(az account show --query id -o tsv)
  az account set --subscription "$SUBSCRIPTION"
fi
cleanup() {
  az postgres flexible-server firewall-rule delete -g "$RG" --server-name "$PG" --name "$RULE" --yes -o none 2>/dev/null || true
  [[ -n "${PREVIOUS_SUBSCRIPTION:-}" ]] && az account set --subscription "$PREVIOUS_SUBSCRIPTION"
  echo ">> firewall rule removed"
}
trap cleanup EXIT

MY_IP=$(curl -s https://api.ipify.org)
echo ">> temporary firewall rule for $MY_IP"
az postgres flexible-server firewall-rule create -g "$RG" --server-name "$PG" --name "$RULE" \
  --start-ip-address "$MY_IP" --end-ip-address "$MY_IP" -o none
PG_HOST=$(az postgres flexible-server show -g "$RG" -n "$PG" --query fullyQualifiedDomainName -o tsv)

echo ">> resetting tables and seeding demo data on $PG_HOST"
(cd billing_api && \
  DATABASE_URL="postgresql+psycopg://$PG_ADMIN:$PG_PASSWORD@$PG_HOST:5432/billing?sslmode=require" \
  ../.venv/bin/python -c "
from app.database import SessionLocal, engine
from app.models import Base
from app.seed import seed_demo_data
Base.metadata.drop_all(engine)
Base.metadata.create_all(engine)
with SessionLocal() as db:
    print('seeded:', seed_demo_data(db))
")
echo ">> done"

#!/bin/sh
# Renders the declarative Kong config from env vars, then starts Kong in DB-less mode.
set -eu
: "${BILLING_API_URL:?BILLING_API_URL is required, e.g. http://billing-api:8000}"
: "${JWT_SECRET:?JWT_SECRET is required (same value as the Billing API)}"
JWT_ISSUER="${JWT_ISSUER:-se4458-billing-auth}"
GATEWAY_SECRET="${GATEWAY_SECRET:-not-configured}"

sed -e "s|__BILLING_API_URL__|${BILLING_API_URL}|g" \
    -e "s|__GATEWAY_SECRET__|${GATEWAY_SECRET}|g" \
    -e "s|__JWT_SECRET__|${JWT_SECRET}|g" \
    -e "s|__JWT_ISSUER__|${JWT_ISSUER}|g" \
    /etc/kong/kong.template.yml > /tmp/kong.yml

export KONG_DECLARATIVE_CONFIG=/tmp/kong.yml
exec /docker-entrypoint.sh kong docker-start

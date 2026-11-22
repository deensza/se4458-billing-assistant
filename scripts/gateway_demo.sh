#!/usr/bin/env bash
# Reproducible API Gateway demonstration (works locally and in the cloud).
#   GATEWAY_URL=http://localhost:8000 ./scripts/gateway_demo.sh | tee docs/gateway-demo.txt
# Shows: public route, protected route without/with JWT, gateway error responses, authorization (403),
# rate-limit headers, and a simulated payment with duplicate protection.
set -u
G="${GATEWAY_URL:-http://localhost:8000}"
h() { echo; echo "### $*"; }
call() { echo "\$ curl $*" | sed -E 's/Bearer [A-Za-z0-9._-]+/Bearer <JWT>/'; curl -s -i "$@" | grep -iE '^HTTP/|^x-ratelimit-remaining-minute|^x-api-gateway|^x-request-id|^\{' ; echo; }
token() {
  curl -s -X POST "$G/api/v1/auth/token" -H 'Content-Type: application/json' \
    -d "{\"username\":\"$1\",\"password\":\"$2\"}" | python3 -c 'import sys,json;print(json.load(sys.stdin)["accessToken"])'
}

echo "Gateway: $G"
h "1. Public route (no auth): GET /api/v1/bills  (Query Bill)"
call "$G/api/v1/bills?subscriberNo=5551001&month=10&year=2026"

h "2. Protected route WITHOUT token -> rejected by the gateway (401)"
call "$G/api/v1/bills/detailed?subscriberNo=5551001&month=10&year=2026"

h "3. Protected route with a FORGED token -> rejected by the gateway (401)"
call "$G/api/v1/bills/detailed?subscriberNo=5551001&month=10&year=2026" -H "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.eyJpc3MiOiJzZTQ0NTgtYmlsbGluZy1hdXRoIiwic3ViIjoiaGFja2VyIn0.invalid"

h "4. Login: POST /api/v1/auth/token (user1001)"
T1=$(token user1001 'Pass1001!'); echo "accessToken: ${T1:0:40}..."

h "5. Protected route WITH token -> 200 (page 1, pageSize 2)"
echo "\$ curl $G/api/v1/bills/detailed?...&pageSize=2 -H 'Authorization: Bearer ...'"
curl -s -i "$G/api/v1/bills/detailed?subscriberNo=5551001&month=10&year=2026&page=1&pageSize=2" -H "Authorization: Bearer $T1" \
  | grep -iE '^HTTP/|^x-ratelimit-remaining-minute|^\{' | cut -c1-700; echo

h "6. user1001 tries to read subscriber 5551002 -> 403 from the API (authorization)"
call "$G/api/v1/bills/detailed?subscriberNo=5551002&month=10&year=2026" -H "Authorization: Bearer $T1"

h "7. user1001 tries to add usage to ANOTHER subscriber (5551002) -> 403"
call -X POST "$G/api/v1/usage" -H "Authorization: Bearer $T1" -H 'Content-Type: application/json' \
  -d '{"subscriberNo":"5551002","month":10,"year":2026,"usageType":"Phone"}'

h "8. Simulated payment: \$30 of the October bill (confirmed payment)"
TXN="DEMO-$(date +%s)"
call -X POST "$G/api/v1/payments" -H "Authorization: Bearer $T1" -H 'Content-Type: application/json' \
  -d "{\"subscriberNo\":\"5551001\",\"month\":10,\"year\":2026,\"amount\":30,\"transactionId\":\"$TXN\"}"

h "9. Same transaction ID again -> 409 DUPLICATE_TRANSACTION (balance unchanged)"
call -X POST "$G/api/v1/payments" -H "Authorization: Bearer $T1" -H 'Content-Type: application/json' \
  -d "{\"subscriberNo\":\"5551001\",\"month\":10,\"year\":2026,\"amount\":30,\"transactionId\":\"$TXN\"}"

h "10. Amount larger than the remaining balance -> 422 AMOUNT_EXCEEDS_BALANCE"
call -X POST "$G/api/v1/payments" -H "Authorization: Bearer $T1" -H 'Content-Type: application/json' \
  -d "{\"subscriberNo\":\"5551001\",\"month\":10,\"year\":2026,\"amount\":1000,\"transactionId\":\"$TXN-B\"}"

h "11. Unknown route -> gateway 404"
call "$G/api/v2/bills"

# Cloud only: the Billing API has its own public hostname but rejects calls that bypass the gateway.
if [[ -n "${BILLING_API_DIRECT_URL:-}" ]]; then
  h "12. Direct call to the Billing API, bypassing the gateway -> 403 GATEWAY_REQUIRED"
  call "$BILLING_API_DIRECT_URL/api/v1/bills?subscriberNo=5551001&month=10&year=2026"
fi

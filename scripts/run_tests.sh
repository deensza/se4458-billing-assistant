#!/usr/bin/env bash
# Runs every unit test suite (no cloud, no gateway, no LLM needed) and saves the output as evidence.
#   ./scripts/run_tests.sh
# Optional: run the Billing API tests against PostgreSQL instead of in-memory SQLite:
#   TEST_DATABASE_URL=postgresql+psycopg://billing:billing@localhost:5433/billing_test ./scripts/run_tests.sh
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="${PYTHON:-$ROOT/.venv/bin/python}"
OUT="$ROOT/docs/test-results.txt"
status=0
{
  echo "Test run: $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
  for suite in billing_api mcp_server agent; do
    echo; echo "================ $suite ================"
    (cd "$ROOT/$suite" && "$PY" -m pytest -vv -p no:cacheprovider) || status=1
  done
} 2>&1 | tee "$OUT"
exit ${PIPESTATUS[0]:-$status}

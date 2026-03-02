#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="${ROOT_DIR}/docs/test_logs"
CONTAINER_NAME="crypto-timescale-test"
DB_PORT="55432"
DB_NAME="crypto_db_test"
DB_USER="postgres"
DB_PASSWORD="postgres"
VENV_DIR="${ROOT_DIR}/.venv-test"

rm -rf "${LOG_DIR}"
mkdir -p "${LOG_DIR}"

cleanup() {
  if docker ps -a --format '{{.Names}}' | grep -qx "${CONTAINER_NAME}"; then
    docker rm -f "${CONTAINER_NAME}" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

cleanup

echo "[test_all] Starting ephemeral TimescaleDB container..."
docker run -d \
  --name "${CONTAINER_NAME}" \
  -e POSTGRES_USER="${DB_USER}" \
  -e POSTGRES_PASSWORD="${DB_PASSWORD}" \
  -e POSTGRES_DB="postgres" \
  -p "${DB_PORT}:5432" \
  timescale/timescaledb:2.13.1-pg15 \
  postgres -c shared_preload_libraries=timescaledb \
  > "${LOG_DIR}/container_start.log"

echo "[test_all] Waiting for database readiness..."
ready=0
ready_streak=0
for _ in {1..120}; do
  if ! docker ps --format '{{.Names}}' | grep -qx "${CONTAINER_NAME}"; then
    break
  fi
  if docker exec "${CONTAINER_NAME}" pg_isready -U "${DB_USER}" -d postgres >/dev/null 2>&1 \
    && docker exec "${CONTAINER_NAME}" psql -U "${DB_USER}" -d postgres -At -c "SELECT 1;" >/dev/null 2>&1; then
    ready_streak=$((ready_streak + 1))
    if [ "${ready_streak}" -ge 3 ]; then
      ready=1
      break
    fi
  else
    ready_streak=0
  fi
  sleep 1
done

if [ "${ready}" -ne 1 ]; then
  if docker ps -a --format '{{.Names}}' | grep -qx "${CONTAINER_NAME}"; then
    docker logs "${CONTAINER_NAME}" > "${LOG_DIR}/container_boot.log" 2>&1 || true
  fi
  echo "[test_all] ERROR: Database did not become ready." >&2
  exit 1
fi

# Guard against transient post-ready restarts observed in container startup.
sleep 2
if ! docker exec "${CONTAINER_NAME}" psql -U "${DB_USER}" -d postgres -At -c "SELECT 1;" >/dev/null 2>&1; then
  docker logs "${CONTAINER_NAME}" > "${LOG_DIR}/container_boot.log" 2>&1 || true
  echo "[test_all] ERROR: Database became unavailable after readiness check." >&2
  exit 1
fi

echo "[test_all] Creating clean-room database ${DB_NAME}..."
docker exec -i "${CONTAINER_NAME}" psql -U "${DB_USER}" -d postgres -v ON_ERROR_STOP=1 \
  -c "DROP DATABASE IF EXISTS ${DB_NAME};" \
  > "${LOG_DIR}/db_create.log"
docker exec -i "${CONTAINER_NAME}" psql -U "${DB_USER}" -d postgres -v ON_ERROR_STOP=1 \
  -c "CREATE DATABASE ${DB_NAME};" \
  >> "${LOG_DIR}/db_create.log"

echo "[test_all] Applying canonical bootstrap schema..."
docker exec -i "${CONTAINER_NAME}" psql -U "${DB_USER}" -d "${DB_NAME}" -v ON_ERROR_STOP=1 \
  < "${ROOT_DIR}/schema_bootstrap.sql" \
  > "${LOG_DIR}/schema_bootstrap_apply.log"

echo "[test_all] Running Phase 1C validation gates..."
docker exec -i "${CONTAINER_NAME}" psql -U "${DB_USER}" -d "${DB_NAME}" -v ON_ERROR_STOP=1 -At \
  < "${ROOT_DIR}/docs/validations/PHASE_1C_VALIDATION.sql" \
  | tee "${LOG_DIR}/phase_1c_validation.log"

if ! awk -F'|' 'NF==2 { if ($2 != 0) { exit 1 } }' "${LOG_DIR}/phase_1c_validation.log"; then
  echo "[test_all] ERROR: Phase 1C validation gate failed." >&2
  exit 1
fi

echo "[test_all] Running Phase 1D validation gates..."
docker exec -i "${CONTAINER_NAME}" psql -U "${DB_USER}" -d "${DB_NAME}" -v ON_ERROR_STOP=1 -At \
  < "${ROOT_DIR}/docs/validations/PHASE_1D_RUNTIME_VALIDATION.sql" \
  | tee "${LOG_DIR}/phase_1d_validation.log"

if ! awk -F'|' 'NF==2 { if ($2 != 0) { exit 1 } }' "${LOG_DIR}/phase_1d_validation.log"; then
  echo "[test_all] ERROR: Phase 1D validation gate failed." >&2
  exit 1
fi

echo "[test_all] Running Phase 2 validation gates..."
docker exec -i "${CONTAINER_NAME}" psql -U "${DB_USER}" -d "${DB_NAME}" -v ON_ERROR_STOP=1 -At \
  < "${ROOT_DIR}/docs/validations/PHASE_2_REPLAY_HARNESS_VALIDATION.sql" \
  | tee "${LOG_DIR}/phase_2_validation.log"

if ! awk -F'|' 'NF==2 { if ($2 != 0) { exit 1 } }' "${LOG_DIR}/phase_2_validation.log"; then
  echo "[test_all] ERROR: Phase 2 validation gate failed." >&2
  exit 1
fi

echo "[test_all] Running Phase 3 validation gates..."
docker exec -i "${CONTAINER_NAME}" psql -U "${DB_USER}" -d "${DB_NAME}" -v ON_ERROR_STOP=1 -At \
  < "${ROOT_DIR}/docs/validations/PHASE_3_RUNTIME_VALIDATION.sql" \
  | tee "${LOG_DIR}/phase_3_validation.log"

if ! awk -F'|' 'NF==2 { if ($2 != 0) { exit 1 } }' "${LOG_DIR}/phase_3_validation.log"; then
  echo "[test_all] ERROR: Phase 3 validation gate failed." >&2
  exit 1
fi

echo "[test_all] Running Phase 4 validation gates..."
docker exec -i "${CONTAINER_NAME}" psql -U "${DB_USER}" -d "${DB_NAME}" -v ON_ERROR_STOP=1 -At \
  < "${ROOT_DIR}/docs/validations/PHASE_4_ORDER_LIFECYCLE_VALIDATION.sql" \
  | tee "${LOG_DIR}/phase_4_validation.log"

if ! awk -F'|' 'NF==2 { if ($2 != 0) { exit 1 } }' "${LOG_DIR}/phase_4_validation.log"; then
  echo "[test_all] ERROR: Phase 4 validation gate failed." >&2
  exit 1
fi

echo "[test_all] Verifying schema equivalence against canonical bootstrap..."
docker exec "${CONTAINER_NAME}" pg_dump -U "${DB_USER}" -d "${DB_NAME}" --schema-only --no-owner --no-privileges \
  > "${LOG_DIR}/live_schema.sql"
shasum -a 256 "${LOG_DIR}/live_schema.sql" "${ROOT_DIR}/schema_bootstrap.sql" \
  | tee "${LOG_DIR}/schema_sha256.log"
if ! cmp -s "${LOG_DIR}/live_schema.sql" "${ROOT_DIR}/schema_bootstrap.sql"; then
  echo "[test_all] ERROR: schema bootstrap equivalence check failed." >&2
  exit 1
fi

echo "[test_all] Preparing Python test environment..."
rm -rf "${VENV_DIR}"
python3 -m venv "${VENV_DIR}"
source "${VENV_DIR}/bin/activate"
python -m pip install --upgrade pip > "${LOG_DIR}/pip_install.log"
python -m pip install -r "${ROOT_DIR}/requirements-dev.txt" >> "${LOG_DIR}/pip_install.log"

echo "[test_all] Enabling runtime fixture inserts in ephemeral DB..."
docker exec -i "${CONTAINER_NAME}" psql -U "${DB_USER}" -d "${DB_NAME}" -v ON_ERROR_STOP=1 -At \
  < "${ROOT_DIR}/docs/validations/TEST_RUNTIME_INSERT_ENABLE.sql" \
  | tee "${LOG_DIR}/test_runtime_insert_enable.log"

if ! awk -F'|' 'NF==2 { if ($2 != 0) { exit 1 } }' "${LOG_DIR}/test_runtime_insert_enable.log"; then
  echo "[test_all] ERROR: Failed to disable ts_insert_blocker triggers for test harness." >&2
  exit 1
fi

export TEST_DB_HOST="localhost"
export TEST_DB_PORT="${DB_PORT}"
export TEST_DB_NAME="${DB_NAME}"
export TEST_DB_USER="${DB_USER}"
export TEST_DB_PASSWORD="${DB_PASSWORD}"

echo "[test_all] Running Phase 2 replay-tool smoke check..."
python "${ROOT_DIR}/scripts/replay_cli.py" \
  --host "${TEST_DB_HOST}" \
  --port "${TEST_DB_PORT}" \
  --dbname "${TEST_DB_NAME}" \
  --user "${TEST_DB_USER}" \
  --password "${TEST_DB_PASSWORD}" \
  replay-tool \
  | tee "${LOG_DIR}/phase_2_replay_tool_smoke.log"

echo "[test_all] Running pytest + coverage..."
cd "${ROOT_DIR}"
pytest | tee "${LOG_DIR}/pytest.log"

echo "[test_all] PASS"

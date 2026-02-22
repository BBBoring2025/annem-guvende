#!/usr/bin/env bash
# Sprint 12: CI-local kontrol scripti.
# Kullanim: bash scripts/ci_check.sh

set -euo pipefail

echo "=== 1/4 Compile check ==="
python -m compileall -q src/

echo "=== 2/4 Import check ==="
python -c "import src.main; import src.collector.mqtt_client; import src.simulator.sensor_simulator; print('All imports OK')"

echo "=== 3/4 Ruff lint ==="
ruff check src/ tests/

echo "=== 4/4 Pytest ==="
pytest -v --tb=short

echo ""
echo "All checks passed!"

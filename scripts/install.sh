#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ "${EUID}" -ne 0 ]]; then
    SUDO=sudo
else
    SUDO=""
fi

echo "Installing YERB Pool dependencies..."
$SUDO apt-get update
$SUDO apt-get install -y build-essential cmake git python3 sqlite3 libboost-dev

if [[ ! -f config.json ]]; then
    cp config.example.json config.json
    echo "Created config.json from config.example.json"
else
    echo "Keeping existing config.json"
fi

echo "Building native GhostRider verifier..."
./scripts/build-native.sh

echo "Creating/upgrading pool database..."
python3 ./scripts/init-db.py

DB_PATH=$(python3 - <<'PY'
import json
from pathlib import Path
root = Path.cwd()
config = json.loads((root / 'config.json').read_text())
p = Path(config.get('database', 'yerbpool.db'))
print(p if p.is_absolute() else root / p)
PY
)

chmod 600 "$DB_PATH" 2>/dev/null || true

echo
echo "YERB Pool installation complete."
echo "Database: $DB_PATH"
echo "Edit configuration before starting: $ROOT/config.json"
echo "Start manually with: cd $ROOT && python3 pool.py"
echo
echo "Database tables:"
sqlite3 "$DB_PATH" '.tables'

#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ "${EUID}" -ne 0 ]]; then
    SUDO=sudo
else
    SUDO=""
fi

INSTALL_DIR=/opt/yerb-pool
SERVICE_USER=yerbpool

echo "Installing YERB Pool dependencies..."
$SUDO apt-get update
$SUDO apt-get install -y build-essential cmake git python3 sqlite3 libboost-dev nginx rsync

if ! id "$SERVICE_USER" >/dev/null 2>&1; then
    $SUDO useradd --system --home "$INSTALL_DIR" --shell /usr/sbin/nologin "$SERVICE_USER"
fi

# Create a source config for first install only. Existing production config in
# /opt/yerb-pool is never overwritten by subsequent installer runs.
if [[ ! -f config.json && ! -f "$INSTALL_DIR/config.json" ]]; then
    cp config.example.json config.json
    echo "Created config.json from config.example.json"
fi

echo "Building native GhostRider verifier..."
./scripts/build-native.sh

echo "Installing pool to $INSTALL_DIR..."
$SUDO mkdir -p "$INSTALL_DIR"

# Never overwrite live accounting/configuration during an upgrade.
$SUDO rsync -a --delete \
  --exclude '.git/' \
  --exclude 'config.json' \
  --exclude '*.db' \
  --exclude '*.db-wal' \
  --exclude '*.db-shm' \
  --exclude 'native/build/' \
  "$ROOT/" "$INSTALL_DIR/"

$SUDO mkdir -p "$INSTALL_DIR/native/build"
if [[ -f "$ROOT/native/build/libyerb_ghostrider.so" ]]; then
    $SUDO cp "$ROOT/native/build/libyerb_ghostrider.so" "$INSTALL_DIR/native/build/"
fi

# First install: copy the configured source file. Upgrades: keep live config.
if [[ ! -f "$INSTALL_DIR/config.json" ]]; then
    if [[ -f "$ROOT/config.json" ]]; then
        $SUDO cp "$ROOT/config.json" "$INSTALL_DIR/config.json"
    else
        $SUDO cp "$ROOT/config.example.json" "$INSTALL_DIR/config.json"
    fi
fi

# Migrate only the original testing default. Do not touch any other user
# settings or a deliberately customized difficulty.
$SUDO python3 - "$INSTALL_DIR/config.json" <<'PY'
import json
import sys
from pathlib import Path
p = Path(sys.argv[1])
cfg = json.loads(p.read_text())
stratum = cfg.setdefault("stratum", {})
old = float(stratum.get("difficulty", 0.000001))
if abs(old - 0.00001) < 1e-15:
    stratum["difficulty"] = 0.000001
    p.write_text(json.dumps(cfg, indent=2) + "\n")
    print("Migrated Stratum test difficulty: 1e-05 -> 1e-06")
else:
    print(f"Keeping configured Stratum difficulty: {old:g}")
PY

$SUDO chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR"
$SUDO chmod 600 "$INSTALL_DIR/config.json" 2>/dev/null || true

echo "Creating/upgrading production pool database..."
(
  cd "$INSTALL_DIR"
  if [[ -n "$SUDO" ]]; then
      $SUDO -u "$SERVICE_USER" /usr/bin/python3 ./scripts/init-db.py
  else
      runuser -u "$SERVICE_USER" -- /usr/bin/python3 ./scripts/init-db.py
  fi
)

echo "Installing systemd services..."
$SUDO cp "$ROOT/systemd/yerb-pool.service" /etc/systemd/system/yerb-pool.service
$SUDO cp "$ROOT/systemd/yerb-pool-web.service" /etc/systemd/system/yerb-pool-web.service

$SUDO sed -i \
  -e 's#WorkingDirectory=.*#WorkingDirectory=/opt/yerb-pool#' \
  -e 's#ExecStart=.*#ExecStart=/usr/bin/python3 /opt/yerb-pool/pool.py#' \
  -e 's#^User=.*#User=yerbpool#' \
  -e 's#^Group=.*#Group=yerbpool#' \
  /etc/systemd/system/yerb-pool.service

$SUDO systemctl daemon-reload
$SUDO systemctl enable yerb-pool yerb-pool-web

echo "Installing Nginx configuration..."
$SUDO cp "$ROOT/nginx/yerb-pool.conf" /etc/nginx/sites-available/yerb-pool
$SUDO ln -sf /etc/nginx/sites-available/yerb-pool /etc/nginx/sites-enabled/yerb-pool
$SUDO rm -f /etc/nginx/sites-enabled/default
$SUDO nginx -t
$SUDO systemctl enable nginx
$SUDO systemctl restart nginx

if command -v ufw >/dev/null 2>&1; then
    $SUDO ufw allow 80/tcp >/dev/null || true
    $SUDO ufw allow 3333/tcp >/dev/null || true
fi

# Stop any stale manually launched checkout copy before binding production port.
pkill -f "$ROOT/pool.py" 2>/dev/null || true

$SUDO systemctl restart yerb-pool-web
$SUDO systemctl restart yerb-pool

echo
echo "YERB Pool installation complete."
echo "Install directory: $INSTALL_DIR"
echo "Dashboard: http://SERVER_IP/"
echo "Web backend: http://127.0.0.1:8080"
echo "Stratum: tcp://SERVER_IP:3333"
echo "Configuration: $INSTALL_DIR/config.json"
echo
echo "Service status:"
$SUDO systemctl --no-pager --full status yerb-pool-web || true
$SUDO systemctl --no-pager --full status yerb-pool || true

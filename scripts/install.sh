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
$SUDO apt-get install -y build-essential cmake git python3 sqlite3 libboost-dev nginx

if ! id "$SERVICE_USER" >/dev/null 2>&1; then
    $SUDO useradd --system --home "$INSTALL_DIR" --shell /usr/sbin/nologin "$SERVICE_USER"
fi

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

echo "Installing pool to $INSTALL_DIR..."
$SUDO mkdir -p "$INSTALL_DIR"
$SUDO rsync -a --delete \
  --exclude '.git/' \
  --exclude 'native/build/' \
  "$ROOT/" "$INSTALL_DIR/"

# Preserve/copy built GhostRider library into installed tree.
$SUDO mkdir -p "$INSTALL_DIR/native/build"
if [[ -f "$ROOT/native/build/libyerb_ghostrider.so" ]]; then
    $SUDO cp "$ROOT/native/build/libyerb_ghostrider.so" "$INSTALL_DIR/native/build/"
fi

$SUDO chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR"
$SUDO chmod 600 "$INSTALL_DIR/config.json" 2>/dev/null || true

# If the configured database is inside the source checkout, copy it to installed tree.
if [[ "$DB_PATH" == "$ROOT"/* ]]; then
    REL_DB="${DB_PATH#$ROOT/}"
    $SUDO mkdir -p "$INSTALL_DIR/$(dirname "$REL_DB")"
    $SUDO cp "$DB_PATH" "$INSTALL_DIR/$REL_DB"
    $SUDO chown "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR/$REL_DB"
fi

echo "Installing systemd services..."
$SUDO cp "$ROOT/systemd/yerb-pool.service" /etc/systemd/system/yerb-pool.service
$SUDO cp "$ROOT/systemd/yerb-pool-web.service" /etc/systemd/system/yerb-pool-web.service

# Normalize existing pool service paths/user for /opt installation.
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

# Start/restart services after files/config are installed.
$SUDO systemctl restart yerb-pool-web
$SUDO systemctl restart yerb-pool || true

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

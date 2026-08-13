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

# Migrate only the known invalid early GhostRider testing defaults.
$SUDO python3 - "$INSTALL_DIR/config.json" <<'PY'
import json
import sys
from pathlib import Path
p = Path(sys.argv[1])
cfg = json.loads(p.read_text())
stratum = cfg.setdefault("stratum", {})
old = float(stratum.get("difficulty", 0.05))
if abs(old - 0.00001) < 1e-15 or abs(old - 0.000001) < 1e-15:
    stratum["difficulty"] = 0.05
    p.write_text(json.dumps(cfg, indent=2) + "\n")
    print(f"Migrated invalid GhostRider Stratum difficulty: {old:g} -> 0.05")
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

DASHBOARD_URL="http://SERVER_IP/"

configure_domain_https() {
    local domain=""
    local enable_ssl="n"

    echo
    echo "Optional domain / HTTPS setup"
    echo "-----------------------------"
    read -r -p "Configure a domain name for the pool website? (y/N): " configure_domain
    if [[ ! "$configure_domain" =~ ^[Yy]$ ]]; then
        return 0
    fi

    while true; do
        read -r -p "Domain name (example: pool.yerbas.org): " domain
        domain="${domain,,}"
        if [[ "$domain" =~ ^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$ ]]; then
            break
        fi
        echo "Invalid domain name. Enter a hostname only, without http://, https://, paths, or ports."
    done

    echo "Configuring Nginx for ${domain}..."
    $SUDO tee /etc/nginx/sites-available/yerb-pool >/dev/null <<EOF
server {
    listen 80;
    listen [::]:80;

    server_name ${domain};

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
    }

    access_log /var/log/nginx/yerb-pool-access.log;
    error_log /var/log/nginx/yerb-pool-error.log;
}
EOF

    $SUDO ln -sf /etc/nginx/sites-available/yerb-pool /etc/nginx/sites-enabled/yerb-pool
    $SUDO nginx -t
    $SUDO systemctl reload nginx
    DASHBOARD_URL="http://${domain}/"

    echo
    echo "DNS check for ${domain}:"
    resolved_ips="$(getent ahostsv4 "$domain" 2>/dev/null | awk '{print $1}' | sort -u | tr '\n' ' ' || true)"
    if [[ -n "$resolved_ips" ]]; then
        echo "  Resolves to: ${resolved_ips}"
    else
        echo "  WARNING: ${domain} does not currently resolve to an IPv4 address."
        echo "  Create an A record pointing ${domain} to this server before requesting a certificate."
    fi

    read -r -p "Secure ${domain} with a Let's Encrypt certificate using Certbot? (y/N): " enable_ssl
    if [[ ! "$enable_ssl" =~ ^[Yy]$ ]]; then
        return 0
    fi

    if [[ -z "$resolved_ips" ]]; then
        echo "Skipping Certbot because DNS is not resolving yet."
        echo "After DNS is ready, run: sudo certbot --nginx -d ${domain}"
        return 0
    fi

    echo "Installing Certbot..."
    $SUDO apt-get update
    $SUDO apt-get install -y certbot python3-certbot-nginx

    if command -v ufw >/dev/null 2>&1; then
        $SUDO ufw allow 443/tcp >/dev/null || true
    fi

    echo "Requesting Let's Encrypt certificate for ${domain}..."
    if $SUDO certbot --nginx -d "$domain"; then
        DASHBOARD_URL="https://${domain}/"
        echo "HTTPS enabled successfully: ${DASHBOARD_URL}"
        echo "Certbot installed its automatic certificate renewal timer."
    else
        echo "Certbot could not issue the certificate."
        echo "The HTTP site remains configured at http://${domain}/"
        echo "Verify DNS and ports 80/443, then retry: sudo certbot --nginx -d ${domain}"
    fi
}

# Interactive installs get the optional domain/HTTPS wizard. Automated installs
# remain non-interactive and keep the default IP-based Nginx configuration.
if [[ -t 0 ]]; then
    configure_domain_https
else
    echo "Non-interactive install detected; skipping optional domain/Certbot wizard."
fi

echo
echo "YERB Pool installation complete."
echo "Install directory: $INSTALL_DIR"
echo "Dashboard: $DASHBOARD_URL"
echo "Web backend: http://127.0.0.1:8080"
echo "Stratum: tcp://SERVER_IP:3333"
echo "Configuration: $INSTALL_DIR/config.json"
echo
echo "Service status:"
$SUDO systemctl --no-pager --full status yerb-pool-web || true
$SUDO systemctl --no-pager --full status yerb-pool || true

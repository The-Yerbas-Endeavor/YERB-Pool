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
SSL_DOMAIN=""
CERTBOT_PRESENT=false
EXISTING_SSL_DOMAIN=""
NGINX_SITE=/etc/nginx/sites-available/yerb-pool
NGINX_ENABLED=/etc/nginx/sites-enabled/yerb-pool
DASHBOARD_URL="http://SERVER_IP/"

usage() {
    cat <<'EOF'
Usage:
  bash install.sh
  bash install.sh --ssl pool.example.com

Options:
  --ssl DOMAIN   Configure Nginx for DOMAIN and enable HTTPS with Certbot.
                 Reuses an existing Let's Encrypt certificate when present.
  -h, --help     Show this help.
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --ssl)
            if [[ $# -lt 2 || -z "${2:-}" ]]; then
                echo "ERROR: --ssl requires a domain name."
                usage
                exit 2
            fi
            SSL_DOMAIN="${2,,}"
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "ERROR: Unknown option: $1"
            usage
            exit 2
            ;;
    esac
done

valid_domain() {
    [[ "$1" =~ ^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$ ]]
}

cert_exists_for_domain() {
    local domain="$1"
    [[ -f "/etc/letsencrypt/live/${domain}/fullchain.pem" \
       && -f "/etc/letsencrypt/live/${domain}/privkey.pem" ]]
}

nginx_https_active_for_domain() {
    local domain="$1"
    local escaped_domain="${domain//./\\.}"

    [[ -f "$NGINX_SITE" ]] || return 1
    grep -Eq '^[[:space:]]*listen[[:space:]]+(\[::\]:)?443([^;]*)[[:space:]]ssl[[:space:]]*;' "$NGINX_SITE" || return 1
    grep -Eq "^[[:space:]]*server_name[[:space:]]+[^;]*${escaped_domain}([^a-zA-Z0-9.-]|;|$)" "$NGINX_SITE" || return 1
    return 0
}

detect_existing_https() {
    CERTBOT_PRESENT=false
    EXISTING_SSL_DOMAIN=""

    if command -v certbot >/dev/null 2>&1; then
        CERTBOT_PRESENT=true
        local cert_domain=""
        cert_domain="$($SUDO certbot certificates 2>/dev/null | awk '/Certificate Name:/ {print $3; exit}' || true)"
        if [[ -n "$cert_domain" ]] && valid_domain "$cert_domain" \
           && cert_exists_for_domain "$cert_domain"; then
            EXISTING_SSL_DOMAIN="$cert_domain"
        fi
    fi

    if [[ -z "$EXISTING_SSL_DOMAIN" && -f "$NGINX_SITE" ]]; then
        local nginx_domain=""
        nginx_domain="$(awk '/^[[:space:]]*server_name[[:space:]]+/ {for(i=2;i<=NF;i++){gsub(/;/,"",$i); if($i!="_" && $i!="localhost"){print $i; exit}}}' "$NGINX_SITE" 2>/dev/null || true)"
        if [[ -n "$nginx_domain" ]] && valid_domain "$nginx_domain"; then
            EXISTING_SSL_DOMAIN="$nginx_domain"
        fi
    fi
}

if [[ -n "$SSL_DOMAIN" ]] && ! valid_domain "$SSL_DOMAIN"; then
    echo "ERROR: Invalid SSL domain: $SSL_DOMAIN"
    echo "Use a hostname only, such as pool.yerbas.org."
    exit 2
fi

echo "Installing YERB Pool dependencies..."
$SUDO apt-get update
$SUDO apt-get install -y build-essential cmake git python3 sqlite3 libboost-dev nginx rsync

detect_existing_https
if [[ -f "$NGINX_SITE" ]]; then
    echo "Existing YERB Pool Nginx site detected; normal upgrades will preserve it."
fi
if [[ -n "$EXISTING_SSL_DOMAIN" ]]; then
    echo "Existing pool domain detected: ${EXISTING_SSL_DOMAIN}"
fi
if [[ "$CERTBOT_PRESENT" == true ]]; then
    echo "Certbot is already installed."
fi

if ! id "$SERVICE_USER" >/dev/null 2>&1; then
    $SUDO useradd --system --home "$INSTALL_DIR" --shell /usr/sbin/nologin "$SERVICE_USER"
fi

if [[ ! -f config.json && ! -f "$INSTALL_DIR/config.json" ]]; then
    cp config.example.json config.json
    echo "Created config.json from config.example.json"
fi

echo "Building native GhostRider verifier..."
./scripts/build-native.sh

echo "Installing pool to $INSTALL_DIR..."
$SUDO mkdir -p "$INSTALL_DIR"
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

if [[ ! -f "$INSTALL_DIR/config.json" ]]; then
    if [[ -f "$ROOT/config.json" ]]; then
        $SUDO cp "$ROOT/config.json" "$INSTALL_DIR/config.json"
    else
        $SUDO cp "$ROOT/config.example.json" "$INSTALL_DIR/config.json"
    fi
fi

$SUDO python3 - "$INSTALL_DIR/config.json" <<'PY'
import json
import sys
from pathlib import Path

p = Path(sys.argv[1])
cfg = json.loads(p.read_text())
stratum = cfg.setdefault("stratum", {})
old = float(stratum.get("difficulty", 0.05))
changed = False

if abs(old - 0.00001) < 1e-15 or abs(old - 0.000001) < 1e-15:
    stratum["difficulty"] = 0.05
    old = 0.05
    changed = True
    print("Migrated invalid GhostRider Stratum difficulty -> 0.05")
else:
    print(f"Keeping configured Stratum difficulty: {old:g}")

vardiff = stratum.setdefault("vardiff", {})
def default(key, value):
    global changed
    if key not in vardiff:
        vardiff[key] = value
        changed = True

default("enabled", True)
default("min_difficulty", max(0.05, min(old, 0.05)))
default("max_difficulty", 65536.0)
default("target_share_seconds", 12)
default("retarget_seconds", 60)
default("variance_percent", 30)
default("max_step_factor", 2.0)

if changed:
    p.write_text(json.dumps(cfg, indent=2) + "\n")
    print("Added/updated GhostRider VarDiff configuration")
else:
    print("Keeping existing GhostRider VarDiff configuration")
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

echo "Checking Nginx configuration..."
if [[ -f "$NGINX_SITE" ]]; then
    echo "Preserving existing Nginx site: $NGINX_SITE"
else
    echo "No existing pool site found; installing default YERB Pool Nginx configuration."
    $SUDO cp "$ROOT/nginx/yerb-pool.conf" "$NGINX_SITE"
fi
$SUDO ln -sf "$NGINX_SITE" "$NGINX_ENABLED"
$SUDO rm -f /etc/nginx/sites-enabled/default
$SUDO nginx -t
$SUDO systemctl enable nginx
$SUDO systemctl reload nginx 2>/dev/null || $SUDO systemctl restart nginx

if command -v ufw >/dev/null 2>&1; then
    $SUDO ufw allow 80/tcp >/dev/null || true
    $SUDO ufw allow 3333/tcp >/dev/null || true
    if [[ "$CERTBOT_PRESENT" == true || -n "$EXISTING_SSL_DOMAIN" ]]; then
        $SUDO ufw allow 443/tcp >/dev/null || true
    fi
fi

pkill -f "$ROOT/pool.py" 2>/dev/null || true
$SUDO systemctl restart yerb-pool-web
$SUDO systemctl restart yerb-pool

configure_nginx_domain() {
    local domain="$1"
    echo "Configuring HTTP Nginx site for ${domain}..."
    $SUDO tee "$NGINX_SITE" >/dev/null <<EOF
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
        proxy_read_timeout 30s;
    }

    access_log /var/log/nginx/yerb-pool-access.log;
    error_log /var/log/nginx/yerb-pool-error.log;
}
EOF
    $SUDO ln -sf "$NGINX_SITE" "$NGINX_ENABLED"
    $SUDO rm -f /etc/nginx/sites-enabled/default
    $SUDO nginx -t
    $SUDO systemctl reload nginx
    DASHBOARD_URL="http://${domain}/"
}

configure_nginx_https_existing_cert() {
    local domain="$1"
    local backup=""

    if ! cert_exists_for_domain "$domain"; then
        echo "ERROR: Existing certificate files for ${domain} were not found."
        return 1
    fi

    if [[ -f "$NGINX_SITE" ]]; then
        backup="${NGINX_SITE}.bak.$(date +%s)"
        $SUDO cp "$NGINX_SITE" "$backup"
    fi

    echo "Restoring HTTPS Nginx configuration for ${domain} from the existing certificate..."
    $SUDO tee "$NGINX_SITE" >/dev/null <<EOF
server {
    listen 80;
    listen [::]:80;
    server_name ${domain};
    return 301 https://\$host\$request_uri;
}

server {
    listen 443 ssl;
    listen [::]:443 ssl;
    server_name ${domain};

    ssl_certificate /etc/letsencrypt/live/${domain}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/${domain}/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 30s;
    }

    access_log /var/log/nginx/yerb-pool-access.log;
    error_log /var/log/nginx/yerb-pool-error.log;
}
EOF

    $SUDO ln -sf "$NGINX_SITE" "$NGINX_ENABLED"
    $SUDO rm -f /etc/nginx/sites-enabled/default

    if ! $SUDO nginx -t; then
        echo "ERROR: Repaired SSL configuration failed Nginx validation."
        if [[ -n "$backup" && -f "$backup" ]]; then
            $SUDO cp "$backup" "$NGINX_SITE"
            $SUDO nginx -t || true
        else
            $SUDO rm -f "$NGINX_SITE"
        fi
        return 1
    fi

    $SUDO systemctl reload nginx
    DASHBOARD_URL="https://${domain}/"
    echo "HTTPS Nginx configuration restored: ${DASHBOARD_URL}"
}

check_dns() {
    local domain="$1"
    local resolved_ips
    resolved_ips="$(getent ahostsv4 "$domain" 2>/dev/null | awk '{print $1}' | sort -u | tr '\n' ' ' || true)"
    if [[ -z "$resolved_ips" ]]; then
        echo "ERROR: ${domain} does not currently resolve to an IPv4 address."
        echo "Create an A record pointing the domain to this server, then retry."
        return 1
    fi
    echo "DNS for ${domain}: ${resolved_ips}"
}

ensure_certbot_nginx() {
    if ! command -v certbot >/dev/null 2>&1; then
        echo "Installing Certbot and Nginx plugin..."
        $SUDO apt-get update
        $SUDO apt-get install -y certbot python3-certbot-nginx
    elif ! dpkg-query -W -f='${Status}' python3-certbot-nginx 2>/dev/null | grep -q 'install ok installed'; then
        echo "Certbot is installed; adding the Nginx plugin..."
        $SUDO apt-get install -y python3-certbot-nginx
    else
        echo "Certbot and the Nginx plugin are already installed."
    fi
    CERTBOT_PRESENT=true
}

install_certbot_ssl() {
    local domain="$1"

    if cert_exists_for_domain "$domain"; then
        if nginx_https_active_for_domain "$domain"; then
            echo "HTTPS is already active for ${domain}; no SSL changes needed."
            DASHBOARD_URL="https://${domain}/"
        else
            echo "Certificate exists for ${domain}, but Nginx is not serving HTTPS."
            configure_nginx_https_existing_cert "$domain"
        fi
        $SUDO systemctl enable certbot.timer >/dev/null 2>&1 || true
        $SUDO systemctl start certbot.timer >/dev/null 2>&1 || true
        return 0
    fi

    check_dns "$domain" || return 1
    ensure_certbot_nginx
    configure_nginx_domain "$domain"

    if command -v ufw >/dev/null 2>&1; then
        $SUDO ufw allow 80/tcp >/dev/null || true
        $SUDO ufw allow 443/tcp >/dev/null || true
    fi

    echo "Requesting Let's Encrypt certificate for ${domain}..."
    if ! $SUDO certbot --nginx \
        -d "$domain" \
        --redirect \
        --agree-tos \
        --register-unsafely-without-email \
        --non-interactive; then
        echo "ERROR: Certbot could not issue the certificate."
        echo "HTTP remains available at http://${domain}/"
        return 1
    fi

    if nginx_https_active_for_domain "$domain"; then
        DASHBOARD_URL="https://${domain}/"
    elif cert_exists_for_domain "$domain"; then
        configure_nginx_https_existing_cert "$domain"
    else
        echo "ERROR: Certbot returned success but the certificate or HTTPS Nginx configuration is missing."
        return 1
    fi

    $SUDO systemctl enable certbot.timer >/dev/null 2>&1 || true
    $SUDO systemctl start certbot.timer >/dev/null 2>&1 || true
    echo "HTTPS enabled successfully: ${DASHBOARD_URL}"
}

configure_domain_interactive() {
    local domain=""
    local enable_ssl="n"
    local configure_domain="n"

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
        if valid_domain "$domain"; then
            break
        fi
        echo "Invalid domain name. Enter a hostname only, without http://, https://, paths, or ports."
    done

    configure_nginx_domain "$domain"
    read -r -p "Secure ${domain} with a Let's Encrypt certificate using Certbot? (y/N): " enable_ssl
    if [[ "$enable_ssl" =~ ^[Yy]$ ]]; then
        install_certbot_ssl "$domain" || true
    fi
}

# SSL/domain state handling is intentionally idempotent:
# - --ssl DOMAIN explicitly configures or repairs that domain.
# - Existing certificate + active 443 is left untouched.
# - Existing certificate + missing 443 is repaired automatically.
# - Certbot already installed without a known certificate never prompts again.
if [[ -n "$SSL_DOMAIN" ]]; then
    echo
    echo "HTTPS setup requested for: ${SSL_DOMAIN}"
    install_certbot_ssl "$SSL_DOMAIN"
elif [[ -n "$EXISTING_SSL_DOMAIN" ]] && cert_exists_for_domain "$EXISTING_SSL_DOMAIN"; then
    echo
    if nginx_https_active_for_domain "$EXISTING_SSL_DOMAIN"; then
        echo "Existing HTTPS configuration for ${EXISTING_SSL_DOMAIN} is active; leaving it unchanged."
        DASHBOARD_URL="https://${EXISTING_SSL_DOMAIN}/"
    else
        echo "Existing certificate found for ${EXISTING_SSL_DOMAIN}, but the Nginx 443 SSL server is missing."
        echo "Repairing HTTPS automatically..."
        configure_nginx_https_existing_cert "$EXISTING_SSL_DOMAIN"
    fi
    $SUDO systemctl enable certbot.timer >/dev/null 2>&1 || true
    $SUDO systemctl start certbot.timer >/dev/null 2>&1 || true
elif [[ "$CERTBOT_PRESENT" == true ]]; then
    echo "Certbot is already installed; skipping domain setup prompt."
    echo "Run 'bash install.sh --ssl DOMAIN' only if SSL still needs to be configured."
    if [[ -n "$EXISTING_SSL_DOMAIN" ]]; then
        DASHBOARD_URL="http://${EXISTING_SSL_DOMAIN}/"
    fi
elif [[ -t 0 ]]; then
    configure_domain_interactive
else
    echo "Non-interactive install detected; skipping optional domain/Certbot wizard."
fi

# Never report an HTTPS URL unless the active Nginx site actually serves 443 SSL.
if [[ -n "$EXISTING_SSL_DOMAIN" ]]; then
    if nginx_https_active_for_domain "$EXISTING_SSL_DOMAIN"; then
        DASHBOARD_URL="https://${EXISTING_SSL_DOMAIN}/"
    elif [[ "$DASHBOARD_URL" == https://* ]]; then
        DASHBOARD_URL="http://${EXISTING_SSL_DOMAIN}/"
    fi
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

#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
    SUDO=sudo
else
    SUDO=""
fi

POOL_USER="${YERB_POOL_USER:-yerbpool}"
WALLET_USER="${YERB_WALLET_USER:-yerbas}"
ADMIN_USER="${YERB_ADMIN_USER:-}"
STRATUM_PORT="${YERB_STRATUM_PORT:-3333}"

log() { printf '[security] %s\n' "$*"; }

require_root_access() {
    if [[ -n "$SUDO" ]]; then
        $SUDO -v
    fi
}

create_system_users() {
    log "Ensuring dedicated non-root service users exist..."

    if ! id "$POOL_USER" >/dev/null 2>&1; then
        $SUDO useradd --system --user-group --home /opt/yerb-pool --shell /usr/sbin/nologin "$POOL_USER"
        log "Created pool service user: $POOL_USER"
    else
        log "Pool service user already exists: $POOL_USER"
    fi

    if ! id "$WALLET_USER" >/dev/null 2>&1; then
        $SUDO useradd --system --user-group --create-home --home-dir /home/yerbas --shell /usr/sbin/nologin "$WALLET_USER"
        log "Created wallet service user: $WALLET_USER"
    else
        log "Wallet service user already exists: $WALLET_USER"
    fi
}

create_admin_user() {
    # A human administrator is optional because an unattended install cannot
    # safely invent a password or SSH key. Set YERB_ADMIN_USER=name before
    # running the installer, or answer the interactive prompt.
    if [[ -z "$ADMIN_USER" && -t 0 ]]; then
        local answer=""
        read -r -p "Create a non-root sudo administrator account now? (y/N): " answer
        if [[ "$answer" =~ ^[Yy]$ ]]; then
            read -r -p "Administrator username: " ADMIN_USER
        fi
    fi

    if [[ -z "$ADMIN_USER" ]]; then
        log "No human administrator requested; skipping admin account creation."
        log "You can later run: adduser USER && usermod -aG sudo USER"
        return 0
    fi

    if [[ ! "$ADMIN_USER" =~ ^[a-z_][a-z0-9_-]*$ ]]; then
        log "WARNING: invalid administrator username '$ADMIN_USER'; skipping."
        return 0
    fi

    if ! id "$ADMIN_USER" >/dev/null 2>&1; then
        log "Creating administrator account: $ADMIN_USER"
        $SUDO adduser "$ADMIN_USER"
    fi
    $SUDO usermod -aG sudo "$ADMIN_USER"
    log "Administrator '$ADMIN_USER' is in the sudo group."

    # If the installer was launched through sudo, copy the invoking user's
    # authorized_keys when useful. Never copy root's key automatically.
    if [[ -n "${SUDO_USER:-}" && "${SUDO_USER}" != "root" && -f "/home/${SUDO_USER}/.ssh/authorized_keys" ]]; then
        if [[ "$ADMIN_USER" != "$SUDO_USER" ]]; then
            $SUDO install -d -m 700 -o "$ADMIN_USER" -g "$ADMIN_USER" "/home/${ADMIN_USER}/.ssh"
            $SUDO cp "/home/${SUDO_USER}/.ssh/authorized_keys" "/home/${ADMIN_USER}/.ssh/authorized_keys"
            $SUDO chown "$ADMIN_USER:$ADMIN_USER" "/home/${ADMIN_USER}/.ssh/authorized_keys"
            $SUDO chmod 600 "/home/${ADMIN_USER}/.ssh/authorized_keys"
            log "Copied SSH authorized_keys from $SUDO_USER to $ADMIN_USER."
        fi
    fi

    log "IMPORTANT: verify SSH key login for '$ADMIN_USER' before disabling root/password SSH."
}

detect_ssh_ports() {
    local ports=""
    if command -v sshd >/dev/null 2>&1; then
        ports="$($SUDO sshd -T 2>/dev/null | awk '$1=="port" {print $2}' | sort -nu | tr '\n' ' ' || true)"
    fi
    if [[ -z "$ports" ]]; then
        ports="22"
    fi
    printf '%s\n' "$ports"
}

configure_ufw() {
    log "Configuring UFW firewall..."
    local ssh_ports
    ssh_ports="$(detect_ssh_ports)"

    $SUDO ufw default deny incoming >/dev/null
    $SUDO ufw default allow outgoing >/dev/null

    for port in $ssh_ports; do
        $SUDO ufw allow "${port}/tcp" comment 'SSH' >/dev/null || true
        log "Allowed SSH TCP port $port"
    done

    $SUDO ufw allow 80/tcp comment 'HTTP' >/dev/null || true
    $SUDO ufw allow 443/tcp comment 'HTTPS' >/dev/null || true
    $SUDO ufw allow "${STRATUM_PORT}/tcp" comment 'YERB Stratum' >/dev/null || true

    # --force avoids the interactive SSH warning only after the SSH allow rule
    # has been installed above.
    $SUDO ufw --force enable >/dev/null
    log "UFW enabled: inbound default deny; SSH, HTTP, HTTPS and Stratum allowed."
}

configure_fail2ban() {
    log "Configuring Fail2Ban..."
    $SUDO mkdir -p /etc/fail2ban/jail.d
    $SUDO tee /etc/fail2ban/jail.d/yerb-pool.local >/dev/null <<'EOF'
[DEFAULT]
bantime = 1h
findtime = 10m
maxretry = 5

[sshd]
enabled = true

[nginx-http-auth]
enabled = true

[nginx-limit-req]
enabled = true
EOF

    $SUDO systemctl enable fail2ban >/dev/null
    $SUDO systemctl restart fail2ban
    log "Fail2Ban enabled for SSH and Nginx authentication/rate-limit events."
}

configure_service_limits() {
    # Keep pool services from falling back to the distribution's low fd limit.
    for service in yerb-pool yerb-pool-web; do
        local dir="/etc/systemd/system/${service}.service.d"
        $SUDO mkdir -p "$dir"
        $SUDO tee "$dir/limits.conf" >/dev/null <<'EOF'
[Service]
LimitNOFILE=65536
EOF
    done
    $SUDO systemctl daemon-reload
    log "Applied LimitNOFILE=65536 to YERB Pool services."
}

install_security_packages() {
    $SUDO apt-get update
    if [[ -n "$SUDO" ]]; then
        $SUDO env DEBIAN_FRONTEND=noninteractive apt-get install -y ufw fail2ban unattended-upgrades sudo
    else
        DEBIAN_FRONTEND=noninteractive apt-get install -y ufw fail2ban unattended-upgrades sudo
    fi
}

main() {
    require_root_access
    log "Installing host security packages..."
    install_security_packages

    create_system_users
    create_admin_user
    configure_service_limits
    configure_ufw
    configure_fail2ban

    log "Security hardening complete."
    log "Wallet RPC and the pool web backend should remain bound to localhost only."
    log "Root SSH is NOT disabled automatically to prevent accidental lockout."
}

main "$@"

#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR=/opt/yerb-pool
SERVICE_USER=yerbpool
NATIVE_SOURCE="$ROOT/native/build/libyerb_ghostrider.so"
NATIVE_DEST="$INSTALL_DIR/native/build/libyerb_ghostrider.so"

if [[ "${EUID}" -ne 0 ]]; then
    SUDO=sudo
else
    SUDO=""
fi

run_as_pool() {
    if [[ -n "$SUDO" ]]; then
        $SUDO -u "$SERVICE_USER" "$@"
    else
        runuser -u "$SERVICE_USER" -- "$@"
    fi
}

verify_native_build() {
    if [[ ! -s "$NATIVE_SOURCE" ]]; then
        echo "ERROR: Native GhostRider build did not produce $NATIVE_SOURCE" >&2
        exit 1
    fi
    if ! file "$NATIVE_SOURCE" | grep -q 'shared object'; then
        echo "ERROR: Native GhostRider output is not a Linux shared object: $NATIVE_SOURCE" >&2
        exit 1
    fi
}

verify_native_install() {
    if [[ ! -s "$NATIVE_DEST" ]]; then
        echo "ERROR: Production GhostRider library is missing: $NATIVE_DEST" >&2
        $SUDO systemctl stop yerb-pool 2>/dev/null || true
        exit 1
    fi

    $SUDO chown "$SERVICE_USER:$SERVICE_USER" "$NATIVE_DEST"
    $SUDO chmod 755 "$NATIVE_DEST"

    echo "Testing production GhostRider library as $SERVICE_USER..."
    if ! run_as_pool env PYTHONPATH="$INSTALL_DIR" /usr/bin/python3 -c \
        'from yerbpool.ghostrider import ensure_available; ensure_available(); print("Native GhostRider load test passed")'; then
        echo "ERROR: $SERVICE_USER cannot load the production GhostRider library." >&2
        $SUDO systemctl stop yerb-pool 2>/dev/null || true
        exit 1
    fi
}

# Always snapshot live accounting/configuration before touching production.
# Fresh installs simply report that there is nothing to back up yet. The
# backup script uses SQLite's online backup API so WAL activity is captured in
# a consistent database snapshot while miners remain connected.
echo "Creating verified pre-update backup..."
bash "$ROOT/scripts/backup-production.sh"

# A fresh pool requires a local Yerbas Core wallet/RPC daemon. This bootstrap
# is idempotent: an existing yerbas user, wallet data directory, yerbas.conf,
# binaries, and configured service are preserved. On a new host it installs
# Core from the latest Yerbas GitHub release, creates secure local-only RPC
# credentials, starts yerbasd, creates a dedicated pool wallet address, and
# writes those values into the pool config before application deployment.
echo "Checking Yerbas Core installation and local RPC configuration..."
bash "$ROOT/scripts/install-yerbas-core.sh"

echo "Pre-building required native GhostRider library..."
bash "$ROOT/scripts/build-native.sh"
verify_native_build

# The application installer explicitly copies native/build/libyerb_ghostrider.so
# into /opt/yerb-pool. Building and validating it first prevents a deployment
# from reaching the service restart stage without the required verifier.
bash "$ROOT/scripts/install.sh" "$@"

verify_native_install

# Restart only after the installed library has passed a real load test under
# the same account that runs the Stratum service.
$SUDO systemctl restart yerb-pool
if ! $SUDO systemctl is-active --quiet yerb-pool; then
    echo "ERROR: yerb-pool did not remain active after deployment." >&2
    $SUDO journalctl -u yerb-pool -n 50 --no-pager >&2 || true
    exit 1
fi

echo "Verified: native GhostRider library is installed, loadable, and yerb-pool is active."

# Apply host-level security after the application is installed so the
# installer can safely allow the actual SSH, HTTP(S), and Stratum ports before
# enabling the default-deny firewall policy.
bash "$ROOT/scripts/security-hardening.sh"

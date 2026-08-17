#!/usr/bin/env bash
set -euo pipefail

INSTALL_DIR="${YERB_POOL_INSTALL_DIR:-/opt/yerb-pool}"
BACKUP_ROOT="${YERB_POOL_BACKUP_DIR:-/var/backups/yerb-pool}"
KEEP_BACKUPS="${YERB_POOL_BACKUP_KEEP:-20}"
SERVICE_USER="${YERB_POOL_USER:-yerbpool}"

if [[ "${EUID}" -ne 0 ]]; then
    SUDO=sudo
else
    SUDO=""
fi

DB_PATH="$INSTALL_DIR/yerbpool.db"
CONFIG_PATH="$INSTALL_DIR/config.json"

# Fresh installs have nothing to preserve yet.
if [[ ! -f "$DB_PATH" && ! -f "$CONFIG_PATH" ]]; then
    echo "No existing production database/configuration found; pre-update backup not required."
    exit 0
fi

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
DEST="$BACKUP_ROOT/$STAMP"

$SUDO install -d -m 700 -o root -g root "$BACKUP_ROOT"
$SUDO install -d -m 700 -o root -g root "$DEST"

echo "Creating pre-update backup: $DEST"

if [[ -f "$DB_PATH" ]]; then
    if ! command -v sqlite3 >/dev/null 2>&1; then
        echo "ERROR: sqlite3 is required to safely back up the live pool database." >&2
        exit 1
    fi

    # SQLite's online backup command creates a consistent snapshot even while
    # the pool is using WAL mode and accepting shares.
    $SUDO sqlite3 "$DB_PATH" ".timeout 10000" ".backup '$DEST/yerbpool.db'"
    $SUDO chmod 600 "$DEST/yerbpool.db"

    # Verify that the snapshot is a readable, internally consistent database.
    integrity="$($SUDO sqlite3 "$DEST/yerbpool.db" 'PRAGMA integrity_check;' 2>&1)"
    if [[ "$integrity" != "ok" ]]; then
        echo "ERROR: database backup integrity check failed: $integrity" >&2
        exit 1
    fi
    echo "  ✓ yerbpool.db (SQLite-consistent snapshot)"
fi

if [[ -f "$CONFIG_PATH" ]]; then
    $SUDO install -m 600 -o root -g root "$CONFIG_PATH" "$DEST/config.json"
    echo "  ✓ config.json"
fi

# Record enough metadata to identify and restore the snapshot later.
{
    echo "created_utc=$STAMP"
    echo "source=$INSTALL_DIR"
    echo "hostname=$(hostname)"
    if [[ -f "$DEST/yerbpool.db" ]]; then
        echo "database_sha256=$(sha256sum "$DEST/yerbpool.db" | awk '{print $1}')"
    fi
    if [[ -f "$DEST/config.json" ]]; then
        echo "config_sha256=$(sha256sum "$DEST/config.json" | awk '{print $1}')"
    fi
} | $SUDO tee "$DEST/MANIFEST" >/dev/null
$SUDO chmod 600 "$DEST/MANIFEST"

# Keep disk use bounded. Backup directories sort chronologically because their
# names are UTC timestamps.
if [[ "$KEEP_BACKUPS" =~ ^[0-9]+$ ]] && (( KEEP_BACKUPS > 0 )); then
    mapfile -t old_backups < <($SUDO find "$BACKUP_ROOT" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' | sort -r | tail -n +$((KEEP_BACKUPS + 1)))
    for old in "${old_backups[@]:-}"; do
        [[ -n "$old" ]] && $SUDO rm -rf -- "$BACKUP_ROOT/$old"
    done
fi

echo "Pre-update backup verified successfully."

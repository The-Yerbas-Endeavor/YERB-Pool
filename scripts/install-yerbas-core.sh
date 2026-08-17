#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CORE_USER=yerbas
CORE_GROUP=yerbas
CORE_HOME=/home/yerbas
CORE_DATADIR="$CORE_HOME/.yerbascore"
CORE_CONF="$CORE_DATADIR/yerbas.conf"
CORE_SERVICE=/etc/systemd/system/yerbasd.service
CORE_BIN=/usr/local/bin/yerbasd
CLI_BIN=/usr/local/bin/yerbas-cli
RPC_PORT=15419
REPO=The-Yerbas-Endeavor/yerbas

if [[ "${EUID}" -ne 0 ]]; then
    SUDO=sudo
else
    SUDO=""
fi

run_as_core() {
    if [[ -n "$SUDO" ]]; then
        $SUDO -u "$CORE_USER" "$@"
    else
        runuser -u "$CORE_USER" -- "$@"
    fi
}

install_dependencies() {
    $SUDO apt-get update
    $SUDO apt-get install -y curl ca-certificates tar gzip openssl python3
}

ensure_core_user() {
    if ! id "$CORE_USER" >/dev/null 2>&1; then
        echo "Creating non-login Yerbas Core service account: $CORE_USER"
        $SUDO useradd --system --create-home --home-dir "$CORE_HOME" --shell /usr/sbin/nologin "$CORE_USER"
    fi
    $SUDO mkdir -p "$CORE_DATADIR"
    $SUDO chown -R "$CORE_USER:$CORE_GROUP" "$CORE_HOME"
    $SUDO chmod 750 "$CORE_HOME"
    $SUDO chmod 700 "$CORE_DATADIR"
}

install_latest_core() {
    if [[ -x "$CORE_BIN" && -x "$CLI_BIN" ]]; then
        echo "Yerbas Core binaries already installed; preserving existing binaries."
        return
    fi

    local os_version arch asset_url tmpdir
    os_version="$(. /etc/os-release; printf '%s' "${VERSION_ID:-}")"
    case "$(uname -m)" in
        x86_64|amd64) arch=x86 ;;
        aarch64|arm64) arch=arm64 ;;
        *) echo "ERROR: Unsupported architecture: $(uname -m)" >&2; exit 1 ;;
    esac

    echo "Finding latest Yerbas Core release for Ubuntu ${os_version} ${arch}..."
    asset_url="$(python3 - "$REPO" "$os_version" "$arch" <<'PY'
import json, sys, urllib.request
repo, os_version, arch = sys.argv[1:]
url = f"https://api.github.com/repos/{repo}/releases/latest"
req = urllib.request.Request(url, headers={"Accept":"application/vnd.github+json","User-Agent":"YERB-Pool-Installer"})
with urllib.request.urlopen(req, timeout=30) as r:
    release = json.load(r)
assets = release.get("assets", [])
needle = f"yerbas-ubuntu-{os_version}-{arch}-release-"
for asset in assets:
    name = asset.get("name", "")
    if name.startswith(needle) and name.endswith(".tar.gz"):
        print(asset["browser_download_url"])
        raise SystemExit(0)
# Prefer the newest Ubuntu x86/arm64 release artifact if this exact Ubuntu
# version has no prebuilt package. This is deliberately a fallback only.
candidates=[]
for asset in assets:
    name=asset.get("name","")
    if name.startswith("yerbas-ubuntu-") and f"-{arch}-release-" in name and name.endswith(".tar.gz"):
        candidates.append(asset)
if candidates:
    print(candidates[-1]["browser_download_url"])
    raise SystemExit(0)
raise SystemExit(1)
PY
)" || {
        echo "ERROR: No compatible Yerbas Core binary asset found in the latest release." >&2
        exit 1
    }

    tmpdir="$(mktemp -d)"
    trap 'rm -rf "$tmpdir"' RETURN
    echo "Downloading Yerbas Core..."
    curl -fL --retry 3 --connect-timeout 15 "$asset_url" -o "$tmpdir/yerbas-core.tar.gz"
    tar -xzf "$tmpdir/yerbas-core.tar.gz" -C "$tmpdir"

    local daemon cli
    daemon="$(find "$tmpdir" -type f -name yerbasd -perm -u+x | head -1)"
    cli="$(find "$tmpdir" -type f -name yerbas-cli -perm -u+x | head -1)"
    if [[ -z "$daemon" || -z "$cli" ]]; then
        echo "ERROR: Release archive did not contain yerbasd and yerbas-cli." >&2
        exit 1
    fi

    $SUDO install -m 0755 "$daemon" "$CORE_BIN"
    $SUDO install -m 0755 "$cli" "$CLI_BIN"
    echo "Installed Yerbas Core binaries in /usr/local/bin."
}

ensure_core_conf() {
    if [[ -f "$CORE_CONF" ]]; then
        echo "Existing $CORE_CONF detected; preserving it."
        return
    fi

    local rpc_user rpc_password
    rpc_user="yerbpool_rpc"
    rpc_password="$(openssl rand -hex 32)"

    echo "Creating secure $CORE_CONF..."
    $SUDO tee "$CORE_CONF" >/dev/null <<EOF
server=1
daemon=1
rpcuser=${rpc_user}
rpcpassword=${rpc_password}
rpcbind=127.0.0.1
rpcallowip=127.0.0.1
rpcport=${RPC_PORT}
listen=1
EOF
    $SUDO chown "$CORE_USER:$CORE_GROUP" "$CORE_CONF"
    $SUDO chmod 600 "$CORE_CONF"
}

ensure_service() {
    if [[ ! -f "$CORE_SERVICE" ]]; then
        echo "Installing yerbasd.service..."
        $SUDO tee "$CORE_SERVICE" >/dev/null <<'EOF'
[Unit]
Description=Yerbas Core Daemon
After=network-online.target
Wants=network-online.target

[Service]
Type=forking
User=yerbas
Group=yerbas
ExecStart=/usr/local/bin/yerbasd -daemon -datadir=/home/yerbas/.yerbascore
ExecStop=/usr/local/bin/yerbas-cli -datadir=/home/yerbas/.yerbascore stop
Restart=on-failure
RestartSec=10
LimitNOFILE=65536
PrivateTmp=true
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
EOF
    fi
    $SUDO systemctl daemon-reload
    $SUDO systemctl enable yerbasd
    $SUDO systemctl restart yerbasd
}

read_conf_value() {
    local key="$1"
    $SUDO awk -F= -v k="$key" '$1==k {sub(/^[^=]*=/,""); print; exit}' "$CORE_CONF"
}

wait_for_rpc() {
    echo "Waiting for Yerbas Core RPC..."
    local i
    for i in $(seq 1 60); do
        if run_as_core "$CLI_BIN" -datadir="$CORE_DATADIR" getblockchaininfo >/dev/null 2>&1; then
            echo "Yerbas Core RPC is ready."
            return 0
        fi
        sleep 2
    done
    echo "ERROR: Yerbas Core RPC did not become ready within 120 seconds." >&2
    $SUDO journalctl -u yerbasd -n 60 --no-pager >&2 || true
    exit 1
}

configure_pool_rpc() {
    local rpc_user rpc_password rpc_port pool_address=""
    rpc_user="$(read_conf_value rpcuser)"
    rpc_password="$(read_conf_value rpcpassword)"
    rpc_port="$(read_conf_value rpcport)"
    rpc_port="${rpc_port:-15419}"

    if [[ -z "$rpc_user" || -z "$rpc_password" ]]; then
        echo "ERROR: Existing yerbas.conf does not contain rpcuser/rpcpassword." >&2
        echo "Add local RPC credentials to $CORE_CONF and rerun the installer." >&2
        exit 1
    fi

    if [[ -f "$ROOT/config.json" ]]; then
        pool_address="$(python3 - "$ROOT/config.json" <<'PY'
import json,sys
try:
    v=json.load(open(sys.argv[1])).get("pool_address","")
    if v and not str(v).startswith("CHANGE_ME"):
        print(v)
except Exception:
    pass
PY
)"
    fi

    if [[ -z "$pool_address" ]]; then
        pool_address="$(run_as_core "$CLI_BIN" -datadir="$CORE_DATADIR" getnewaddress "YERB Pool" 2>/dev/null || run_as_core "$CLI_BIN" -datadir="$CORE_DATADIR" getnewaddress)"
        echo "Created a dedicated pool wallet address."
    fi

    if [[ ! -f "$ROOT/config.json" ]]; then
        cp "$ROOT/config.example.json" "$ROOT/config.json"
    fi

    python3 - "$ROOT/config.json" "$rpc_user" "$rpc_password" "$rpc_port" "$pool_address" <<'PY'
import json,sys
from pathlib import Path
p=Path(sys.argv[1])
cfg=json.loads(p.read_text())
rpc=cfg.setdefault("rpc",{})
rpc["url"]=f"http://127.0.0.1:{sys.argv[4]}"
rpc["user"]=sys.argv[2]
rpc["password"]=sys.argv[3]
cfg["pool_address"]=sys.argv[5]
p.write_text(json.dumps(cfg,indent=2)+"\n")
PY
    chmod 600 "$ROOT/config.json"
    echo "Configured YERB-Pool for local Yerbas Core RPC."
}

install_dependencies
ensure_core_user
install_latest_core
ensure_core_conf
ensure_service
wait_for_rpc
configure_pool_rpc

echo "Yerbas Core bootstrap complete."
echo "  Service: yerbasd.service"
echo "  User:    $CORE_USER (nologin)"
echo "  Data:    $CORE_DATADIR"
echo "  RPC:     127.0.0.1:${RPC_PORT}"

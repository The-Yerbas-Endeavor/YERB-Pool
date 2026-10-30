#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
[[ $EUID -eq 0 ]] || { echo 'Run with sudo.'; exit 1; }
exec 9>/run/lock/yerbas-core-upgrade.lock
flock -n 9 || { echo 'Another upgrade is running.'; exit 1; }
stage=$(cd -- "$(dirname -- "$0")" && pwd)
archive="$stage/release.tar.gz"
expected=2c10b56c1f0e14a236fb37e3eaf0e74e2097686a452a3542f1a3c69b529539ca
printf '%s  %s\n' "$expected" "$archive" | sha256sum -c -
data=/home/yerbas/.yerbascore
conf="$data/yerbas.conf"
[[ -f "$conf" && ! -L "$conf" ]]
systemctl is-active --quiet yerbasd
systemctl is-active --quiet yerb-pool
[[ $(readlink -f /usr/local/bin/yerbasd) == /usr/local/bin/yerbasd ]]
/usr/local/bin/yerbasd --version | head -1 | grep -F 'v3.2.0.21'
cli() { runuser -u yerbas -- timeout 60 /usr/local/bin/yerbas-cli -datadir="$data" "$@"; }
cli getblockchaininfo >/dev/null
stamp=$(date -u +%Y%m%dT%H%M%SZ)
backup="/var/backups/yerb-pool/core-4.0.1.2-$stamp"
install -d -m 700 "$backup"
cli getblockchaininfo >"$backup/blockchain-before.json"
cli getwalletinfo >"$backup/wallet-before.json"
sha256sum "$conf" >"$backup/config.sha256"
cp -a "$conf" "$backup/yerbas.conf"
cp -a /usr/local/bin/yerbasd /usr/local/bin/yerbas-cli "$backup/"
systemctl cat yerbasd >"$backup/yerbasd.service.txt"
size=$(du -sb "$data" | awk '{print $1}')
free=$(df -PB1 "$backup" | awk 'NR==2 {print $4}')
((free > size + 2147483648)) || { echo 'Insufficient space for complete offline data backup plus 2 GiB reserve. Nothing stopped.'; exit 1; }
release="$backup/release"
mkdir "$release"
tar -xzf "$archive" -C "$release" --no-same-owner
"$release/bin/yerbasd" --version | head -1 | grep -F 'v4.0.1.2-63b09cd'
"$release/bin/yerbas-cli" --version | head -1 | grep -F 'v4.0.1.2'
walletdir=/home/yerbas/core-upgrade-backups
install -d -o yerbas -g yerbas -m 700 "$walletdir"
cli backupwallet "$walletdir/wallet-$stamp.dat" >/dev/null
cp -a "$walletdir/wallet-$stamp.dat" "$backup/wallet.dat"
echo "Wallet backup saved. Full offline backup: $backup"
maintenance=0
on_error() {
  rc=$?
  echo "Upgrade stopped (status $rc). Backup: $backup"
  if [[ $maintenance == 1 ]]; then
    echo 'Pool remains stopped. Do not start the old daemon against upgraded data. Inspect the error before recovery.'
  fi
  exit "$rc"
}
trap on_error ERR
maintenance=1
systemctl stop yerb-pool
systemctl stop yerbasd
! pgrep -x yerbasd >/dev/null
sha256sum -c "$backup/config.sha256"
tar --sparse -cpf "$backup/core-data.tar" -C /home/yerbas .yerbascore
tar -df "$backup/core-data.tar" -C /home/yerbas
sha256sum "$backup/core-data.tar" >"$backup/core-data.tar.sha256"
for name in yerbasd yerbas-cli; do
  install -o root -g root -m 755 "$release/bin/$name" "/usr/local/bin/$name.new-4.0.1.2"
  cmp "$release/bin/$name" "/usr/local/bin/$name.new-4.0.1.2"
done
mv -f /usr/local/bin/yerbas-cli.new-4.0.1.2 /usr/local/bin/yerbas-cli
mv -f /usr/local/bin/yerbasd.new-4.0.1.2 /usr/local/bin/yerbasd
sha256sum -c "$backup/config.sha256"
systemctl start yerbasd
echo '4.0.1.2 started; waiting up to 10 minutes for RPC, peers, and synchronization.'
ready=0
for i in $(seq 1 120); do
  if cli getblockchaininfo >"$backup/blockchain-after.json" 2>/dev/null && cli getnetworkinfo >"$backup/network-after.json" 2>/dev/null; then
    if python3 - "$backup" <<'PY'
import json,sys,pathlib
p=pathlib.Path(sys.argv[1]); before=json.loads((p/'blockchain-before.json').read_text()); after=json.loads((p/'blockchain-after.json').read_text()); net=json.loads((p/'network-after.json').read_text())
sys.exit(0 if net.get('version')==4000102 and net.get('connections',0)>0 and not after.get('initialblockdownload',True) and after['blocks']>=before['blocks'] and after.get('headers',after['blocks'])-after['blocks']<=2 else 1)
PY
    then ready=1; break; fi
  fi
  sleep 5
done
[[ $ready == 1 ]] || { echo 'Node not ready yet. Pool kept stopped; inspect Core before resuming.'; false; }
cli getwalletinfo >"$backup/wallet-after.json"
sha256sum -c "$backup/config.sha256"
systemctl start yerb-pool
systemctl is-active --quiet yerbasd
systemctl is-active --quiet yerb-pool
maintenance=0
/usr/local/bin/yerbasd --version | head -1
cli getblockcount
printf 'Upgrade complete. Core and pool are active. Protected backup: %s\n' "$backup"
echo 'Configuration is byte-for-byte unchanged. Wallet and full pre-upgrade data backup retained.'

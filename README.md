# YERB Pool

A standalone [Yerbas](https://github.com/The-Yerbas-Endeavor) (YERB) mining pool for the GhostRider algorithm. Includes Stratum, proportional rewards, automated payouts, and a web dashboard with miner, worker, block, and payout history.

**[Live dashboard](https://pool.yerbas.org/)** · **[Mining setup and downloads](https://pool.yerbas.org/configure)** · **[API documentation](https://pool.yerbas.org/api/help)**

## Connect a miner

Pool address: `stratum+tcp://pool.yerbas.org:3333`

Use your YERB payout address as the username, with an optional `.worker` suffix. Password: `x`.

With [Yerbas Miner](https://github.com/The-Yerbas-Endeavor/Yerbas-Miner/releases/latest):

```bash
yerbas-miner --pool stratum+tcp://pool.yerbas.org:3333 \
  --user YOUR_YERB_ADDRESS --worker yerbas --password x
```

The dashboard and Configure page provide commands and download links for supported miners.

## Install on Ubuntu

Requires sudo access and a host that can accept mining connections on TCP port `3333`.

```bash
sudo apt update
sudo apt install -y build-essential cmake git python3 sqlite3 libboost-dev nginx rsync

git clone https://github.com/The-Yerbas-Endeavor/YERB-Pool.git
cd YERB-Pool
bash install.sh
```

The installer backs up an existing installation, sets up Yerbas Core and local RPC, builds the native GhostRider verifier, and installs the pool under `/opt/yerb-pool`. It also installs systemd services and applies host security settings, including firewall rules.

## Configuration and payouts

See [config.example.json](config.example.json) for available settings. The installed configuration is `/opt/yerb-pool/config.json`; keep RPC credentials private.

Payout defaults are a **1 YERB minimum**, a **2-hour payout interval**, and **100 confirmations** before rewards mature. Block maturity is checked every 60 seconds. Eligible miners are paid together in a wallet transaction. Pool fees are adjustable through the admin settings and credited to the pool treasury.

## Service management

- Mining service: `yerb-pool` → `pool.py`
- Web/admin service: `yerb-pool-web` → `web_preloaded.py`

```bash
systemctl status yerb-pool yerb-pool-web --no-pager
journalctl -u yerb-pool -n 50 --no-pager
journalctl -u yerb-pool-web -n 50 --no-pager
```

After changing web code, restart the web service:

```bash
sudo systemctl restart yerb-pool-web
```

## Health and accounting

Public monitoring endpoints:

- `/api/summary` — pool statistics
- `/api/health` — Stratum, wallet, database, and accounting health
- `/api/accounting-integrity` — accounting reconciliation
- `/api/pools` — Miningcore-compatible pool discovery

See [API documentation](https://pool.yerbas.org/api/help) for versioned, paginated endpoints and miner/worker history.

Check a deployed pool:

```bash
curl -s https://pool.yerbas.org/api/health | python3 -m json.tool
cd /opt/yerb-pool
sudo -u yerbpool python3 scripts/check-accounting.py
```

Healthy reconciliation reports `ok: true` and zero differences. Investigate discrepancies before changing balances.

## Development

From the repository root:

```bash
python3 -m unittest discover -s tests
node tests/test_dashboard_loading.cjs
```

Node.js is needed only for the JavaScript loading test. Live configuration, databases, logs, and native build output are excluded from Git.

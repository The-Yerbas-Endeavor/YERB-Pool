# YERB Pool

> Multi-coin administration is under development on the dedicated feature branch. The Admin
> panel can create validated coin drafts and preview isolated domains, ports, folders,
> databases, services, nginx sites, DNS, and firewall requirements without modifying the
> production YERB instance. Privileged activation remains a separate explicit operator step.

A standalone Yerbas (YERB) GhostRider mining pool with Stratum, proportional block accounting, automated batched payouts, an admin treasury, and a live web dashboard.

## Production baseline

`main` is intended to remain a deployable working baseline. Changes should preserve the existing mining, payout, accounting, admin, and diagnostics paths unless a change explicitly targets one of them.

Current production features include:

- Yerbas `getblocktemplate` polling and block submission
- Standard Stratum TCP on port `3333`
- `mining.subscribe`, `mining.authorize`, `mining.notify`, and `mining.submit`
- Native GhostRider share verification built from a pinned Yerbas Core revision
- Variable difficulty with a 12-second target share time
- SQLite miner, worker, share, block, ledger, and payout accounting
- Proportional round rewards
- Coinbase maturity tracking
- Adjustable pool fee
- Internal pool treasury address and admin withdrawal controls
- Combined `sendmany` miner payout batches every 2 hours
- 60-second block maturity checks
- Public miner/account pages and address search
- Pool, worker, block, payout, and accounting APIs
- Read-only health and accounting-integrity diagnostics
- Web/admin dashboard served through `web_enhanced.py`

## Architecture

```text
GhostRider miner
      |
Stratum :3333
      |
   pool.py
      |
+-----+--------------------+
|                          |
SQLite                 Yerbas RPC
|                          |
Accounting             yerbasd
Payouts
Treasury

Web stack:
web.py -> web_stats.py -> web_admin.py -> web_enhanced.py
```

The layered web stack is intentional in the current production baseline. Do not remove one of these files without first consolidating and testing the behavior inherited from it.

## Ubuntu installation

```bash
sudo apt update
sudo apt install -y build-essential cmake git python3 sqlite3 libboost-dev nginx rsync

git clone https://github.com/The-Yerbas-Endeavor/YERB-Pool.git
cd YERB-Pool
bash install.sh
```

The installer builds the native GhostRider verifier, installs the pool under `/opt/yerb-pool`, initializes/upgrades the database, installs the systemd units, preserves an existing Nginx configuration, and restarts the pool services.

## Configuration

Start from `config.example.json` for a manual installation. Production installs keep their live configuration at:

```text
/opt/yerb-pool/config.json
```

Important defaults:

```json
{
  "stratum": {
    "host": "0.0.0.0",
    "port": 3333,
    "difficulty": 0.05,
    "vardiff": {
      "enabled": true,
      "min_difficulty": 0.05,
      "max_difficulty": 65536.0,
      "target_share_seconds": 12,
      "retarget_seconds": 60
    }
  },
  "payouts": {
    "enabled": true,
    "coinbase_maturity": 100,
    "block_check_interval_seconds": 60,
    "check_interval_seconds": 7200,
    "minimum_payout": "1.00000000",
    "pool_fee_percent": 0.0
  }
}
```

The adjustable pool fee is persisted by the pool's runtime settings. Future pool-fee allocations are credited to the internally managed treasury address.

## Services

```bash
systemctl status yerb-pool --no-pager
systemctl status yerb-pool-web --no-pager
```

Production entrypoints:

```text
Mining/Stratum: /opt/yerb-pool/pool.py
Web/Admin:      /opt/yerb-pool/web_enhanced.py
```

Useful logs:

```bash
journalctl -u yerb-pool -n 50 --no-pager
journalctl -u yerb-pool-web -n 50 --no-pager
```

## Miner connection

```text
stratum+tcp://pool.yerbas.org:3333
```

Username format:

```text
YOUR_YERB_ADDRESS.worker
```

Example:

```bash
cpuminer-opt-gr -a gr \
  -o stratum+tcp://pool.yerbas.org:3333 \
  -u YOUR_YERB_ADDRESS.cpu \
  -p x
```

The dashboard provides prebuilt commands for supported miners.

## Payouts

The payout manager deliberately separates block maintenance from miner payments:

- block confirmation/maturity checks: every 60 seconds
- eligible payout checks: every 7200 seconds (2 hours)
- eligible miners in each payout cycle are combined into one wallet `sendmany` transaction
- restarting the service does not intentionally trigger an immediate scheduled payout

The configured minimum payout remains enforced before an account is included in a batch.

## Pool treasury

The pool wallet creates and owns a dedicated treasury address. Pool fees are credited to that account through normal immature/mature accounting. The admin panel can display the treasury balance and broadcast authenticated withdrawals without storing the private key in the web application.

## Diagnostics

Public/read-only diagnostics:

```text
/api/summary
/api/pool
/api/health
/api/accounting-integrity
```

Public API discovery and versioned endpoints:

```text
/api
/api/help
/api/meta
/api/v1/summary
/api/v1/health
/api/v1/blocks?limit=100&offset=0
/api/v1/payouts?limit=100&offset=0
/api/v1/miners?limit=100&offset=0
/api/v1/workers?limit=100&offset=0
/api/v1/shares?status=accepted&limit=100&offset=0
```

The legacy list endpoints continue returning bare arrays for dashboard
compatibility. The `/api/v1` list endpoints return `items`, `pagination`, and
`generated_at`. Exact coin values are retained as atomic integers and are also
provided as eight-decimal strings where applicable.

Miner-specific API routes:

```text
/api/account/{address}/summary
/api/account/{address}/payments
/api/account/{address}/earnings/daily?days=30
/api/account/{address}/balance-changes
/api/account/{address}/blocks
/api/account/{address}/performance?hours=24&bucket=600
/api/worker/{id}/performance?hours=24&bucket=600
/api/worker/{id}/detail?hours=24&bucket=600&share_limit=25
/api/payouts/{id}
```

Worker detail responses combine identity and live hashrate data with range
averages, recent shares, rejection reasons, and blocks attributed to that
worker. The public worker page renders these diagnostics around the existing
performance chart.

The public Payouts page uses server-side pagination and can browse the complete
payout history. Individual payout-detail responses include the complete
recipient list for that batch.

Local accounting reconciliation:

```bash
cd /opt/yerb-pool
sudo -u yerbpool python3 scripts/check-accounting.py
```

A healthy result reports:

```json
{
  "ok": true,
  "difference": {
    "mature_atomic": 0,
    "immature_atomic": 0,
    "earned_atomic": 0,
    "paid_atomic": 0
  }
}
```

Do not manually alter miner balances to repair a failed integrity check. Diagnose the ledger/accounting discrepancy first.

## Native GhostRider verifier

Build manually with:

```bash
./scripts/build-native.sh
```

The native verifier is compiled directly from a pinned Yerbas Core revision. The pool refuses to start when the verifier is unavailable and never credits unverified shares.

## Repository hygiene

Runtime databases, live configuration, Python caches, native build products, logs, crash dumps, editor metadata, and temporary files are intentionally excluded by `.gitignore`.

Keep `main` focused on source, tests, production configuration examples, installer/service definitions, and documentation. Experimental rewrites should be developed on a separate branch and merged only after the production health and accounting checks pass.

## Baseline verification before and after changes

```bash
python3 -m py_compile \
  pool.py \
  web.py \
  web_stats.py \
  web_admin.py \
  web_enhanced.py \
  yerbpool/*.py \
  scripts/check-accounting.py
```

After deployment:

```bash
curl -s https://pool.yerbas.org/api/health | python3 -m json.tool
cd /opt/yerb-pool
sudo -u yerbpool python3 scripts/check-accounting.py
```

For the production baseline, both should report healthy accounting before further development continues.

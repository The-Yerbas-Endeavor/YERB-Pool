# YERB Pool

A deliberately small Yerbas (YERB) mining pool implementation.

## Goals

- Yerbas `getblocktemplate` / `submitblock` integration
- Stratum TCP endpoint for GhostRider miners
- Wallet-address-as-username authentication
- SQLite share accounting
- Minimal dependencies and easy deployment

## Status

The initial pool scaffold includes the RPC client, Stratum listener, live block-template refresh, SQLite share storage, configuration loader, and systemd unit.

**GhostRider share validation is fail-closed right now.** `yerbpool/ghostrider.py` is the dedicated adapter for the native GhostRider hash implementation. Until that backend and full coinbase/merkle/header reconstruction are wired, submitted shares are rejected rather than falsely credited.

## Miner format

```bash
cpuminer -a gr \
  -o stratum+tcp://POOL_HOST:3333 \
  -u YOUR_YERB_ADDRESS.worker1 \
  -p x
```

## Quick start

```bash
git clone https://github.com/The-Yerbas-Endeavor/YERB-Pool.git
cd YERB-Pool
cp config.example.json config.json
# Edit RPC credentials and pool payout address.
python3 pool.py
```

## Yerbas daemon

Keep RPC bound to localhost unless you intentionally secure remote access.

```ini
server=1
rpcuser=CHANGE_ME
rpcpassword=CHANGE_ME_TOO
rpcbind=127.0.0.1
rpcallowip=127.0.0.1
```

## Layout

```text
pool.py
config.example.json
yerbpool/
  config.py
  rpc.py
  database.py
  ghostrider.py
  jobs.py
  stratum.py
systemd/
  yerb-pool.service
```

## Next implementation milestone

1. Build valid Yerbas coinbase transactions from `getblocktemplate`.
2. Construct merkle branches and standard Stratum `mining.notify` jobs.
3. Bind a verified GhostRider implementation for server-side share hashing.
4. Reconstruct submitted headers and compare against share/network targets.
5. Serialize and submit valid block candidates through `submitblock`.
6. Add proportional payout accounting after block maturity.

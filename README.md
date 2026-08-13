# YERB Pool

A deliberately small standalone Yerbas (YERB) GhostRider mining pool.

## What works

- Yerbas `getblocktemplate` polling
- Standard Stratum TCP on port `3333`
- `mining.subscribe`, `mining.authorize`, `mining.notify`, and `mining.submit`
- Real GhostRider server-side share verification
- Native GhostRider verifier built directly from pinned Yerbas Core sources
- Yerbas DIP0003 CbTx coinbase construction
- Required Smartnode, superblock, and founder payments from `getblocktemplate`
- Coinbase extranonce1/extranonce2
- Coinbase merkle branch construction
- Exact 80-byte miner header reconstruction
- Pool share target and network target checks
- Full block serialization and `submitblock`
- SQLite accepted/rejected share accounting
- Immediate template refresh after an accepted block

## Architecture

```text
GhostRider Stratum miner
        |
     Stratum :3333
        |
   YERB-Pool (Python)
     |          |
 SQLite      libyerb_ghostrider
                |
          Yerbas Core GR
        |
   yerbasd JSON-RPC
```

YERB-Pool does not depend on any miner repository. The native verifier is compiled directly from a pinned revision of `The-Yerbas-Endeavor/yerbas`, so consensus hashing comes from Yerbas Core itself.

## Ubuntu quick start

```bash
sudo apt update
sudo apt install -y build-essential cmake git python3

git clone https://github.com/The-Yerbas-Endeavor/YERB-Pool.git
cd YERB-Pool

./scripts/build-native.sh
cp config.example.json config.json
nano config.json

python3 pool.py
```

The first native build fetches the pinned Yerbas Core GhostRider sources.

## Configuration

```json
{
  "rpc": {
    "url": "http://127.0.0.1:15419",
    "user": "CHANGE_ME",
    "password": "CHANGE_ME"
  },
  "stratum": {
    "host": "0.0.0.0",
    "port": 3333,
    "difficulty": 0.00001
  },
  "database": "yerbpool.db",
  "pool_address": "YOUR_YERB_ADDRESS",
  "template_refresh_seconds": 5,
  "log_level": "INFO"
}
```

`pool_address` receives the miner portion of the coinbase reward. Required Smartnode, superblock, and founder outputs are copied from the live Yerbas block template.

## Yerbas daemon

Keep RPC on localhost unless you intentionally secure remote access.

```ini
server=1
rpcuser=CHANGE_ME
rpcpassword=CHANGE_ME_TOO
rpcbind=127.0.0.1
rpcallowip=127.0.0.1
```

The daemon must be fully synced and connected to peers before `getblocktemplate` will return work.

## Miner connection

Use any compatible GhostRider Stratum miner with a wallet/worker username:

```bash
cpuminer -a gr \
  -o stratum+tcp://POOL_HOST:3333 \
  -u YOUR_YERB_ADDRESS.rig1 \
  -p x
```

## GhostRider native library

Build it with:

```bash
./scripts/build-native.sh
```

The Python adapter searches these locations automatically:

```text
native/build/libyerb_ghostrider.so
native/build/libyerb_ghostrider.dylib
native/build/Release/yerb_ghostrider.dll
```

You can override the location:

```bash
export YERB_GHOSTRIDER_LIB=/path/to/libyerb_ghostrider.so
```

The pool refuses to start if the native GhostRider verifier is unavailable. It never credits unverified shares.

## Coinbase details

Yerbas mainnet has DIP0003 active. The pool builds transaction version `3`, type `TRANSACTION_COINBASE (5)`, preserves the `coinbase_payload` returned by `getblocktemplate`, and uses the coinbase scriptSig for `OP_RETURN + extranonce1 + extranonce2`.

Output order follows Yerbas Core block construction:

1. pool/miner reward
2. Smartnode payments
3. superblock payments
4. founder payment

The pool reward is `coinbasevalue` minus all required template outputs.

## Block submission

For every submitted share the pool:

1. rebuilds the exact coinbase from the session extranonces
2. computes the coinbase transaction hash
3. walks the template merkle branch
4. serializes the exact 80-byte Yerbas header
5. hashes it with GhostRider
6. compares the hash with the configured share target
7. compares it with the template network target
8. if it meets the network target, serializes the whole block and calls `submitblock`

BIP22 success from `submitblock` is JSON `null`.

## Current scope

This is intentionally a simple pool. It does not yet automate mature-block payouts. Shares and block candidates are recorded in SQLite so proportional payout accounting can be added without changing the mining protocol.

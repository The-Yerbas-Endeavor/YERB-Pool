#!/usr/bin/env python3
"""YERB Pool dashboard runtime with live production metrics.

This keeps the existing web.py routes/UI intact while overriding the summary,
worker activity, luck/hashrate, pool history, and share API calculations with
values derived directly from the live production database and Yerbas wallet RPC.
"""
import contextlib
import mimetypes
import sqlite3
import time
from http.server import ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import web as base


COIN = 100_000_000
ACTIVE_WINDOW = 600
HASHRATE_WINDOW = 600


@contextlib.contextmanager
def _closed_db():
    """Open the pool SQLite database and always close it after the request."""
    con = sqlite3.connect(base.DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        yield con
    finally:
        con.close()


base.db = _closed_db


def _wallet_balance_atomic():
    try:
        info = base.rpc_call("getwalletinfo")
        if isinstance(info, dict) and info.get("balance") is not None:
            return int(round(float(info["balance"]) * COIN))
    except Exception:
        pass
    try:
        value = base.rpc_call("getbalance")
        if value is not None:
            return int(round(float(value) * COIN))
    except Exception:
        pass
    return None


def api_summary():
    now = int(time.time())
    cutoff = now - ACTIVE_WINDOW
    with base.db() as con:
        accounts = base.one(
            con,
            "SELECT COUNT(*) accounts, COALESCE(SUM(balance_atomic),0) balance_atomic, "
            "COALESCE(SUM(immature_balance_atomic),0) immature_atomic FROM accounts",
        )
        shares = base.one(
            con,
            "SELECT COUNT(*) shares, "
            "COALESCE(SUM(CASE WHEN accepted=1 THEN 1 ELSE 0 END),0) accepted, "
            "COALESCE(SUM(CASE WHEN accepted=0 THEN 1 ELSE 0 END),0) rejected FROM shares",
        )
        workers = base.one(
            con,
            """SELECT (SELECT COUNT(*) FROM workers) workers,
                      COUNT(DISTINCT s.worker_id) active_workers
               FROM shares s
               WHERE s.accepted=1 AND s.worker_id IS NOT NULL AND s.ts>=?""",
            (cutoff,),
        )
        blocks = base.one(
            con,
            "SELECT COUNT(*) blocks, "
            "COALESCE(SUM(CASE WHEN status='mature' THEN 1 ELSE 0 END),0) mature, "
            "COALESCE(SUM(CASE WHEN status IN ('submitted','confirmed') THEN 1 ELSE 0 END),0) pending FROM blocks",
        )
        payouts = base.one(
            con,
            "SELECT COUNT(*) payouts, "
            "COALESCE(SUM(CASE WHEN status='sent' THEN total_atomic ELSE 0 END),0) paid_atomic FROM payouts",
        )

    accounts["miner_balance_atomic"] = int(accounts.get("balance_atomic") or 0)
    wallet_atomic = _wallet_balance_atomic()
    if wallet_atomic is not None:
        accounts["balance_atomic"] = wallet_atomic
        accounts["wallet_rpc_ok"] = True
    else:
        accounts["wallet_rpc_ok"] = False

    return {"accounts": accounts, "shares": shares, "workers": workers, "blocks": blocks, "payouts": payouts}


def api_workers(limit=500):
    now = int(time.time())
    cutoff = now - ACTIVE_WINDOW
    limit = min(max(int(limit), 1), 1000)
    with base.db() as con:
        result = base.rows(
            con,
            """SELECT w.id,a.address,w.name,w.created_at,w.last_seen_at,
                      w.accepted_shares,w.rejected_shares,
                      COALESCE(SUM(CASE WHEN s.accepted=1 AND s.ts>=? THEN s.difficulty ELSE 0 END),0) recent_diff,
                      COALESCE(MAX(CASE WHEN s.accepted=1 THEN s.ts ELSE NULL END),0) last_share_at
               FROM workers w
               JOIN accounts a ON a.id=w.account_id
               LEFT JOIN shares s ON s.worker_id=w.id
               GROUP BY w.id
               ORDER BY MAX(w.last_seen_at, COALESCE(MAX(s.ts),0)) DESC
               LIMIT ?""",
            (cutoff, limit),
        )

    for item in result:
        recent_diff = float(item.get("recent_diff") or 0)
        item["hashrate"] = (
            (recent_diff / base.GHOSTRIDER_TARGET_FACTOR)
            * base.DIFF1_HASHES
            / HASHRATE_WINDOW
        )
        last_activity = max(
            int(item.get("last_seen_at") or 0),
            int(item.get("last_share_at") or 0),
        )
        item["active"] = last_activity >= cutoff
    return result


def api_pool_history(hours=24, bucket_seconds=300):
    """Pool-wide share/hashrate history independent of current worker status."""
    hours = min(max(int(hours), 1), 168)
    bucket_seconds = min(max(int(bucket_seconds), 60), 3600)
    now = int(time.time())
    end = (now // bucket_seconds) * bucket_seconds
    start = end - hours * 3600

    with base.db() as con:
        raw = base.rows(
            con,
            """SELECT (ts / ?) * ? bucket,
                      COALESCE(SUM(CASE WHEN accepted=1 THEN difficulty ELSE 0 END),0) accepted_diff,
                      COALESCE(SUM(CASE WHEN accepted=1 THEN 1 ELSE 0 END),0) accepted,
                      COALESCE(SUM(CASE WHEN accepted=0 THEN 1 ELSE 0 END),0) rejected
               FROM shares
               WHERE ts>=? AND ts<?
               GROUP BY bucket
               ORDER BY bucket""",
            (bucket_seconds, bucket_seconds, start, end + bucket_seconds),
        )

    by_bucket = {int(r["bucket"]): r for r in raw}
    history = []
    t = start
    while t <= end:
        row = by_bucket.get(t, {})
        accepted_diff = float(row.get("accepted_diff") or 0)
        history.append({
            "ts": t,
            "hashrate": (
                accepted_diff / base.GHOSTRIDER_TARGET_FACTOR
            ) * base.DIFF1_HASHES / bucket_seconds,
            "accepted": int(row.get("accepted") or 0),
            "rejected": int(row.get("rejected") or 0),
        })
        t += bucket_seconds
    return history


def _recent_pool_hashrate():
    """Return a resilient 10-minute hashrate estimate from accepted shares."""
    now = int(time.time())
    cutoff = now - HASHRATE_WINDOW
    with base.db() as con:
        recent = base.one(
            con,
            "SELECT COALESCE(SUM(difficulty),0) accepted_diff FROM shares WHERE accepted=1 AND ts>=?",
            (cutoff,),
        )
    recent_diff = float(recent.get("accepted_diff") or 0)
    return (
        (recent_diff / base.GHOSTRIDER_TARGET_FACTOR)
        * base.DIFF1_HASHES
        / HASHRATE_WINDOW
    )


def api_luck():
    now = int(time.time())
    pool_hashrate = _recent_pool_hashrate()
    with base.db() as con:
        last_block = base.one(con, "SELECT height,submitted_at FROM blocks ORDER BY id DESC LIMIT 1")
        if last_block and last_block.get("submitted_at"):
            round_start = int(last_block["submitted_at"])
        else:
            first = base.one(con, "SELECT MIN(ts) first_ts FROM shares WHERE accepted=1")
            round_start = int(first.get("first_ts") or now)
        round_stats = base.one(
            con,
            "SELECT COUNT(*) accepted_shares, COALESCE(SUM(difficulty),0) accepted_diff FROM shares WHERE accepted=1 AND ts>?",
            (round_start,),
        )

    # Hashrate reporting should survive a temporary wallet/mining RPC failure.
    # Network-derived luck fields can be unavailable without zeroing hashrate.
    try:
        network_diff = base.current_network_difficulty()
    except Exception:
        network_diff = None

    round_diff = float(round_stats.get("accepted_diff") or 0)
    effort_ratio = 0.0
    chance = 0.0
    eta_seconds = None
    if network_diff is not None and float(network_diff) > 0:
        expected_stratum_diff = max(float(network_diff) * base.GHOSTRIDER_TARGET_FACTOR, 1e-30)
        effort_ratio = round_diff / expected_stratum_diff
        import math
        chance = (1.0 - math.exp(-effort_ratio)) * 100.0
        eta_seconds = float(network_diff) * base.DIFF1_HASHES / pool_hashrate if pool_hashrate > 0 else None

    return {
        "pool_hashrate": pool_hashrate,
        "network_difficulty": network_diff,
        "eta_seconds": eta_seconds,
        "round_start": round_start,
        "round_seconds": max(0, now - round_start),
        "round_accepted_shares": int(round_stats.get("accepted_shares") or 0),
        "round_stratum_difficulty": round_diff,
        "round_effort_percent": effort_ratio * 100.0,
        "chance_percent": chance,
        "last_block_height": last_block.get("height") if last_block else None,
    }


def api_shares(status=None, address=None, limit=250):
    """Return shares with the persisted Stratum rejection reason when present."""
    clauses = []
    params = []
    if status == "accepted":
        clauses.append("s.accepted=1")
    elif status == "rejected":
        clauses.append("s.accepted=0")
    if address:
        clauses.append("a.address=?")
        params.append(address)

    with base.db() as con:
        columns = {row[1] for row in con.execute("PRAGMA table_info(shares)")}
        reason_expr = "s.rejection_reason" if "rejection_reason" in columns else "NULL AS rejection_reason"
        sql = f"""SELECT s.id,s.ts,s.worker,s.worker_id,s.job_id,s.difficulty,s.accepted,
                         s.block_candidate,s.hash,{reason_expr},a.address
                  FROM shares s LEFT JOIN accounts a ON a.id=s.account_id"""
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY s.id DESC LIMIT ?"
        params.append(min(max(int(limit), 1), 1000))
        return base.rows(con, sql, params)


base.api_summary = api_summary
base.api_workers = api_workers
base.api_luck = api_luck
base.api_shares = api_shares


class LiveHandler(base.Handler):
    """Serve the existing dashboard with clearer reward and balance labels."""

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/pool/history":
            query = parse_qs(parsed.query)
            try:
                history = api_pool_history(
                    (query.get("hours") or [24])[0],
                    (query.get("bucket") or [300])[0],
                )
                return self.send_json(history)
            except Exception as exc:
                return self.send_json({"error": str(exc)}, 500)
        return super().do_GET()

    def serve_file(self, target):
        if target == base.WEB_ROOT / "index.html":
            text = target.read_text()
            text = text.replace(
                "['Address','Workers','Accepted','Rejected','Balance','Immature','Total Paid']",
                "['Address','Workers','Accepted','Rejected','Mature Balance','Immature Balance','Total Paid']",
            )
            text = text.replace(
                '<div class="muted">Immature</div>',
                '<div class="muted">Immature Balance</div>',
            )
            text = text.replace(
                '<div class="muted">Balance</div>',
                '<div class="muted">Mature Balance</div>',
            )
            text = text.replace(
                "const active=w.filter(x=>x.active).slice(0,24);const stats=(await Promise.all(active.map(x=>get('/api/worker/'+x.id+'/stats?hours=24&bucket=300').catch(()=>null)))).filter(Boolean);const h=aggregateHistory(stats);",
                "const h=await get('/api/pool/history?hours=24&bucket=300').catch(()=>[]);",
            )
            # Keep displayed current hashrate tied to the same pool-wide share
            # stream as the graph instead of depending on worker active flags.
            text = text.replace(
                "const current=w.reduce((n,x)=>n+Number(x.active?x.hashrate:0),0);",
                "const recentBuckets=h.slice(-2);const current=recentBuckets.length?recentBuckets.reduce((n,x)=>n+Number(x.hashrate||0),0)/recentBuckets.length:w.reduce((n,x)=>n+Number(x.active?x.hashrate:0),0);",
            )
            text = text.replace(
                "Accepted GhostRider share work from currently tracked workers.",
                "Pool-wide GhostRider share work recorded during the last 24 hours.",
            )
            text = text.replace(
                "</head>",
                '<link rel="stylesheet" href="/brand.css?v=1"></head>',
            )
            body = text.replace(
                "</body>",
                base.LUCK_SCRIPT + '<script src="/reward_labels.js?v=5"></script></body>',
            ).encode()
        else:
            body = target.read_bytes()
        self.send_response(200)
        self.send_header(
            "Content-Type",
            mimetypes.guess_type(target.name)[0] or "application/octet-stream",
        )
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    print(f"YERB Pool web listening on http://{base.HOST}:{base.PORT} (live metrics)")
    ThreadingHTTPServer((base.HOST, base.PORT), LiveHandler).serve_forever()

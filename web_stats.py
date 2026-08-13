#!/usr/bin/env python3
"""YERB Pool dashboard runtime with live production metrics.

This keeps the existing web.py routes/UI intact while overriding the summary,
worker activity, and luck/hashrate calculations with values derived directly
from the live production database and Yerbas wallet RPC.
"""
import contextlib
import mimetypes
import sqlite3
import time
from http.server import ThreadingHTTPServer

import web as base


COIN = 100_000_000
ACTIVE_WINDOW = 600
HASHRATE_WINDOW = 600


@contextlib.contextmanager
def _closed_db():
    """Open the pool SQLite database and always close it after the request.

    sqlite3.Connection's own context-manager commits/rolls back but does not
    close the connection, which caused the dashboard to eventually exhaust
    its file-descriptor limit under repeated API refreshes.
    """
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


def api_luck():
    now = int(time.time())
    cutoff = now - HASHRATE_WINDOW
    with base.db() as con:
        recent = base.one(
            con,
            "SELECT COALESCE(SUM(difficulty),0) accepted_diff FROM shares WHERE accepted=1 AND ts>=?",
            (cutoff,),
        )
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

    recent_diff = float(recent.get("accepted_diff") or 0)
    pool_hashrate = (
        (recent_diff / base.GHOSTRIDER_TARGET_FACTOR)
        * base.DIFF1_HASHES
        / HASHRATE_WINDOW
    )
    network_diff = base.current_network_difficulty()
    expected_stratum_diff = max(network_diff * base.GHOSTRIDER_TARGET_FACTOR, 1e-30)
    round_diff = float(round_stats.get("accepted_diff") or 0)
    effort_ratio = round_diff / expected_stratum_diff

    import math
    chance = (1.0 - math.exp(-effort_ratio)) * 100.0
    eta_seconds = network_diff * base.DIFF1_HASHES / pool_hashrate if pool_hashrate > 0 else None

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


base.api_summary = api_summary
base.api_workers = api_workers
base.api_luck = api_luck


class LiveHandler(base.Handler):
    """Serve the existing dashboard with clearer reward and balance labels."""

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
                "</head>",
                '<link rel="stylesheet" href="/brand.css?v=1"></head>',
            )
            body = text.replace(
                "</body>",
                base.LUCK_SCRIPT + '<script src="/reward_labels.js?v=1"></script></body>',
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

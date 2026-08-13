#!/usr/bin/env python3
import json
import mimetypes
import sqlite3
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from yerbpool.config import load_config

ROOT = Path(__file__).resolve().parent
WEB_ROOT = ROOT / "web"
CFG = load_config()
DB_PATH = Path(CFG.get("database", "yerbpool.db"))
if not DB_PATH.is_absolute():
    DB_PATH = ROOT / DB_PATH
WEB_CFG = CFG.get("web", {})
HOST = WEB_CFG.get("host", "127.0.0.1")
PORT = int(WEB_CFG.get("port", 8080))
GHOSTRIDER_TARGET_FACTOR = 65536.0


def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def one(con, sql, params=()):
    row = con.execute(sql, params).fetchone()
    return dict(row) if row else {}


def rows(con, sql, params=()):
    return [dict(r) for r in con.execute(sql, params).fetchall()]


def api_summary():
    with db() as con:
        accounts = one(con, "SELECT COUNT(*) accounts, COALESCE(SUM(balance_atomic),0) balance_atomic, COALESCE(SUM(immature_balance_atomic),0) immature_atomic FROM accounts")
        shares = one(con, "SELECT COUNT(*) shares, COALESCE(SUM(CASE WHEN accepted=1 THEN 1 ELSE 0 END),0) accepted, COALESCE(SUM(CASE WHEN accepted=0 THEN 1 ELSE 0 END),0) rejected FROM shares")
        workers = one(con, "SELECT COUNT(*) workers, COALESCE(SUM(CASE WHEN last_seen_at >= strftime('%s','now')-600 THEN 1 ELSE 0 END),0) active_workers FROM workers")
        blocks = one(con, "SELECT COUNT(*) blocks, COALESCE(SUM(CASE WHEN status='mature' THEN 1 ELSE 0 END),0) mature, COALESCE(SUM(CASE WHEN status IN ('submitted','confirmed') THEN 1 ELSE 0 END),0) pending FROM blocks")
        payouts = one(con, "SELECT COUNT(*) payouts, COALESCE(SUM(CASE WHEN status='sent' THEN total_atomic ELSE 0 END),0) paid_atomic FROM payouts")
    return {"accounts": accounts, "shares": shares, "workers": workers, "blocks": blocks, "payouts": payouts}


def api_blocks(status=None, limit=100):
    with db() as con:
        sql = "SELECT id,height,block_hash,status,confirmations,reward_atomic,pool_fee_atomic,submitted_at,maturity_height FROM blocks"
        params = []
        if status:
            if status == "pending":
                sql += " WHERE status IN ('submitted','confirmed')"
            else:
                sql += " WHERE status=?"
                params.append(status)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(min(max(int(limit), 1), 500))
        return rows(con, sql, params)


def api_miners(limit=250):
    with db() as con:
        return rows(con, """SELECT a.address,a.balance_atomic,a.immature_balance_atomic,a.total_earned_atomic,a.total_paid_atomic,
            COUNT(w.id) worker_count, COALESCE(MAX(w.last_seen_at),0) last_seen_at,
            COALESCE(SUM(w.accepted_shares),0) accepted_shares, COALESCE(SUM(w.rejected_shares),0) rejected_shares
            FROM accounts a LEFT JOIN workers w ON w.account_id=a.id
            GROUP BY a.id ORDER BY last_seen_at DESC LIMIT ?""", (min(max(int(limit), 1), 1000),))


def api_workers(limit=500):
    now = int(time.time())
    window = 600
    with db() as con:
        result = rows(con, """SELECT w.id,a.address,w.name,w.created_at,w.last_seen_at,w.accepted_shares,w.rejected_shares,
            COALESCE(SUM(CASE WHEN s.accepted=1 AND s.ts>=? THEN s.difficulty ELSE 0 END),0) recent_diff,
            COALESCE(MAX(CASE WHEN s.accepted=1 THEN s.ts ELSE NULL END),0) last_share_at
            FROM workers w JOIN accounts a ON a.id=w.account_id
            LEFT JOIN shares s ON s.worker_id=w.id
            GROUP BY w.id ORDER BY w.last_seen_at DESC LIMIT ?""", (now - window, min(max(int(limit), 1), 1000)))
    for item in result:
        # GhostRider cpuminer uses target difficulty D/65536.
        item["hashrate"] = (float(item.get("recent_diff") or 0) / GHOSTRIDER_TARGET_FACTOR) * 4294967296.0 / window
        item["active"] = int(item.get("last_seen_at") or 0) >= now - window
    return result


def api_worker_stats(worker_id, hours=24, bucket_seconds=300):
    worker_id = int(worker_id)
    hours = min(max(int(hours), 1), 168)
    bucket_seconds = min(max(int(bucket_seconds), 60), 3600)
    now = int(time.time())
    end = (now // bucket_seconds) * bucket_seconds
    start = end - hours * 3600

    with db() as con:
        worker = one(con, """SELECT w.id,a.address,w.name,w.created_at,w.last_seen_at,
            w.accepted_shares,w.rejected_shares
            FROM workers w JOIN accounts a ON a.id=w.account_id WHERE w.id=?""", (worker_id,))
        if not worker:
            return None
        raw = rows(con, """SELECT (s.ts / ?) * ? bucket,
            COALESCE(SUM(CASE WHEN s.accepted=1 THEN s.difficulty ELSE 0 END),0) accepted_diff,
            COALESCE(SUM(CASE WHEN s.accepted=1 THEN 1 ELSE 0 END),0) accepted,
            COALESCE(SUM(CASE WHEN s.accepted=0 THEN 1 ELSE 0 END),0) rejected
            FROM shares s WHERE s.worker_id=? AND s.ts>=? AND s.ts<?
            GROUP BY bucket ORDER BY bucket""",
            (bucket_seconds, bucket_seconds, worker_id, start, end + bucket_seconds))

    by_bucket = {int(r["bucket"]): r for r in raw}
    history = []
    t = start
    while t <= end:
        r = by_bucket.get(t, {})
        accepted_diff = float(r.get("accepted_diff") or 0)
        history.append({
            "ts": t,
            "hashrate": (accepted_diff / GHOSTRIDER_TARGET_FACTOR) * 4294967296.0 / bucket_seconds,
            "accepted": int(r.get("accepted") or 0),
            "rejected": int(r.get("rejected") or 0),
        })
        t += bucket_seconds

    worker["active"] = int(worker.get("last_seen_at") or 0) >= now - 600
    worker["hours"] = hours
    worker["bucket_seconds"] = bucket_seconds
    worker["history"] = history
    return worker


def api_shares(status=None, address=None, limit=250):
    clauses = []
    params = []
    if status == "accepted":
        clauses.append("s.accepted=1")
    elif status == "rejected":
        clauses.append("s.accepted=0")
    if address:
        clauses.append("a.address=?")
        params.append(address)
    sql = """SELECT s.id,s.ts,s.worker,s.job_id,s.difficulty,s.accepted,s.block_candidate,s.hash,a.address
             FROM shares s LEFT JOIN accounts a ON a.id=s.account_id"""
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY s.id DESC LIMIT ?"
    params.append(min(max(int(limit), 1), 1000))
    with db() as con:
        return rows(con, sql, params)


def api_account(address):
    with db() as con:
        account = one(con, """SELECT id,address,created_at,updated_at,balance_atomic,immature_balance_atomic,
            total_earned_atomic,total_paid_atomic,minimum_payout_atomic,enabled FROM accounts WHERE address=?""", (address,))
        if not account:
            return None
        account["workers"] = rows(con, "SELECT id,name,created_at,last_seen_at,accepted_shares,rejected_shares FROM workers WHERE account_id=? ORDER BY name", (account["id"],))
        account["ledger"] = rows(con, "SELECT id,ts,block_id,payout_id,entry_type,amount_atomic,note FROM ledger WHERE account_id=? ORDER BY id DESC LIMIT 100", (account["id"],))
        account["payouts"] = rows(con, """SELECT p.id,p.created_at,p.sent_at,p.txid,p.status,pi.amount_atomic
            FROM payout_items pi JOIN payouts p ON p.id=pi.payout_id WHERE pi.account_id=? ORDER BY p.id DESC LIMIT 100""", (account["id"],))
        return account


def api_payouts(limit=100):
    with db() as con:
        return rows(con, "SELECT id,created_at,sent_at,txid,total_atomic,fee_atomic,status,error FROM payouts ORDER BY id DESC LIMIT ?", (min(max(int(limit), 1), 500),))


FRONTEND_ROUTES = {"/", "/miners", "/workers", "/shares", "/blocks", "/blocks/pending", "/payouts"}


class Handler(BaseHTTPRequestHandler):
    def send_json(self, obj, status=200):
        body = json.dumps(obj, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def serve_file(self, target):
        body = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(target.name)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        try:
            if path == "/api/summary": return self.send_json(api_summary())
            if path == "/api/blocks": return self.send_json(api_blocks((query.get("status") or [None])[0], (query.get("limit") or [100])[0]))
            if path == "/api/miners": return self.send_json(api_miners((query.get("limit") or [250])[0]))
            if path == "/api/workers": return self.send_json(api_workers((query.get("limit") or [500])[0]))
            if path.startswith("/api/worker/") and path.endswith("/stats"):
                worker_id = unquote(path[len("/api/worker/"):-len("/stats")]).strip("/")
                stats = api_worker_stats(worker_id, (query.get("hours") or [24])[0], (query.get("bucket") or [300])[0])
                return self.send_json(stats if stats is not None else {"error": "worker not found"}, 200 if stats is not None else 404)
            if path == "/api/shares": return self.send_json(api_shares((query.get("status") or [None])[0], (query.get("address") or [None])[0], (query.get("limit") or [250])[0]))
            if path.startswith("/api/account/"):
                account = api_account(unquote(path[len("/api/account/"):]))
                return self.send_json(account if account is not None else {"error": "account not found"}, 200 if account is not None else 404)
            if path == "/api/payouts": return self.send_json(api_payouts((query.get("limit") or [100])[0]))
            if path == "/api/health": return self.send_json({"ok": True})

            if path in FRONTEND_ROUTES or path.startswith("/account/") or path.startswith("/worker/"):
                return self.serve_file(WEB_ROOT / "index.html")

            target = (WEB_ROOT / path.lstrip("/")).resolve()
            if WEB_ROOT.resolve() not in target.parents and target != WEB_ROOT.resolve():
                return self.send_error(403)
            if not target.is_file(): return self.send_error(404)
            return self.serve_file(target)
        except Exception as exc:
            self.send_json({"error": str(exc)}, 500)

    def log_message(self, fmt, *args):
        print("web:", fmt % args)


if __name__ == "__main__":
    print(f"YERB Pool web listening on http://{HOST}:{PORT}")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()

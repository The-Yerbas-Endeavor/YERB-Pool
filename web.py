#!/usr/bin/env python3
import json
import mimetypes
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

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


def api_blocks():
    with db() as con:
        return rows(con, "SELECT height,block_hash,status,confirmations,reward_atomic,submitted_at FROM blocks ORDER BY id DESC LIMIT 25")


def api_miners():
    with db() as con:
        return rows(con, """SELECT a.address,a.balance_atomic,a.immature_balance_atomic,a.total_earned_atomic,a.total_paid_atomic,
            COUNT(w.id) worker_count, COALESCE(MAX(w.last_seen_at),0) last_seen_at
            FROM accounts a LEFT JOIN workers w ON w.account_id=a.id
            GROUP BY a.id ORDER BY last_seen_at DESC LIMIT 100""")


def api_payouts():
    with db() as con:
        return rows(con, "SELECT id,created_at,sent_at,txid,total_atomic,status,error FROM payouts ORDER BY id DESC LIMIT 25")


class Handler(BaseHTTPRequestHandler):
    def send_json(self, obj, status=200):
        body = json.dumps(obj, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        try:
            if path == "/api/summary": return self.send_json(api_summary())
            if path == "/api/blocks": return self.send_json(api_blocks())
            if path == "/api/miners": return self.send_json(api_miners())
            if path == "/api/payouts": return self.send_json(api_payouts())
            if path == "/api/health": return self.send_json({"ok": True})
            if path == "/": path = "/index.html"
            target = (WEB_ROOT / path.lstrip("/")).resolve()
            if WEB_ROOT.resolve() not in target.parents and target != WEB_ROOT.resolve():
                return self.send_error(403)
            if not target.is_file(): return self.send_error(404)
            body = target.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", mimetypes.guess_type(target.name)[0] or "application/octet-stream")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except Exception as exc:
            self.send_json({"error": str(exc)}, 500)

    def log_message(self, fmt, *args):
        print("web:", fmt % args)


if __name__ == "__main__":
    print(f"YERB Pool web listening on http://{HOST}:{PORT}")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()

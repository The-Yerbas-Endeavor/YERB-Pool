#!/usr/bin/env python3
import base64
import json
import math
import mimetypes
import sqlite3
import time
import urllib.request
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
DIFF1_HASHES = 4294967296.0


def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def one(con, sql, params=()):
    row = con.execute(sql, params).fetchone()
    return dict(row) if row else {}


def rows(con, sql, params=()):
    return [dict(r) for r in con.execute(sql, params).fetchall()]


def rpc_call(method, params=None):
    cfg = CFG.get("rpc", {})
    payload = json.dumps({"jsonrpc": "1.0", "id": "yerbpool-web", "method": method, "params": params or []}).encode()
    token = base64.b64encode(f"{cfg.get('user', '')}:{cfg.get('password', '')}".encode()).decode()
    req = urllib.request.Request(
        cfg.get("url", "http://127.0.0.1:15419"),
        data=payload,
        headers={"Content-Type": "application/json", "Authorization": f"Basic {token}"},
    )
    with urllib.request.urlopen(req, timeout=3) as response:
        result = json.loads(response.read().decode())
    if result.get("error"):
        raise RuntimeError(str(result["error"]))
    return result.get("result")


def current_network_difficulty():
    try:
        info = rpc_call("getmininginfo")
        if isinstance(info, dict) and info.get("difficulty") is not None:
            return float(info["difficulty"])
    except Exception:
        pass
    return float(rpc_call("getdifficulty"))


def api_luck():
    now = int(time.time())
    window = 600
    with db() as con:
        recent = one(con, """SELECT COALESCE(SUM(difficulty),0) accepted_diff
            FROM shares WHERE accepted=1 AND ts>=?""", (now - window,))
        last_block = one(con, "SELECT height,submitted_at FROM blocks ORDER BY id DESC LIMIT 1")
        if last_block and last_block.get("submitted_at"):
            round_start = int(last_block["submitted_at"])
        else:
            first = one(con, "SELECT MIN(ts) first_ts FROM shares WHERE accepted=1")
            round_start = int(first.get("first_ts") or now)
        round_stats = one(con, """SELECT COUNT(*) accepted_shares, COALESCE(SUM(difficulty),0) accepted_diff
            FROM shares WHERE accepted=1 AND ts>?""", (round_start,))

    recent_diff = float(recent.get("accepted_diff") or 0)
    pool_hashrate = (recent_diff / GHOSTRIDER_TARGET_FACTOR) * DIFF1_HASHES / window
    network_diff = current_network_difficulty()
    expected_stratum_diff = max(network_diff * GHOSTRIDER_TARGET_FACTOR, 1e-30)
    round_diff = float(round_stats.get("accepted_diff") or 0)
    effort_ratio = round_diff / expected_stratum_diff
    chance = (1.0 - math.exp(-effort_ratio)) * 100.0
    eta_seconds = (network_diff * DIFF1_HASHES / pool_hashrate) if pool_hashrate > 0 else None

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


def api_summary():
    now = int(time.time())
    active_cutoff = now - 3600
    with db() as con:
        accounts = one(con, """SELECT COUNT(*) accounts,
            COALESCE(SUM(a.balance_atomic),0) balance_atomic,
            COALESCE(SUM(a.immature_balance_atomic),0) immature_atomic
            FROM accounts a
            WHERE NOT EXISTS (
                SELECT 1 FROM settings s
                WHERE s.key='pool_treasury_address' AND s.value=a.address
            )""")
        active_miners = one(con, """SELECT COUNT(DISTINCT a.id) active_miners
            FROM accounts a JOIN workers w ON w.account_id=a.id
            WHERE a.enabled=1 AND w.last_seen_at>=?
              AND NOT EXISTS (
                SELECT 1 FROM settings s
                WHERE s.key='pool_treasury_address' AND s.value=a.address
              )""", (active_cutoff,))
        accounts["active_miners"] = int(active_miners.get("active_miners") or 0)
        shares = one(con, "SELECT COUNT(*) shares, COALESCE(SUM(CASE WHEN accepted=1 THEN 1 ELSE 0 END),0) accepted, COALESCE(SUM(CASE WHEN accepted=0 THEN 1 ELSE 0 END),0) rejected FROM shares")
        workers = one(con, "SELECT COUNT(*) workers, COALESCE(SUM(CASE WHEN last_seen_at >= strftime('%s','now')-600 THEN 1 ELSE 0 END),0) active_workers FROM workers")
        blocks = one(con, "SELECT COUNT(*) blocks, COALESCE(SUM(CASE WHEN status='mature' THEN 1 ELSE 0 END),0) mature, COALESCE(SUM(CASE WHEN status IN ('submitted','confirmed') THEN 1 ELSE 0 END),0) pending FROM blocks")
        payouts = one(con, "SELECT COUNT(*) payouts, COALESCE(SUM(CASE WHEN status='sent' THEN total_atomic ELSE 0 END),0) paid_atomic FROM payouts")
    return {"accounts": accounts, "shares": shares, "workers": workers, "blocks": blocks, "payouts": payouts}


def api_blocks(status=None, limit=100):
    with db() as con:
        sql = "SELECT id,height,block_hash,status,confirmations,reward_atomic,network_reward_atomic,pool_fee_atomic,submitted_at,maturity_height FROM blocks"
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
    active_cutoff = int(time.time()) - 3600
    with db() as con:
        return rows(con, """SELECT a.address,a.balance_atomic,a.immature_balance_atomic,a.total_earned_atomic,a.total_paid_atomic,
            COUNT(w.id) worker_count, COALESCE(MAX(w.last_seen_at),0) last_seen_at,
            COALESCE(SUM(w.accepted_shares),0) accepted_shares, COALESCE(SUM(w.rejected_shares),0) rejected_shares
            FROM accounts a LEFT JOIN workers w ON w.account_id=a.id
            WHERE a.enabled=1
              AND NOT EXISTS (
                SELECT 1 FROM settings s
                WHERE s.key='pool_treasury_address' AND s.value=a.address
            )
            GROUP BY a.id
            HAVING COALESCE(MAX(w.last_seen_at),0) >= ?
            ORDER BY last_seen_at DESC LIMIT ?""",
            (active_cutoff, min(max(int(limit), 1), 1000)))


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
        item["hashrate"] = (float(item.get("recent_diff") or 0) / GHOSTRIDER_TARGET_FACTOR) * DIFF1_HASHES / window
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
            COALESCE(SUM(CASE WHEN s.accepted=0 THEN s.difficulty ELSE 0 END),0) rejected_diff,
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
        rejected_diff = float(r.get("rejected_diff") or 0)
        history.append({
            "ts": t,
            "hashrate": (accepted_diff / GHOSTRIDER_TARGET_FACTOR) * DIFF1_HASHES / bucket_seconds,
            "accepted": int(r.get("accepted") or 0),
            "rejected": int(r.get("rejected") or 0),
            "accepted_diff": accepted_diff,
            "rejected_diff": rejected_diff,
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

LUCK_SCRIPT = r'''
<script>
(function(){
  if(location.pathname !== '/') return;
  const fmtHash=v=>{v=Number(v||0);if(v>=1e9)return(v/1e9).toFixed(2)+' GH/s';if(v>=1e6)return(v/1e6).toFixed(2)+' MH/s';if(v>=1e3)return(v/1e3).toFixed(2)+' kH/s';return v.toFixed(1)+' H/s'};
  const fmtTime=s=>{if(s==null||!isFinite(s))return '—';s=Math.max(0,Number(s));if(s<60)return Math.round(s)+' sec';if(s<3600)return (s/60).toFixed(1)+' min';if(s<86400)return (s/3600).toFixed(1)+' hr';return (s/86400).toFixed(1)+' days'};
  async function renderLuck(){
    try{
      const r=await fetch('/api/luck',{cache:'no-store'}); if(!r.ok)return;
      const x=await r.json(); const root=document.querySelector('main#app'); if(!root)return;
      let panel=document.getElementById('luck-panel');
      if(!panel){panel=document.createElement('section');panel.id='luck-panel';const first=root.querySelector('.grid');if(first)first.insertAdjacentElement('afterend',panel);else root.prepend(panel)}
      panel.innerHTML=`<div style="display:flex;justify-content:space-between;align-items:end;gap:12px;flex-wrap:wrap"><div><h2 style="margin-bottom:4px">Pool Luck & Round</h2><div class="muted">Current round statistics based on accepted GhostRider work.</div></div><a href="/blocks">Blocks →</a></div><div class="grid" style="margin-top:14px"><div class="card"><div class="muted">Pool Hashrate</div><div class="value">${fmtHash(x.pool_hashrate)}</div></div><div class="card"><div class="muted">Network Difficulty</div><div class="value">${Number(x.network_difficulty||0).toPrecision(5)}</div></div><div class="card"><div class="muted">Estimated Time to Block</div><div class="value" style="font-size:22px">${fmtTime(x.eta_seconds)}</div></div><div class="card"><div class="muted">Round Effort</div><div class="value">${Number(x.round_effort_percent||0).toFixed(1)}%</div><div class="small muted">100% = expected work</div></div><div class="card"><div class="muted">Chance So Far</div><div class="value">${Number(x.chance_percent||0).toFixed(1)}%</div><div class="small muted">Probability by this effort</div></div><div class="card"><div class="muted">Round Shares</div><div class="value">${Number(x.round_accepted_shares||0).toLocaleString()}</div><div class="small muted">Round age ${fmtTime(x.round_seconds)}</div></div></div>`;
    }catch(e){}
  }
  setTimeout(renderLuck,800); setInterval(renderLuck,10000);
})();
</script>
'''


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
        if target == WEB_ROOT / "index.html":
            text = target.read_text()
            text = text.replace("</head>", '<link rel="stylesheet" href="/brand.css?v=1"></head>')
            body = text.replace("</body>", LUCK_SCRIPT + "</body>").encode()
        else:
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
            if path == "/api/luck": return self.send_json(api_luck())
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

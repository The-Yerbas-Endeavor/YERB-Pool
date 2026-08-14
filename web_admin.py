#!/usr/bin/env python3
import base64
import hashlib
import hmac
import json
import time
from html import escape
from http.server import ThreadingHTTPServer
from urllib.parse import unquote, urlparse

import web_stats as live
from yerbpool.admin_settings import get_pool_fee_percent, set_pool_fee_percent


CFG = live.base.CFG
# Account pages need a live rolling estimate that is independent of partial
# 5-minute chart buckets. The parent dashboard injects LUCK_SCRIPT into every
# served index page, so append this small account-only enhancement there.
live.base.LUCK_SCRIPT += '<script src="/account_live_hashrate.js?v=1"></script>'


def _verify_password(password, spec):
    if not isinstance(spec, dict) or spec.get("scheme") != "pbkdf2_sha256":
        return False
    try:
        iterations = int(spec.get("iterations", 310000))
        salt = bytes.fromhex(spec["salt"])
        expected = bytes.fromhex(spec["hash"])
    except Exception:
        return False
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(actual, expected)


def _admin_config():
    return CFG.get("admin", {})


def _admin_enabled():
    admin = _admin_config()
    return bool(admin.get("username") and admin.get("password_hash"))


def _authorized(header):
    if not _admin_enabled() or not header or not header.startswith("Basic "):
        return False
    try:
        raw = base64.b64decode(header[6:], validate=True).decode("utf-8")
        username, password = raw.split(":", 1)
    except Exception:
        return False
    admin = _admin_config()
    return hmac.compare_digest(username, str(admin.get("username", ""))) and _verify_password(
        password, admin.get("password_hash")
    )


def _public_settings():
    payouts = CFG.get("payouts", {})
    return {
        "pool_fee_percent": get_pool_fee_percent(CFG),
        "coinbase_maturity": int(payouts.get("coinbase_maturity", 100)),
        "minimum_payout": str(payouts.get("minimum_payout", "1.00000000")),
        "check_interval_seconds": int(payouts.get("check_interval_seconds", 60)),
    }


def _account_hashrate(address):
    """Rolling 10-minute hashrate for one payout address from accepted shares."""
    cutoff = int(time.time()) - live.HASHRATE_WINDOW
    with live.base.db() as con:
        row = live.base.one(
            con,
            """SELECT COALESCE(SUM(s.difficulty),0) accepted_diff,
                      COALESCE(MAX(s.ts),0) last_share_at,
                      COUNT(DISTINCT s.worker_id) workers
               FROM shares s
               JOIN accounts a ON a.id=s.account_id
               WHERE a.address=? AND s.accepted=1 AND s.ts>=?""",
            (address, cutoff),
        )
    recent_diff = float(row.get("accepted_diff") or 0)
    hashrate = (
        (recent_diff / live.base.GHOSTRIDER_TARGET_FACTOR)
        * live.base.DIFF1_HASHES
        / live.HASHRATE_WINDOW
    )
    return {
        "address": address,
        "hashrate": hashrate,
        "window_seconds": live.HASHRATE_WINDOW,
        "accepted_difficulty": recent_diff,
        "last_share_at": int(row.get("last_share_at") or 0),
        "workers": int(row.get("workers") or 0),
    }


def _admin_snapshot():
    data = _public_settings()
    data["summary"] = live.api_summary()
    try:
        wallet = live.base.rpc_call("getwalletinfo")
        data["wallet"] = {
            "balance": wallet.get("balance", 0),
            "immature_balance": wallet.get("immature_balance", 0),
            "txcount": wallet.get("txcount", 0),
        }
    except Exception as exc:
        data["wallet"] = {"error": str(exc)}
    return data


def _admin_html():
    if not _admin_enabled():
        setup = "sudo -u yerbpool python3 /opt/yerb-pool/scripts/set-admin-password.py"
        return f"""<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>YERB Pool Admin</title><link rel='stylesheet' href='/brand.css?v=1'></head><body><main style='max-width:850px;margin:60px auto;padding:24px'><h1>YERB Pool Admin</h1><div class='card'><h2>Admin login is not configured</h2><p class='muted'>Set an admin password locally, then restart the web service.</p><code>{escape(setup)}</code></div></main></body></html>"""

    return """<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>YERB Pool Admin</title><link rel="stylesheet" href="/brand.css?v=1">
<style>body{background:#111;color:#eee;font-family:system-ui,sans-serif;margin:0}main{max-width:1000px;margin:auto;padding:30px}.admin-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:14px}.admin-card{background:#1b1b1b;border:1px solid #303030;border-radius:10px;padding:18px}.admin-card strong{display:block;font-size:24px;margin-top:4px}.form-row{display:flex;gap:12px;align-items:end;flex-wrap:wrap}label{display:block;color:#aaa;font-size:13px;margin-bottom:6px}input{background:#111;color:#fff;border:1px solid #444;border-radius:7px;padding:10px 12px;font-size:16px;width:180px}button{background:#2b7a3d;color:#fff;border:0;border-radius:7px;padding:11px 18px;font-weight:700;cursor:pointer}.notice{margin-top:12px;color:#9fe3a7}.error{color:#ffaaaa}.muted{color:#aaa}a{color:#9fd3ff}</style></head>
<body><main><div style="display:flex;justify-content:space-between;align-items:center;gap:20px;flex-wrap:wrap"><div><h1 style="margin-bottom:4px">YERB Pool Admin</h1><div class="muted">Operational settings and pool status</div></div><a href="/">← Public dashboard</a></div>
<section><h2>Pool status</h2><div class="admin-grid" id="status"><div class="admin-card">Loading…</div></div></section>
<section><h2>Pool fee</h2><div class="admin-card"><div class="form-row"><div><label for="fee">Pool fee percent</label><input id="fee" type="number" min="0" max="100" step="0.01"></div><button id="save">Save fee</button></div><p class="muted">The new fee applies to the next block found. Existing block allocations and miner balances are never recalculated.</p><div id="message"></div></div></section>
<section><h2>Payout configuration</h2><div class="admin-grid" id="payouts"></div></section>
<script>
const coin=v=>Number(v||0).toFixed(2)+' YERB';
async function load(){const r=await fetch('/api/admin/settings',{cache:'no-store'});if(!r.ok)throw new Error(await r.text());const x=await r.json();document.getElementById('fee').value=Number(x.pool_fee_percent||0).toFixed(2);const s=x.summary||{},w=x.wallet||{};document.getElementById('status').innerHTML=`<div class="admin-card"><span class="muted">Wallet Balance</span><strong>${coin(w.balance)}</strong></div><div class="admin-card"><span class="muted">Immature Wallet</span><strong>${coin(w.immature_balance)}</strong></div><div class="admin-card"><span class="muted">Active Workers</span><strong>${s.workers?.active_workers??0}</strong></div><div class="admin-card"><span class="muted">Pending Blocks</span><strong>${s.blocks?.pending??0}</strong></div><div class="admin-card"><span class="muted">Total Paid</span><strong>${coin(Number(s.payouts?.paid_atomic||0)/1e8)}</strong></div>`;document.getElementById('payouts').innerHTML=`<div class="admin-card"><span class="muted">Minimum Payout</span><strong>${x.minimum_payout} YERB</strong></div><div class="admin-card"><span class="muted">Payment Check</span><strong>${x.check_interval_seconds}s</strong></div><div class="admin-card"><span class="muted">Coinbase Maturity</span><strong>${x.coinbase_maturity} blocks</strong></div>`;}
document.getElementById('save').onclick=async()=>{const message=document.getElementById('message');message.className='';message.textContent='Saving…';try{const fee=Number(document.getElementById('fee').value);const r=await fetch('/api/admin/settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({pool_fee_percent:fee})});const x=await r.json();if(!r.ok)throw new Error(x.error||'Save failed');message.className='notice';message.textContent=`Pool fee updated to ${Number(x.pool_fee_percent).toFixed(2)}%. Applies to the next block.`;await load();}catch(e){message.className='error';message.textContent=e.message;}};
load().catch(e=>{document.getElementById('status').innerHTML=`<div class="admin-card error">${e.message}</div>`});
</script></main></body></html>"""


class AdminHandler(live.LiveHandler):
    def _require_admin(self):
        if _authorized(self.headers.get("Authorization")):
            return True
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="YERB Pool Admin", charset="UTF-8"')
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        return False

    def _send_html(self, text, status=200):
        body = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        if path.startswith("/api/account-hashrate/"):
            address = unquote(path[len("/api/account-hashrate/"):]).strip()
            if not address:
                return self.send_json({"error": "address is required"}, 400)
            return self.send_json(_account_hashrate(address))
        if path == "/api/pool-settings":
            return self.send_json(_public_settings())
        if path == "/admin":
            if _admin_enabled() and not self._require_admin():
                return
            return self._send_html(_admin_html())
        if path == "/api/admin/settings":
            if not self._require_admin():
                return
            return self.send_json(_admin_snapshot())
        return super().do_GET()

    def do_POST(self):
        path = urlparse(self.path).path
        if path != "/api/admin/settings":
            return self.send_error(404)
        if not self._require_admin():
            return
        try:
            length = min(max(int(self.headers.get("Content-Length", "0")), 0), 65536)
            payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
            if "pool_fee_percent" not in payload:
                return self.send_json({"error": "pool_fee_percent is required"}, 400)
            fee = float(payload["pool_fee_percent"])
            set_pool_fee_percent(CFG, fee, persist_config=True)
            return self.send_json({"ok": True, "pool_fee_percent": get_pool_fee_percent(CFG)})
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            return self.send_json({"error": str(exc)}, 400)
        except Exception as exc:
            return self.send_json({"error": str(exc)}, 500)


if __name__ == "__main__":
    print(f"YERB Pool web/admin listening on http://{live.base.HOST}:{live.base.PORT}")
    ThreadingHTTPServer((live.base.HOST, live.base.PORT), AdminHandler).serve_forever()

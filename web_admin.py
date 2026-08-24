#!/usr/bin/env python3
import base64
import hashlib
import hmac
import json
import sqlite3
import time
from decimal import Decimal
from html import escape
from http.server import ThreadingHTTPServer
from urllib.parse import unquote, urlparse

import web_stats as live
from yerbpool.coin_manager import activation_command, deployment_plan, load_registry, save_coin
from yerbpool.admin_settings import (
    YERB_ADDRESS_RE,
    ensure_treasury_address,
    get_pool_fee_percent,
    get_treasury_address,
    set_pool_fee_percent,
)
from yerbpool.rpc import YerbasRPC


CFG = live.base.CFG
COIN = 100_000_000
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


def _rpc():
    return YerbasRPC(CFG["rpc"])


def _treasury_address():
    address = get_treasury_address(CFG)
    if address:
        return address
    return ensure_treasury_address(CFG, _rpc())


def _public_settings():
    payouts = CFG.get("payouts", {})
    return {
        "pool_fee_percent": get_pool_fee_percent(CFG),
        "coinbase_maturity": int(payouts.get("coinbase_maturity", 100)),
        "minimum_payout": str(payouts.get("minimum_payout", "1.00000000")),
        "check_interval_seconds": int(payouts.get("check_interval_seconds", 60)),
    }


def _account_hashrate(address):
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


def _ensure_treasury_history_table():
    with live.base.db() as con:
        con.execute(
            """CREATE TABLE IF NOT EXISTS treasury_withdrawals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at INTEGER NOT NULL,
                destination TEXT NOT NULL,
                amount_atomic INTEGER NOT NULL,
                txid TEXT,
                status TEXT NOT NULL,
                error TEXT
            )"""
        )
        con.commit()


def _treasury_snapshot():
    _ensure_treasury_history_table()
    address = _treasury_address()
    rpc = _rpc()
    try:
        account = rpc.getaccount(address)
    except Exception:
        account = "YERB-Pool-Treasury"
    try:
        balance = float(rpc.getaccountbalance(account, 1, False))
    except Exception:
        balance = 0.0

    with live.base.db() as con:
        history = live.base.rows(
            con,
            "SELECT id,created_at,destination,amount_atomic,txid,status,error FROM treasury_withdrawals ORDER BY id DESC LIMIT 50",
        )
        accounting = live.base.one(
            con,
            """SELECT id,balance_atomic,immature_balance_atomic,total_earned_atomic,total_paid_atomic
               FROM accounts WHERE address=?""",
            (address,),
        )
        withdrawn = live.base.one(
            con,
            """SELECT COALESCE(SUM(amount_atomic),0) withdrawn_atomic
               FROM treasury_withdrawals WHERE status='sent'""",
        )
        ledger = []
        if accounting:
            ledger = live.base.rows(
                con,
                """SELECT l.id,l.ts,l.block_id,l.entry_type,l.amount_atomic,l.note,b.height
                   FROM ledger l
                   LEFT JOIN blocks b ON b.id=l.block_id
                   WHERE l.account_id=?
                   ORDER BY l.id DESC LIMIT 75""",
                (int(accounting["id"]),),
            )

    immature_atomic = int(accounting.get("immature_balance_atomic") or 0) if accounting else 0
    mature_earned_atomic = int(accounting.get("total_earned_atomic") or 0) if accounting else 0
    withdrawn_atomic = int(withdrawn.get("withdrawn_atomic") or 0)

    activity = []
    for item in ledger:
        entry_type = str(item.get("entry_type") or "")
        if entry_type == "block_immature":
            label = "Fee earned (immature)"
        elif entry_type == "block_mature":
            label = "Fee matured"
        elif entry_type == "block_orphan":
            label = "Orphan reversal"
        elif entry_type == "payout":
            label = "Treasury payout"
        else:
            label = entry_type.replace("_", " ").title() or "Ledger entry"
        activity.append({
            "ts": int(item.get("ts") or 0),
            "type": label,
            "amount_atomic": int(item.get("amount_atomic") or 0),
            "block_id": item.get("block_id"),
            "block_height": item.get("height"),
            "txid": None,
            "status": None,
            "note": item.get("note") or "",
        })

    for item in history:
        status = str(item.get("status") or "")
        amount = int(item.get("amount_atomic") or 0)
        activity.append({
            "ts": int(item.get("created_at") or 0),
            "type": "Treasury withdrawal" if status == "sent" else "Withdrawal attempt",
            "amount_atomic": -amount if status == "sent" else 0,
            "block_id": None,
            "block_height": None,
            "txid": item.get("txid"),
            "status": status,
            "note": item.get("error") or item.get("destination") or "",
        })

    activity.sort(key=lambda item: int(item.get("ts") or 0), reverse=True)
    activity = activity[:100]

    return {
        "address": address,
        "account": account,
        "balance": balance,
        "history": history,
        "total_fees_earned_atomic": mature_earned_atomic + immature_atomic,
        "immature_fees_atomic": immature_atomic,
        "mature_fees_earned_atomic": mature_earned_atomic,
        "total_withdrawn_atomic": withdrawn_atomic,
        "accounting_balance_atomic": int(accounting.get("balance_atomic") or 0) if accounting else 0,
        "activity": activity,
    }


def _admin_snapshot():
    data = _public_settings()
    data["summary"] = live.api_summary()
    data["treasury"] = _treasury_snapshot()
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


def _record_treasury_withdrawal(destination, amount_atomic, status, txid=None, error=None):
    _ensure_treasury_history_table()
    with live.base.db() as con:
        con.execute(
            "INSERT INTO treasury_withdrawals(created_at,destination,amount_atomic,txid,status,error) VALUES(?,?,?,?,?,?)",
            (int(time.time()), destination, int(amount_atomic), txid, status, error),
        )
        con.commit()


def _withdraw_treasury(destination, amount):
    destination = str(destination or "").strip()
    if not YERB_ADDRESS_RE.fullmatch(destination):
        raise ValueError("destination must be a valid YERB address")
    amount_dec = Decimal(str(amount))
    if amount_dec <= 0:
        raise ValueError("withdrawal amount must be greater than zero")

    treasury = _treasury_snapshot()
    balance_dec = Decimal(str(treasury["balance"]))
    if amount_dec > balance_dec:
        raise ValueError("treasury has insufficient funds")

    rpc = _rpc()
    amounts = {destination: float(amount_dec)}
    try:
        txid = str(rpc.sendmany(amounts, "YERB-Pool treasury withdrawal", treasury["account"]) or "")
    except Exception as exc:
        _record_treasury_withdrawal(destination, int(amount_dec * COIN), "failed", error=str(exc))
        raise
    _record_treasury_withdrawal(destination, int(amount_dec * COIN), "sent", txid=txid)
    return txid


def _admin_html():
    if not _admin_enabled():
        setup = "sudo -u yerbpool python3 /opt/yerb-pool/scripts/set-admin-password.py"
        return f"""<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>YERB Pool Admin</title><link rel='stylesheet' href='/brand.css?v=1'></head><body><main style='max-width:850px;margin:60px auto;padding:24px'><h1>YERB Pool Admin</h1><div class='card'><h2>Admin login is not configured</h2><p class='muted'>Set an admin password locally, then restart the web service.</p><code>{escape(setup)}</code></div></main></body></html>"""

    return """<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>YERB Pool Admin</title><link rel="stylesheet" href="/brand.css?v=1">
<style>body{background:#111;color:#eee;font-family:system-ui,sans-serif;margin:0}main{max-width:1100px;margin:auto;padding:30px}.admin-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:14px}.admin-card{background:#1b1b1b;border:1px solid #303030;border-radius:10px;padding:18px}.admin-card strong{display:block;font-size:24px;margin-top:4px}.form-row{display:flex;gap:12px;align-items:end;flex-wrap:wrap}label{display:block;color:#aaa;font-size:13px;margin-bottom:6px}input{box-sizing:border-box;background:#111;color:#fff;border:1px solid #444;border-radius:7px;padding:10px 12px;font-size:16px;width:200px}.wide{width:min(520px,80vw)}button{background:#2b7a3d;color:#fff;border:0;border-radius:7px;padding:11px 18px;font-weight:700;cursor:pointer}.secondary{background:#343434}.notice{margin-top:12px;color:#9fe3a7}.error{color:#ffaaaa}.muted{color:#aaa}a{color:#9fd3ff}table{width:100%;border-collapse:collapse;margin-top:12px}th,td{padding:9px;border-bottom:1px solid #2d2d2d;text-align:left;font-size:13px}code{word-break:break-all}.amount-positive{color:#9fe3a7}.amount-negative{color:#ffaaaa}.treasury-audit{margin-top:16px}.treasury-audit .admin-card strong{font-size:20px}.wizard-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:14px}.wizard-grid input{width:100%}#coin-plan{margin-top:16px}</style></head>
<body><main><div style="display:flex;justify-content:space-between;align-items:center;gap:20px;flex-wrap:wrap"><div><h1 style="margin-bottom:4px">YERB Pool Admin</h1><div class="muted">Operational settings and pool treasury</div></div><a href="/">← Public dashboard</a></div>
<section><h2>Pool status</h2><div class="admin-grid" id="status"><div class="admin-card">Loading…</div></div></section>
<section><h2>Coins</h2><div class="admin-card"><div id="coin-list">Loading…</div><details style="margin-top:18px"><summary><strong>Add another coin</strong></summary><p class="muted">Create a validated draft and deployment preview. The current YERB instance is not modified.</p><div class="wizard-grid"><div><label>Name</label><input id="coin-name" placeholder="Example Coin"></div><div><label>Ticker</label><input id="coin-ticker" placeholder="EXM"></div><div><label>Slug</label><input id="coin-slug" placeholder="exm"></div><div><label>Algorithm</label><input id="coin-algorithm" value="GhostRider"></div><div><label>Pool payout address</label><input id="coin-pool-address" placeholder="Coin wallet address"></div><div><label>Website domain</label><input id="coin-domain" placeholder="exm.pool.yerbas.org"></div><div><label>Explorer URL</label><input id="coin-explorer" placeholder="https://explorer.example.org"></div><div><label>Logo URL</label><input id="coin-logo" placeholder="https://example.org/logo.svg"></div><div><label>Theme color</label><input id="coin-theme" type="color" value="#2b7a3d"></div><div><label>Stratum port</label><input id="coin-stratum" type="number" value="3334"></div><div><label>Internal web port</label><input id="coin-web" type="number" value="8081"></div><div><label>RPC URL</label><input id="coin-rpc-url" value="http://127.0.0.1:8332"></div><div><label>RPC username</label><input id="coin-rpc-user"></div><div><label>RPC password</label><input id="coin-rpc-password" type="password"></div><div><label>Block maturity</label><input id="coin-maturity" type="number" value="100"></div><div><label>Minimum payout</label><input id="coin-minimum" value="1.00000000"></div><div><label>Pool fee %</label><input id="coin-fee" type="number" step="0.01" value="0"></div><div><label>Payout check seconds</label><input id="coin-payout-interval" type="number" value="7200"></div></div><button id="save-coin" style="margin-top:16px">Save coin draft</button><div id="coin-message"></div></details><div id="coin-plan"></div></div></section>
<section><h2>Pool fee</h2><div class="admin-card"><div class="form-row"><div><label for="fee">Pool fee percent</label><input id="fee" type="number" min="0" max="100" step="0.01"></div><button id="save-fee">Save fee</button></div><p class="muted">Future pool fees are credited automatically to the internal Pool Treasury. Existing block allocations are never recalculated.</p><div id="fee-message"></div></div></section>
<section><h2>Pool Treasury</h2><div class="admin-card"><div class="admin-grid"><div><span class="muted">Treasury Address</span><strong style="font-size:14px"><code id="treasury-address">—</code></strong></div><div><span class="muted">Current Spendable</span><strong id="treasury-balance">0.00 YERB</strong></div></div><div class="admin-grid treasury-audit" id="treasury-audit"><div class="admin-card">Loading accounting…</div></div><h3 style="margin-top:22px">Treasury Activity</h3><div class="muted">Fee credits and maturity transitions from the accounting ledger, combined with recorded treasury withdrawals.</div><div id="treasury-activity"></div><div class="form-row" style="margin-top:24px"><div><label for="withdraw-address">Withdraw to</label><input id="withdraw-address" class="wide" type="text" autocomplete="off" spellcheck="false" placeholder="Destination YERB address"></div><div><label for="withdraw-amount">Amount (YERB)</label><input id="withdraw-amount" type="number" min="0.00000001" step="0.00000001"></div><button id="withdraw">Withdraw</button></div><p class="muted">Withdrawals are signed and broadcast by the pool's Yerbas wallet. The treasury private key is never stored in the web application.</p><div id="withdraw-message"></div><h3 style="margin-top:22px">Withdrawal History</h3><div id="treasury-history"></div></div></section>
<section><h2>Payout configuration</h2><div class="admin-grid" id="payouts"></div></section>
<script>
const coin=v=>Number(v||0).toFixed(8)+' YERB';
const atomicCoin=v=>(Number(v||0)/1e8).toFixed(8)+' YERB';
const when=t=>t?new Date(Number(t)*1000).toLocaleString():'—';
function renderHistory(items){if(!items?.length)return'<p class="muted">No treasury withdrawals yet.</p>';return `<table><thead><tr><th>Time</th><th>Destination</th><th>Amount</th><th>Status</th><th>TXID</th></tr></thead><tbody>${items.map(x=>`<tr><td>${when(x.created_at)}</td><td><code>${x.destination}</code></td><td>${atomicCoin(x.amount_atomic)}</td><td>${x.status}</td><td>${x.txid?`<code>${x.txid}</code>`:'—'}</td></tr>`).join('')}</tbody></table>`}
function renderActivity(items){if(!items?.length)return'<p class="muted">No treasury accounting activity yet.</p>';return `<table><thead><tr><th>Time</th><th>Type</th><th>Amount</th><th>Block / TX</th><th>Note</th></tr></thead><tbody>${items.map(x=>{const amount=Number(x.amount_atomic||0),cls=amount>0?'amount-positive':amount<0?'amount-negative':'';const ref=x.block_height?`Block ${x.block_height}`:x.txid?`<code>${x.txid}</code>`:'—';return `<tr><td>${when(x.ts)}</td><td>${x.type||'—'}${x.status?` <span class="muted">(${x.status})</span>`:''}</td><td class="${cls}">${amount>0?'+':''}${atomicCoin(amount)}</td><td>${ref}</td><td>${x.note||'—'}</td></tr>`}).join('')}</tbody></table>`}
async function load(){const r=await fetch('/api/admin/settings',{cache:'no-store'});if(!r.ok)throw new Error(await r.text());const x=await r.json();document.getElementById('fee').value=Number(x.pool_fee_percent||0).toFixed(2);const s=x.summary||{},w=x.wallet||{},t=x.treasury||{};document.getElementById('status').innerHTML=`<div class="admin-card"><span class="muted">Wallet Balance</span><strong>${Number(w.balance||0).toFixed(2)} YERB</strong></div><div class="admin-card"><span class="muted">Immature Wallet</span><strong>${Number(w.immature_balance||0).toFixed(2)} YERB</strong></div><div class="admin-card"><span class="muted">Active Workers</span><strong>${s.workers?.active_workers??0}</strong></div><div class="admin-card"><span class="muted">Pending Blocks</span><strong>${s.blocks?.pending??0}</strong></div><div class="admin-card"><span class="muted">Total Paid</span><strong>${(Number(s.payouts?.paid_atomic||0)/1e8).toFixed(2)} YERB</strong></div>`;document.getElementById('treasury-address').textContent=t.address||'—';document.getElementById('treasury-balance').textContent=coin(t.balance);document.getElementById('treasury-audit').innerHTML=`<div class="admin-card"><span class="muted">Total Fees Earned</span><strong>${atomicCoin(t.total_fees_earned_atomic)}</strong></div><div class="admin-card"><span class="muted">Immature Fees</span><strong>${atomicCoin(t.immature_fees_atomic)}</strong></div><div class="admin-card"><span class="muted">Mature Fees Earned</span><strong>${atomicCoin(t.mature_fees_earned_atomic)}</strong></div><div class="admin-card"><span class="muted">Total Withdrawn</span><strong>${atomicCoin(t.total_withdrawn_atomic)}</strong></div><div class="admin-card"><span class="muted">Current Spendable</span><strong>${coin(t.balance)}</strong></div>`;document.getElementById('treasury-activity').innerHTML=renderActivity(t.activity);document.getElementById('treasury-history').innerHTML=renderHistory(t.history);document.getElementById('payouts').innerHTML=`<div class="admin-card"><span class="muted">Minimum Payout</span><strong>${x.minimum_payout} YERB</strong></div><div class="admin-card"><span class="muted">Payment Check</span><strong>${x.check_interval_seconds}s</strong></div><div class="admin-card"><span class="muted">Coinbase Maturity</span><strong>${x.coinbase_maturity} blocks</strong></div>`;}
document.getElementById('save-fee').onclick=async()=>{const message=document.getElementById('fee-message');message.className='';message.textContent='Saving…';try{const fee=Number(document.getElementById('fee').value);const r=await fetch('/api/admin/settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({pool_fee_percent:fee})});const x=await r.json();if(!r.ok)throw new Error(x.error||'Save failed');message.className='notice';message.textContent=`Pool fee updated to ${Number(x.pool_fee_percent).toFixed(2)}%. Applies to the next block.`;await load();}catch(e){message.className='error';message.textContent=e.message;}};
document.getElementById('withdraw').onclick=async()=>{const message=document.getElementById('withdraw-message');message.className='';message.textContent='Broadcasting withdrawal…';try{const destination=document.getElementById('withdraw-address').value.trim();const amount=document.getElementById('withdraw-amount').value;const r=await fetch('/api/admin/treasury/withdraw',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({destination,amount})});const x=await r.json();if(!r.ok)throw new Error(x.error||'Withdrawal failed');message.className='notice';message.textContent=`Withdrawal sent. TXID: ${x.txid}`;document.getElementById('withdraw-amount').value='';await load();}catch(e){message.className='error';message.textContent=e.message;}};
load().catch(e=>{document.getElementById('status').innerHTML=`<div class="admin-card error">${e.message}</div>`});
</script><script src="/admin_coins.js?v=1"></script></main></body></html>"""


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

    def _read_json(self):
        length = min(max(int(self.headers.get("Content-Length", "0")), 0), 65536)
        return json.loads(self.rfile.read(length).decode("utf-8") or "{}")

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
        if path == "/api/admin/coins":
            if not self._require_admin():
                return
            return self.send_json({"coins": load_registry()})
        if path.startswith("/api/admin/coins/") and path.endswith("/plan"):
            if not self._require_admin():
                return
            slug = unquote(path[len("/api/admin/coins/"):-len("/plan")]).strip("/")
            coin = next((item for item in load_registry() if item.get("slug") == slug), None)
            return self.send_json(deployment_plan(coin)) if coin else self.send_json({"error": "coin not found"}, 404)
        return super().do_GET()

    def do_POST(self):
        path = urlparse(self.path).path
        if not self._require_admin():
            return
        try:
            payload = self._read_json()
            if path == "/api/admin/settings":
                if "pool_fee_percent" not in payload:
                    return self.send_json({"error": "pool_fee_percent is required"}, 400)
                set_pool_fee_percent(CFG, float(payload["pool_fee_percent"]), persist_config=True)
                return self.send_json({"ok": True, "pool_fee_percent": get_pool_fee_percent(CFG)})
            if path == "/api/admin/treasury/withdraw":
                txid = _withdraw_treasury(payload.get("destination"), payload.get("amount"))
                return self.send_json({"ok": True, "txid": txid})
            if path == "/api/admin/coins":
                return self.send_json(save_coin(payload), 201)
            if path.startswith("/api/admin/coins/") and path.endswith("/activation"):
                slug = unquote(path[len("/api/admin/coins/"):-len("/activation")]).strip("/")
                coin = next((item for item in load_registry() if item.get("slug") == slug), None)
                if not coin:
                    return self.send_json({"error": "coin not found"}, 404)
                return self.send_json({"ok": True, "command": activation_command(coin, payload.get("email")),
                    "note": "Run this command on the pool server after DNS points to it. Certbot will issue and activate HTTPS for this subdomain."})
            return self.send_error(404)
        except (ValueError, TypeError, json.JSONDecodeError, ArithmeticError) as exc:
            return self.send_json({"error": str(exc)}, 400)
        except Exception as exc:
            return self.send_json({"error": str(exc)}, 500)


if __name__ == "__main__":
    _ensure_treasury_history_table()
    print(f"YERB Pool web/admin listening on http://{live.base.HOST}:{live.base.PORT}")
    ThreadingHTTPServer((live.base.HOST, live.base.PORT), AdminHandler).serve_forever()

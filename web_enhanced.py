#!/usr/bin/env python3
"""Additive health/diagnostics layer for the existing YERB Pool dashboard.

This wrapper deliberately reuses the production AdminHandler unchanged for all
existing routes and POST actions. Only new read-only GET endpoints and a small
public status script are added here.
"""

import socket
import time
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import web_admin as admin
from yerbpool.admin_settings import get_pool_fee_percent, get_treasury_address
from yerbpool.diagnostics import accounting_integrity, read_payout_status


ROOT = Path(__file__).resolve().parent
_base_summary = admin.live.api_summary
_base_public_settings = admin._public_settings

# LiveHandler injects LUCK_SCRIPT into the existing page. Appending one script
# here avoids modifying the working dashboard renderer or admin implementation.
if "/pool_status.js" not in admin.live.base.LUCK_SCRIPT:
    admin.live.base.LUCK_SCRIPT += '<script src="/pool_status.js?v=1"></script>'


def effective_public_settings():
    """Expose the payout interval the scheduler actually uses."""
    result = _base_public_settings()
    interval = int(result.get("check_interval_seconds", 7200))
    if interval == 60:
        interval = 7200
    result["check_interval_seconds"] = interval
    result["block_check_interval_seconds"] = int(
        admin.CFG.get("payouts", {}).get("block_check_interval_seconds", 60)
    )
    return result


# web_admin resolves this module-global function at request time, so the admin
# panel and /api/pool-settings now report the same effective scheduler values.
admin._public_settings = effective_public_settings


def public_summary():
    """Keep the internal treasury out of public miner/account totals."""
    result = _base_summary()
    treasury = get_treasury_address(admin.CFG)
    if not treasury:
        return result

    try:
        with admin.live.base.db() as con:
            row = admin.live.base.one(
                con,
                """SELECT balance_atomic,immature_balance_atomic
                   FROM accounts WHERE address=?""",
                (treasury,),
            )
        accounts = result.get("accounts", {})
        if row:
            accounts["accounts"] = max(0, int(accounts.get("accounts") or 0) - 1)
            accounts["miner_balance_atomic"] = max(
                0,
                int(accounts.get("miner_balance_atomic") or 0)
                - int(row.get("balance_atomic") or 0),
            )
            accounts["immature_atomic"] = max(
                0,
                int(accounts.get("immature_atomic") or 0)
                - int(row.get("immature_balance_atomic") or 0),
            )
    except Exception:
        # Public summary must remain available even if this cosmetic exclusion
        # cannot be calculated during a transient database problem.
        pass
    return result


# Patch the same module-global function used by web.py's inherited Handler.
admin.live.api_summary = public_summary
admin.live.base.api_summary = public_summary


def _stratum_online():
    cfg = admin.CFG.get("stratum", {})
    host = str(cfg.get("host", "0.0.0.0"))
    port = int(cfg.get("port", 3333))
    probe_host = "127.0.0.1" if host in ("0.0.0.0", "::", "") else host
    started = time.perf_counter()
    try:
        with socket.create_connection((probe_host, port), timeout=0.35):
            pass
        return True, round((time.perf_counter() - started) * 1000, 2)
    except Exception:
        return False, None


def _wallet_health():
    started = time.perf_counter()
    try:
        info = admin.live.base.rpc_call("getblockchaininfo")
        return {
            "online": True,
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            "blocks": int(info.get("blocks", 0)) if isinstance(info, dict) else None,
            "headers": int(info.get("headers", 0)) if isinstance(info, dict) else None,
            "verification_progress": float(info.get("verificationprogress", 0)) if isinstance(info, dict) else None,
        }
    except Exception as exc:
        return {
            "online": False,
            "latency_ms": None,
            "error": str(exc)[:200],
        }


def _database_health():
    now = int(time.time())
    try:
        with admin.live.base.db() as con:
            con.execute("SELECT 1").fetchone()
            last_share = admin.live.base.one(
                con,
                "SELECT COALESCE(MAX(ts),0) last_share_at FROM shares",
            )
            last_payout = admin.live.base.one(
                con,
                """SELECT id,sent_at,txid,total_atomic,status
                   FROM payouts WHERE status='sent'
                   ORDER BY id DESC LIMIT 1""",
            )
        last_share_at = int(last_share.get("last_share_at") or 0)
        return {
            "online": True,
            "last_share_at": last_share_at,
            "last_share_age_seconds": max(0, now - last_share_at) if last_share_at else None,
            "last_successful_payout": last_payout or None,
        }
    except Exception as exc:
        return {"online": False, "error": str(exc)[:200]}


def api_health():
    stratum_online, stratum_latency = _stratum_online()
    wallet = _wallet_health()
    database = _database_health()
    try:
        integrity = accounting_integrity(admin.live.base.DB_PATH)
    except Exception as exc:
        integrity = {"ok": False, "error": str(exc)[:200]}

    payout = read_payout_status(ROOT)
    ok = bool(stratum_online and wallet.get("online") and database.get("online"))
    return {
        "ok": ok,
        "checked_at": int(time.time()),
        "stratum": {
            "online": stratum_online,
            "latency_ms": stratum_latency,
            "endpoint": "stratum+tcp://pool.yerbas.org:3333",
        },
        "wallet": wallet,
        "database": database,
        "accounting": integrity,
        "payout_scheduler": payout,
    }


def api_pool():
    summary = public_summary()
    luck = admin.live.api_luck()
    payout_cfg = effective_public_settings()
    payout_status = read_payout_status(ROOT)
    interval = int(payout_status.get("interval_seconds") or payout_cfg.get("check_interval_seconds", 7200))

    return {
        "name": "YERB Pool",
        "algorithm": "GhostRider",
        "stratum": "stratum+tcp://pool.yerbas.org:3333",
        "pool_address": str(admin.CFG.get("pool_address", "") or ""),
        "pool_fee_percent": get_pool_fee_percent(admin.CFG),
        "minimum_payout": str(payout_cfg.get("minimum_payout", "1.00000000")),
        "payout_interval_seconds": interval,
        "next_payout_check_at": int(payout_status.get("next_check_at") or 0),
        "hashrate": float(luck.get("pool_hashrate") or 0),
        "hashrate_window_seconds": int(luck.get("hashrate_window_seconds") or admin.live.HASHRATE_WINDOW),
        "network_difficulty": luck.get("network_difficulty"),
        "miners": int(summary.get("accounts", {}).get("accounts") or 0),
        "active_workers": int(summary.get("workers", {}).get("active_workers") or 0),
        "blocks_found": int(summary.get("blocks", {}).get("blocks") or 0),
        "pending_blocks": int(summary.get("blocks", {}).get("pending") or 0),
        "total_paid_atomic": int(summary.get("payouts", {}).get("paid_atomic") or 0),
    }


class EnhancedHandler(admin.AdminHandler):
    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/health":
            return self.send_json(api_health())
        if path == "/api/pool":
            return self.send_json(api_pool())
        if path == "/api/accounting-integrity":
            try:
                return self.send_json(accounting_integrity(admin.live.base.DB_PATH))
            except Exception as exc:
                return self.send_json({"ok": False, "error": str(exc)}, 500)
        return super().do_GET()


if __name__ == "__main__":
    print(
        f"YERB Pool web/admin listening on http://{admin.live.base.HOST}:{admin.live.base.PORT} "
        "(health diagnostics enabled)"
    )
    ThreadingHTTPServer((admin.live.base.HOST, admin.live.base.PORT), EnhancedHandler).serve_forever()

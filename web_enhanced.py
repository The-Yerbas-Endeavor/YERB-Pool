#!/usr/bin/env python3
"""Additive health/diagnostics layer for the existing YERB Pool dashboard."""

import socket
import time
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import web_admin as admin
from yerbpool.admin_settings import get_pool_fee_percent, get_treasury_address
from yerbpool.diagnostics import accounting_integrity, read_payout_status


ROOT = Path(__file__).resolve().parent
_base_summary = admin.live.api_summary
_base_public_settings = admin._public_settings
_health_cache = None
_health_cache_at = 0.0
_pool_cache = None
_pool_cache_at = 0.0
CACHE_SECONDS = 10.0

# Public Configure page uses the normal dashboard shell.
admin.live.base.FRONTEND_ROUTES.add("/configure")

# LiveHandler injects LUCK_SCRIPT before reward_labels.js. Configure is loaded
# first so its hidden compatibility marker prevents the legacy home command
# injector from recreating Prebuilt Miner Commands on the dashboard.
if "/configure_page.js" not in admin.live.base.LUCK_SCRIPT:
    admin.live.base.LUCK_SCRIPT += '<script src="/configure_page.js?v=1"></script>'
if "/pool_status.js" not in admin.live.base.LUCK_SCRIPT:
    admin.live.base.LUCK_SCRIPT += '<script src="/pool_status.js?v=2"></script>'
if "/block_presentation.js" not in admin.live.base.LUCK_SCRIPT:
    admin.live.base.LUCK_SCRIPT += '<script src="/block_presentation.js?v=1"></script>'
if "/payout_presentation.js" not in admin.live.base.LUCK_SCRIPT:
    admin.live.base.LUCK_SCRIPT += '<script src="/payout_presentation.js?v=3"></script>'
if "/hashrate_chart_fast.js" not in admin.live.base.LUCK_SCRIPT:
    admin.live.base.LUCK_SCRIPT += '<script src="/hashrate_chart_fast.js?v=2"></script>'


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
        pass
    return result


admin.live.api_summary = public_summary
admin.live.base.api_summary = public_summary


def api_blocks_enhanced(status=None, limit=100):
    """Return block data plus the already-stored finder identity."""
    with admin.live.base.db() as con:
        sql = """SELECT
                    b.id,b.height,b.block_hash,b.status,b.confirmations,
                    b.reward_atomic,b.network_reward_atomic,b.pool_fee_atomic,
                    b.submitted_at,b.confirmed_at,b.credited_at,b.maturity_height,
                    b.finder_account_id,b.finder_worker_id,
                    a.address AS finder_address,
                    w.name AS finder_worker
                 FROM blocks b
                 LEFT JOIN accounts a ON a.id=b.finder_account_id
                 LEFT JOIN workers w ON w.id=b.finder_worker_id"""
        params = []
        if status:
            if status == "pending":
                sql += " WHERE b.status IN ('submitted','confirmed')"
            else:
                sql += " WHERE b.status=?"
                params.append(status)
        sql += " ORDER BY b.id DESC LIMIT ?"
        params.append(min(max(int(limit), 1), 500))
        return admin.live.base.rows(con, sql, params)


def api_payouts_enhanced(limit=100):
    """Return at most 100 payout batches with miner recipient counts."""
    with admin.live.base.db() as con:
        return admin.live.base.rows(
            con,
            """SELECT
                   p.id,p.created_at,p.sent_at,p.txid,p.total_atomic,
                   p.fee_atomic,p.status,p.error,
                   COUNT(pi.id) AS recipient_count
               FROM payouts p
               LEFT JOIN payout_items pi ON pi.payout_id=p.id
               GROUP BY p.id
               ORDER BY p.id DESC
               LIMIT ?""",
            (min(max(int(limit), 1), 100),),
        )


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
        return {"online": False, "latency_ms": None, "error": str(exc)[:200]}


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


def api_health(force=False):
    global _health_cache, _health_cache_at
    now_mono = time.monotonic()
    if not force and _health_cache is not None and now_mono - _health_cache_at < CACHE_SECONDS:
        return _health_cache

    stratum_online, stratum_latency = _stratum_online()
    wallet = _wallet_health()
    database = _database_health()
    try:
        integrity = accounting_integrity(admin.live.base.DB_PATH)
    except Exception as exc:
        integrity = {"ok": False, "error": str(exc)[:200]}

    payout = read_payout_status(ROOT)
    ok = bool(stratum_online and wallet.get("online") and database.get("online"))
    result = {
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
    _health_cache = result
    _health_cache_at = now_mono
    return result


def api_pool(force=False):
    global _pool_cache, _pool_cache_at
    now_mono = time.monotonic()
    if not force and _pool_cache is not None and now_mono - _pool_cache_at < CACHE_SECONDS:
        return _pool_cache

    summary = public_summary()
    luck = admin.live.api_luck()
    payout_cfg = effective_public_settings()
    payout_status = read_payout_status(ROOT)
    interval = int(
        payout_status.get("interval_seconds")
        or payout_cfg.get("check_interval_seconds", 7200)
    )

    result = {
        "name": "YERB Pool",
        "algorithm": "GhostRider",
        "stratum": "stratum+tcp://pool.yerbas.org:3333",
        "pool_address": str(admin.CFG.get("pool_address", "") or ""),
        "pool_fee_percent": get_pool_fee_percent(admin.CFG),
        "minimum_payout": str(payout_cfg.get("minimum_payout", "1.00000000")),
        "payout_interval_seconds": interval,
        "next_payout_check_at": int(payout_status.get("next_check_at") or 0),
        "hashrate": float(luck.get("pool_hashrate") or 0),
        "hashrate_window_seconds": int(
            luck.get("hashrate_window_seconds") or admin.live.HASHRATE_WINDOW
        ),
        "network_difficulty": luck.get("network_difficulty"),
        "miners": int(summary.get("accounts", {}).get("accounts") or 0),
        "active_workers": int(summary.get("workers", {}).get("active_workers") or 0),
        "blocks_found": int(summary.get("blocks", {}).get("blocks") or 0),
        "pending_blocks": int(summary.get("blocks", {}).get("pending") or 0),
        "total_paid_atomic": int(summary.get("payouts", {}).get("paid_atomic") or 0),
    }
    _pool_cache = result
    _pool_cache_at = now_mono
    return result


class EnhancedHandler(admin.AdminHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/api/health":
            return self.send_json(api_health())
        if path == "/api/pool":
            return self.send_json(api_pool())
        if path == "/api/accounting-integrity":
            try:
                return self.send_json(accounting_integrity(admin.live.base.DB_PATH))
            except Exception as exc:
                return self.send_json({"ok": False, "error": str(exc)}, 500)
        if path == "/api/blocks":
            query = parse_qs(parsed.query)
            try:
                return self.send_json(
                    api_blocks_enhanced(
                        (query.get("status") or [None])[0],
                        (query.get("limit") or [100])[0],
                    )
                )
            except Exception as exc:
                return self.send_json({"error": str(exc)}, 500)
        if path == "/api/payouts":
            query = parse_qs(parsed.query)
            try:
                return self.send_json(
                    api_payouts_enhanced((query.get("limit") or [100])[0])
                )
            except Exception as exc:
                return self.send_json({"error": str(exc)}, 500)
        return super().do_GET()


if __name__ == "__main__":
    print(
        f"YERB Pool web/admin listening on http://{admin.live.base.HOST}:{admin.live.base.PORT} "
        "(health diagnostics enabled)"
    )
    ThreadingHTTPServer(
        (admin.live.base.HOST, admin.live.base.PORT), EnhancedHandler
    ).serve_forever()

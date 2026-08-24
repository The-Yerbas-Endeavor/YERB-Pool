#!/usr/bin/env python3
"""Additive health/diagnostics layer for the existing YERB Pool dashboard."""

import socket
import time
from decimal import Decimal
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

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
COIN = 100_000_000
API_VERSION = "1.0.0"
MAX_PAGE_SIZE = 500

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
    admin.live.base.LUCK_SCRIPT += '<script src="/payout_presentation.js?v=4"></script>'
if "/worker_detail.js" not in admin.live.base.LUCK_SCRIPT:
    admin.live.base.LUCK_SCRIPT += '<script src="/worker_detail.js?v=1"></script>'


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
    if treasury:
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

    # Additive fields keep the existing dashboard contract intact while making
    # /api/summary useful as a complete pool-monitoring response.
    try:
        luck = admin.live.api_luck()
        settings = effective_public_settings()
        result["coin"] = {
            "name": "Yerbas",
            "symbol": "YERB",
            "algorithm": "GhostRider",
            "network": "mainnet",
            "decimals": 8,
        }
        result["pool"] = {
            "address": result.get("pool_address", ""),
            "fee_percent": result.get("pool_fee_percent", 0),
            "payout_scheme": "PROP",
            "minimum_payout": str(settings.get("minimum_payout", "1.00000000")),
            "hashrate": float(luck.get("pool_hashrate") or 0),
            "hashrate_window_seconds": int(luck.get("hashrate_window_seconds") or 120),
            "stratum": "stratum+tcp://pool.yerbas.org:3333",
        }
        result["network"] = {
            "difficulty": luck.get("network_difficulty"),
            "hashrate": luck.get("network_hashrate"),
        }
        result["round"] = {
            "started_at": luck.get("round_start"),
            "duration_seconds": luck.get("round_seconds"),
            "accepted_shares": luck.get("round_accepted_shares"),
            "accepted_difficulty": luck.get("round_stratum_difficulty"),
            "effort_percent": luck.get("round_effort_percent"),
            "chance_percent": luck.get("chance_percent"),
            "estimated_block_seconds": luck.get("eta_seconds"),
            "last_pool_block_height": luck.get("last_block_height"),
        }
    except Exception:
        # Summary remains available during a transient wallet RPC outage.
        pass
    result["generated_at"] = int(time.time())
    return result


admin.live.api_summary = public_summary
admin.live.base.api_summary = public_summary


def api_blocks_enhanced(status=None, limit=100, offset=0):
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
        sql += " ORDER BY b.id DESC LIMIT ? OFFSET ?"
        params.extend((min(max(int(limit), 1), 500), max(int(offset), 0)))
        result = admin.live.base.rows(con, sql, params)
    maturity = max(1, int(admin.CFG.get("payouts", {}).get("coinbase_maturity", 100)))
    explorer = str(admin.CFG.get("explorer_url", "https://explorer.yerbas.org")).rstrip("/")
    for block in result:
        confirmations = int(block.get("confirmations") or 0)
        status_name = str(block.get("status") or "")
        block["normalized_status"] = "pending" if status_name in ("submitted", "confirmed") else status_name
        block["confirmation_progress"] = min(1.0, confirmations / maturity)
        block["reward"] = _coin_string(block.get("reward_atomic"))
        block["network_reward"] = _coin_string(block.get("network_reward_atomic"))
        block["pool_fee"] = _coin_string(block.get("pool_fee_atomic"))
        if block.get("block_hash"):
            block["explorer_url"] = f"{explorer}/block/{block['block_hash']}"
    return result


def api_payouts_enhanced(limit=100, offset=0):
    """Return one bounded page of payout batches with recipient counts."""
    with admin.live.base.db() as con:
        result = admin.live.base.rows(
            con,
            """SELECT
                   p.id,p.created_at,p.sent_at,p.txid,p.total_atomic,
                   p.fee_atomic,p.status,p.error,
                   COUNT(pi.id) AS recipient_count
               FROM payouts p
               LEFT JOIN payout_items pi ON pi.payout_id=p.id
               GROUP BY p.id
               ORDER BY p.id DESC
               LIMIT ? OFFSET ?""",
            (min(max(int(limit), 1), 500), max(int(offset), 0)),
        )
    explorer = str(admin.CFG.get("explorer_url", "https://explorer.yerbas.org")).rstrip("/")
    for payout in result:
        payout["total"] = _coin_string(payout.get("total_atomic"))
        payout["fee"] = _coin_string(payout.get("fee_atomic"))
        if payout.get("txid"):
            payout["explorer_url"] = f"{explorer}/tx/{payout['txid']}"
    return result


def api_payout_detail(payout_id):
    """Return one payout batch and every recipient without a history cutoff."""
    with admin.live.base.db() as con:
        payout = admin.live.base.one(
            con,
            """SELECT p.id,p.created_at,p.sent_at,p.txid,p.total_atomic,
                      p.fee_atomic,p.status,p.error,COUNT(pi.id) recipient_count
               FROM payouts p LEFT JOIN payout_items pi ON pi.payout_id=p.id
               WHERE p.id=? GROUP BY p.id""",
            (int(payout_id),),
        )
        if not payout:
            return None
        payout["recipients"] = admin.live.base.rows(
            con,
            """SELECT address,amount_atomic FROM payout_items
               WHERE payout_id=? ORDER BY amount_atomic DESC,address""",
            (int(payout_id),),
        )
    explorer = str(admin.CFG.get("explorer_url", "https://explorer.yerbas.org")).rstrip("/")
    payout["total"] = _coin_string(payout.get("total_atomic"))
    payout["fee"] = _coin_string(payout.get("fee_atomic"))
    payout["explorer_url"] = f"{explorer}/tx/{payout['txid']}" if payout.get("txid") else None
    for recipient in payout["recipients"]:
        recipient["amount"] = _coin_string(recipient.get("amount_atomic"))
    return payout


def _coin_string(value):
    """Return an exact eight-decimal YERB amount without binary float loss."""
    return format(Decimal(int(value or 0)) / Decimal(COIN), ".8f")


def _bounded_int(value, default, minimum=0, maximum=MAX_PAGE_SIZE):
    try:
        value = int(value)
    except (TypeError, ValueError):
        value = int(default)
    return min(max(value, minimum), maximum)


def _page(items, total, limit, offset):
    return {
        "items": items,
        "pagination": {
            "limit": limit,
            "offset": offset,
            "total": int(total or 0),
            "has_more": offset + len(items) < int(total or 0),
        },
        "generated_at": int(time.time()),
    }


def api_meta():
    return {
        "name": "YERB Pool API",
        "version": API_VERSION,
        "coin": "YERB",
        "algorithm": "GhostRider",
        "decimals": 8,
        "legacy_base": "/api",
        "versioned_base": "/api/v1",
        "generated_at": int(time.time()),
    }


def api_help():
    return {
        **api_meta(),
        "notes": [
            "Legacy list endpoints return arrays for dashboard compatibility.",
            "Versioned list endpoints return items plus pagination metadata.",
            "Coin amounts include exact *_atomic integers and decimal strings where applicable.",
        ],
        "endpoints": [
            {"method": "GET", "path": "/api/summary", "description": "Complete pool, network, round and accounting summary"},
            {"method": "GET", "path": "/api/health", "description": "Stratum, wallet, database and accounting health"},
            {"method": "GET", "path": "/api/luck", "description": "Current round effort, chance and block ETA"},
            {"method": "GET", "path": "/api/hashrate/chart", "parameters": "hours,bucket"},
            {"method": "GET", "path": "/api/v1/blocks", "parameters": "status,limit,offset"},
            {"method": "GET", "path": "/api/v1/payouts", "parameters": "limit,offset"},
            {"method": "GET", "path": "/api/payouts/{id}", "description": "Payout batch and complete recipient list"},
            {"method": "GET", "path": "/api/v1/miners", "parameters": "limit,offset"},
            {"method": "GET", "path": "/api/v1/workers", "parameters": "limit,offset"},
            {"method": "GET", "path": "/api/v1/shares", "parameters": "status,address,limit,offset"},
            {"method": "GET", "path": "/api/account/{address}/summary"},
            {"method": "GET", "path": "/api/account/{address}/payments", "parameters": "limit,offset"},
            {"method": "GET", "path": "/api/account/{address}/earnings/daily", "parameters": "days,limit,offset"},
            {"method": "GET", "path": "/api/account/{address}/balance-changes", "parameters": "limit,offset"},
            {"method": "GET", "path": "/api/account/{address}/blocks", "parameters": "limit,offset"},
            {"method": "GET", "path": "/api/account/{address}/performance", "parameters": "hours,bucket"},
            {"method": "GET", "path": "/api/worker/{id}/performance", "parameters": "hours,bucket"},
            {"method": "GET", "path": "/api/worker/{id}/detail", "parameters": "hours,bucket,share_limit"},
        ],
    }


def _account_identity(con, address):
    return admin.live.base.one(
        con,
        """SELECT id,address,created_at,updated_at,balance_atomic,
                  immature_balance_atomic,total_earned_atomic,total_paid_atomic,
                  minimum_payout_atomic,enabled
           FROM accounts WHERE address=?""",
        (address,),
    )


def api_account_summary(address):
    now = int(time.time())
    current_cutoff = now - admin.live.HASHRATE_WINDOW
    with admin.live.base.db() as con:
        account = _account_identity(con, address)
        if not account:
            return None
        stats = admin.live.base.one(
            con,
            """SELECT
                   COALESCE(SUM(CASE WHEN s.accepted=1 THEN 1 ELSE 0 END),0) accepted_shares,
                   COALESCE(SUM(CASE WHEN s.accepted=0 THEN 1 ELSE 0 END),0) rejected_shares,
                   COALESCE(SUM(CASE WHEN s.accepted=1 AND s.ts>=? THEN s.difficulty ELSE 0 END),0) current_diff,
                   COALESCE(SUM(CASE WHEN s.accepted=1 AND s.ts>=? THEN s.difficulty ELSE 0 END),0) diff_1h,
                   COALESCE(SUM(CASE WHEN s.accepted=1 AND s.ts>=? THEN s.difficulty ELSE 0 END),0) diff_24h,
                   COALESCE(MAX(s.ts),0) last_share_at
               FROM shares s WHERE s.account_id=?""",
            (current_cutoff, now - 3600, now - 86400, account["id"]),
        )
        workers = admin.live.base.rows(
            con,
            """SELECT id,name,created_at,last_seen_at,accepted_shares,rejected_shares
               FROM workers WHERE account_id=? ORDER BY name""",
            (account["id"],),
        )
        paid24 = admin.live.base.one(
            con,
            """SELECT COALESCE(SUM(pi.amount_atomic),0) paid_atomic
               FROM payout_items pi JOIN payouts p ON p.id=pi.payout_id
               WHERE pi.account_id=? AND p.status='sent' AND p.sent_at>=?""",
            (account["id"], now - 86400),
        )
    accepted = int(stats.get("accepted_shares") or 0)
    rejected = int(stats.get("rejected_shares") or 0)
    total = accepted + rejected
    account.update({
        "balance": _coin_string(account.get("balance_atomic")),
        "immature_balance": _coin_string(account.get("immature_balance_atomic")),
        "total_earned": _coin_string(account.get("total_earned_atomic")),
        "total_paid": _coin_string(account.get("total_paid_atomic")),
        "paid_24h_atomic": int(paid24.get("paid_atomic") or 0),
        "paid_24h": _coin_string(paid24.get("paid_atomic")),
        "accepted_shares": accepted,
        "rejected_shares": rejected,
        "rejection_percent": (rejected / total * 100.0) if total else 0.0,
        "hashrate": admin.live._hashrate_from_diff(stats.get("current_diff")),
        "hashrate_1h": admin.live._hashrate_from_diff(stats.get("diff_1h"), 3600),
        "hashrate_24h": admin.live._hashrate_from_diff(stats.get("diff_24h"), 86400),
        "hashrate_window_seconds": admin.live.HASHRATE_WINDOW,
        "last_share_at": int(stats.get("last_share_at") or 0),
        "active_workers": sum(1 for worker in workers if int(worker.get("last_seen_at") or 0) >= current_cutoff),
        "workers": workers,
        "generated_at": now,
    })
    return account


def api_account_payments(address, limit=100, offset=0):
    with admin.live.base.db() as con:
        account = _account_identity(con, address)
        if not account:
            return None
        total = admin.live.base.one(con, "SELECT COUNT(*) total FROM payout_items WHERE account_id=?", (account["id"],)).get("total", 0)
        items = admin.live.base.rows(
            con,
            """SELECT p.id,p.created_at,p.sent_at,p.txid,p.status,p.fee_atomic,pi.amount_atomic
               FROM payout_items pi JOIN payouts p ON p.id=pi.payout_id
               WHERE pi.account_id=? ORDER BY p.id DESC LIMIT ? OFFSET ?""",
            (account["id"], limit, offset),
        )
    explorer = str(admin.CFG.get("explorer_url", "https://explorer.yerbas.org")).rstrip("/")
    for item in items:
        item["amount"] = _coin_string(item.get("amount_atomic"))
        item["explorer_url"] = f"{explorer}/tx/{item['txid']}" if item.get("txid") else None
    return _page(items, total, limit, offset)


def api_account_balance_changes(address, limit=100, offset=0):
    with admin.live.base.db() as con:
        account = _account_identity(con, address)
        if not account:
            return None
        total = admin.live.base.one(con, "SELECT COUNT(*) total FROM ledger WHERE account_id=?", (account["id"],)).get("total", 0)
        items = admin.live.base.rows(
            con,
            """SELECT id,ts,block_id,payout_id,entry_type,amount_atomic,note
               FROM ledger WHERE account_id=? ORDER BY id DESC LIMIT ? OFFSET ?""",
            (account["id"], limit, offset),
        )
    for item in items:
        item["amount"] = _coin_string(item.get("amount_atomic"))
    return _page(items, total, limit, offset)


def api_account_daily_earnings(address, days=30, limit=100, offset=0):
    days = _bounded_int(days, 30, 1, 365)
    cutoff = int(time.time()) - days * 86400
    with admin.live.base.db() as con:
        account = _account_identity(con, address)
        if not account:
            return None
        grouped = admin.live.base.rows(
            con,
            """SELECT date(ts,'unixepoch') day, SUM(amount_atomic) earned_atomic, COUNT(*) credits
               FROM ledger WHERE account_id=? AND entry_type='block_mature' AND ts>=?
               GROUP BY date(ts,'unixepoch') ORDER BY day DESC""",
            (account["id"], cutoff),
        )
    total = len(grouped)
    items = grouped[offset:offset + limit]
    for item in items:
        item["earned"] = _coin_string(item.get("earned_atomic"))
    return _page(items, total, limit, offset)


def api_account_blocks(address, limit=100, offset=0):
    with admin.live.base.db() as con:
        account = _account_identity(con, address)
        if not account:
            return None
        total = admin.live.base.one(con, "SELECT COUNT(*) total FROM blocks WHERE finder_account_id=?", (account["id"],)).get("total", 0)
        items = admin.live.base.rows(
            con,
            """SELECT id,height,block_hash,status,confirmations,reward_atomic,
                      network_reward_atomic,pool_fee_atomic,submitted_at,confirmed_at,
                      credited_at,maturity_height,finder_worker_id
               FROM blocks WHERE finder_account_id=? ORDER BY id DESC LIMIT ? OFFSET ?""",
            (account["id"], limit, offset),
        )
    for item in items:
        item["reward"] = _coin_string(item.get("reward_atomic"))
    return _page(items, total, limit, offset)


def api_performance(address=None, worker_id=None, hours=24, bucket_seconds=600):
    hours = _bounded_int(hours, 24, 1, 168)
    bucket_seconds = _bounded_int(bucket_seconds, 600, 60, 3600)
    bucket_seconds = max(60, (bucket_seconds // 60) * 60)
    now = int(time.time())
    end = (now // bucket_seconds) * bucket_seconds
    start = end - hours * 3600
    clauses = ["s.ts>=?", "s.ts<?"]
    params = [start, end + bucket_seconds]
    with admin.live.base.db() as con:
        if address is not None:
            account = _account_identity(con, address)
            if not account:
                return None
            clauses.append("s.account_id=?")
            params.append(account["id"])
        elif worker_id is not None:
            worker = admin.live.base.one(con, "SELECT id FROM workers WHERE id=?", (int(worker_id),))
            if not worker:
                return None
            clauses.append("s.worker_id=?")
            params.append(int(worker_id))
        raw = admin.live.base.rows(
            con,
            f"""SELECT (s.ts / ?) * ? bucket,
                       COALESCE(SUM(CASE WHEN s.accepted=1 THEN s.difficulty ELSE 0 END),0) accepted_diff,
                       COALESCE(SUM(CASE WHEN s.accepted=1 THEN 1 ELSE 0 END),0) accepted,
                       COALESCE(SUM(CASE WHEN s.accepted=0 THEN 1 ELSE 0 END),0) rejected
                FROM shares s WHERE {' AND '.join(clauses)}
                GROUP BY bucket ORDER BY bucket""",
            (bucket_seconds, bucket_seconds, *params),
        )
    by_bucket = {int(row["bucket"]): row for row in raw}
    history = []
    cursor = start
    while cursor <= end:
        row = by_bucket.get(cursor, {})
        history.append({
            "ts": cursor,
            "hashrate": admin.live._hashrate_from_diff(row.get("accepted_diff"), bucket_seconds),
            "accepted": int(row.get("accepted") or 0),
            "rejected": int(row.get("rejected") or 0),
        })
        cursor += bucket_seconds
    return {"hours": hours, "bucket_seconds": bucket_seconds, "history": history, "generated_at": now}


def api_worker_detail(worker_id, hours=24, bucket_seconds=600, share_limit=25):
    """Return the complete public worker view in one bounded response."""
    worker_id = int(worker_id)
    share_limit = _bounded_int(share_limit, 25, 1, 100)
    result = admin.live.api_worker_stats(worker_id, hours, bucket_seconds)
    if result is None:
        return None

    with admin.live.base.db() as con:
        columns = {row[1] for row in con.execute("PRAGMA table_info(shares)")}
        reason_expr = "s.rejection_reason" if "rejection_reason" in columns else "NULL AS rejection_reason"
        result["recent_shares"] = admin.live.base.rows(
            con,
            f"""SELECT s.id,s.ts,s.difficulty,s.accepted,s.block_candidate,s.hash,
                       {reason_expr}
                FROM shares s WHERE s.worker_id=? ORDER BY s.id DESC LIMIT ?""",
            (worker_id, share_limit),
        )
        if "rejection_reason" in columns:
            reasons = admin.live.base.rows(
                con,
                """SELECT COALESCE(NULLIF(TRIM(rejection_reason),''),'Unspecified') reason,
                          COUNT(*) count
                   FROM shares WHERE worker_id=? AND accepted=0
                   GROUP BY COALESCE(NULLIF(TRIM(rejection_reason),''),'Unspecified')
                   ORDER BY count DESC,reason""",
                (worker_id,),
            )
        else:
            rejected = admin.live.base.one(
                con,
                "SELECT COUNT(*) count FROM shares WHERE worker_id=? AND accepted=0",
                (worker_id,),
            )
            reasons = [{"reason": "Unspecified", "count": int(rejected.get("count") or 0)}] if rejected.get("count") else []
        result["rejection_reasons"] = reasons
        result["blocks_found"] = admin.live.base.rows(
            con,
            """SELECT id,height,block_hash,status,confirmations,submitted_at
               FROM blocks WHERE finder_worker_id=? ORDER BY id DESC LIMIT 25""",
            (worker_id,),
        )
        result["blocks_found_total"] = int(admin.live.base.one(
            con,
            "SELECT COUNT(*) count FROM blocks WHERE finder_worker_id=?",
            (worker_id,),
        ).get("count") or 0)

    history = result.get("history") or []
    result["average_hashrate"] = (
        sum(float(row.get("hashrate") or 0) for row in history) / len(history)
        if history else 0.0
    )
    result["range_accepted_shares"] = sum(int(row.get("accepted") or 0) for row in history)
    result["range_rejected_shares"] = sum(int(row.get("rejected") or 0) for row in history)
    latest_share = result["recent_shares"][0] if result["recent_shares"] else None
    result["last_share_difficulty"] = float(latest_share.get("difficulty") or 0) if latest_share else None
    result["generated_at"] = int(time.time())
    return result


def api_v1_list(resource, query):
    limit = _bounded_int((query.get("limit") or [100])[0], 100, 1, MAX_PAGE_SIZE)
    offset = _bounded_int((query.get("offset") or [0])[0], 0, 0, 1_000_000)
    status = (query.get("status") or [None])[0]
    address = (query.get("address") or [None])[0]
    with admin.live.base.db() as con:
        if resource == "blocks":
            clause = ""
            params = []
            if status == "pending":
                clause = " WHERE status IN ('submitted','confirmed')"
            elif status:
                clause = " WHERE status=?"
                params.append(status)
            total = admin.live.base.one(con, f"SELECT COUNT(*) total FROM blocks{clause}", params).get("total", 0)
            items = api_blocks_enhanced(status, limit, offset)
        elif resource == "payouts":
            total = admin.live.base.one(con, "SELECT COUNT(*) total FROM payouts").get("total", 0)
            items = api_payouts_enhanced(limit, offset)
        elif resource == "miners":
            treasury = get_treasury_address(admin.CFG)
            treasury_clause = "WHERE a.address!=?" if treasury else ""
            treasury_params = [treasury] if treasury else []
            total = admin.live.base.one(con, f"SELECT COUNT(*) total FROM accounts a {treasury_clause}", treasury_params).get("total", 0)
            items = admin.live.base.rows(
                con,
                f"""SELECT a.address,a.balance_atomic,a.immature_balance_atomic,a.total_earned_atomic,a.total_paid_atomic,
                           COUNT(w.id) worker_count,COALESCE(MAX(w.last_seen_at),0) last_seen_at,
                           COALESCE(SUM(w.accepted_shares),0) accepted_shares,
                           COALESCE(SUM(w.rejected_shares),0) rejected_shares
                    FROM accounts a LEFT JOIN workers w ON w.account_id=a.id {treasury_clause}
                    GROUP BY a.id ORDER BY last_seen_at DESC LIMIT ? OFFSET ?""",
                (*treasury_params, limit, offset),
            )
            for item in items:
                item["balance"] = _coin_string(item.get("balance_atomic"))
                item["immature_balance"] = _coin_string(item.get("immature_balance_atomic"))
                item["total_earned"] = _coin_string(item.get("total_earned_atomic"))
                item["total_paid"] = _coin_string(item.get("total_paid_atomic"))
        elif resource == "workers":
            total = admin.live.base.one(con, "SELECT COUNT(*) total FROM workers").get("total", 0)
            # Existing live worker implementation includes the canonical rolling
            # hashrate and active-state calculations.
            items = admin.live.api_workers(min(1000, limit + offset))[offset:offset + limit]
        elif resource == "shares":
            clauses = []
            params = []
            if status == "accepted": clauses.append("s.accepted=1")
            elif status == "rejected": clauses.append("s.accepted=0")
            if address:
                clauses.append("a.address=?")
                params.append(address)
            where = " WHERE " + " AND ".join(clauses) if clauses else ""
            total = admin.live.base.one(
                con,
                f"SELECT COUNT(*) total FROM shares s LEFT JOIN accounts a ON a.id=s.account_id{where}",
                params,
            ).get("total", 0)
            columns = {row[1] for row in con.execute("PRAGMA table_info(shares)")}
            reason_expr = "s.rejection_reason" if "rejection_reason" in columns else "NULL AS rejection_reason"
            items = admin.live.base.rows(
                con,
                f"""SELECT s.id,s.ts,s.worker,s.worker_id,s.job_id,s.difficulty,s.accepted,
                           s.block_candidate,s.hash,{reason_expr},a.address
                    FROM shares s LEFT JOIN accounts a ON a.id=s.account_id{where}
                    ORDER BY s.id DESC LIMIT ? OFFSET ?""",
                (*params, limit, offset),
            )
        else:
            raise ValueError("unknown API resource")
    return _page(items, total, limit, offset)


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
        query = parse_qs(parsed.query)
        if path in ("/api", "/api/", "/api/help"):
            return self.send_json(api_help())
        if path == "/api/meta":
            return self.send_json(api_meta())
        if path in ("/api/v1/summary", "/api/v1/pool"):
            return self.send_json(public_summary())
        if path == "/api/v1/health":
            return self.send_json(api_health())
        if path.startswith("/api/v1/"):
            resource = path[len("/api/v1/"):].strip("/")
            if resource in ("blocks", "payouts", "miners", "workers", "shares"):
                try:
                    return self.send_json(api_v1_list(resource, query))
                except (TypeError, ValueError) as exc:
                    return self.send_json({"error": str(exc)}, 400)

        if path.startswith("/api/account/"):
            tail = path[len("/api/account/"):].strip("/")
            suffixes = (
                ("/earnings/daily", "earnings"),
                ("/balance-changes", "balance_changes"),
                ("/performance", "performance"),
                ("/payments", "payments"),
                ("/summary", "summary"),
                ("/blocks", "blocks"),
            )
            for suffix, action in suffixes:
                if tail.endswith(suffix):
                    address = unquote(tail[:-len(suffix)]).strip()
                    if not address:
                        return self.send_json({"error": "address is required"}, 400)
                    limit = _bounded_int((query.get("limit") or [100])[0], 100, 1, MAX_PAGE_SIZE)
                    offset = _bounded_int((query.get("offset") or [0])[0], 0, 0, 1_000_000)
                    try:
                        if action == "summary": result = api_account_summary(address)
                        elif action == "payments": result = api_account_payments(address, limit, offset)
                        elif action == "earnings": result = api_account_daily_earnings(address, (query.get("days") or [30])[0], limit, offset)
                        elif action == "balance_changes": result = api_account_balance_changes(address, limit, offset)
                        elif action == "blocks": result = api_account_blocks(address, limit, offset)
                        else: result = api_performance(address=address, hours=(query.get("hours") or [24])[0], bucket_seconds=(query.get("bucket") or [600])[0])
                    except (TypeError, ValueError) as exc:
                        return self.send_json({"error": str(exc)}, 400)
                    return self.send_json(result if result is not None else {"error": "account not found"}, 200 if result is not None else 404)

        if path.startswith("/api/worker/") and path.endswith("/performance"):
            worker_id = unquote(path[len("/api/worker/"):-len("/performance")]).strip("/")
            try:
                result = api_performance(worker_id=worker_id, hours=(query.get("hours") or [24])[0], bucket_seconds=(query.get("bucket") or [600])[0])
            except (TypeError, ValueError) as exc:
                return self.send_json({"error": str(exc)}, 400)
            return self.send_json(result if result is not None else {"error": "worker not found"}, 200 if result is not None else 404)

        if path.startswith("/api/worker/") and path.endswith("/detail"):
            worker_id = unquote(path[len("/api/worker/"):-len("/detail")]).strip("/")
            try:
                result = api_worker_detail(
                    worker_id,
                    (query.get("hours") or [24])[0],
                    (query.get("bucket") or [600])[0],
                    (query.get("share_limit") or [25])[0],
                )
            except (TypeError, ValueError) as exc:
                return self.send_json({"error": str(exc)}, 400)
            return self.send_json(result if result is not None else {"error": "worker not found"}, 200 if result is not None else 404)

        if path.startswith("/api/payouts/"):
            payout_id = unquote(path[len("/api/payouts/"):]).strip("/")
            try:
                result = api_payout_detail(payout_id)
            except (TypeError, ValueError):
                return self.send_json({"error": "invalid payout id"}, 400)
            return self.send_json(result if result is not None else {"error": "payout not found"}, 200 if result is not None else 404)

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

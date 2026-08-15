"""Read-only diagnostics for the YERB Pool.

Nothing in this module mutates pool accounting.  It is intentionally kept
separate from mining, block allocation, payout, and treasury write paths so
health checks cannot change balances.
"""

import json
import sqlite3
import time
from pathlib import Path


def _connect(db_path):
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout = 3000")
    return con


def read_payout_status(root):
    path = Path(root) / "web" / "payout_status.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def accounting_integrity(db_path):
    """Reconcile stored account counters against their immutable ledger history."""
    with _connect(db_path) as con:
        totals = con.execute(
            """SELECT
                 COUNT(*) AS accounts,
                 COALESCE(SUM(balance_atomic),0) AS stored_mature,
                 COALESCE(SUM(immature_balance_atomic),0) AS stored_immature,
                 COALESCE(SUM(total_earned_atomic),0) AS stored_earned,
                 COALESCE(SUM(total_paid_atomic),0) AS stored_paid
               FROM accounts"""
        ).fetchone()

        expected = con.execute(
            """SELECT
                 COALESCE(SUM(CASE WHEN l.entry_type='block_mature' THEN l.amount_atomic ELSE 0 END),0)
                   + COALESCE(SUM(CASE WHEN l.entry_type='payout' THEN l.amount_atomic ELSE 0 END),0)
                   AS expected_mature,
                 COALESCE(SUM(CASE WHEN l.entry_type='block_mature' THEN l.amount_atomic ELSE 0 END),0)
                   AS expected_earned,
                 -COALESCE(SUM(CASE WHEN l.entry_type='payout' THEN l.amount_atomic ELSE 0 END),0)
                   AS expected_paid
               FROM ledger l"""
        ).fetchone()

        pending = con.execute(
            """SELECT COALESCE(SUM(l.amount_atomic),0) AS expected_immature
               FROM ledger l
               JOIN blocks b ON b.id=l.block_id
               WHERE l.entry_type='block_immature'
                 AND b.status IN ('submitted','confirmed')"""
        ).fetchone()

        payout_state = con.execute(
            """SELECT
                 COALESCE(SUM(CASE WHEN status='uncertain' THEN 1 ELSE 0 END),0) AS uncertain,
                 COALESCE(SUM(CASE WHEN status='broadcasting' THEN 1 ELSE 0 END),0) AS broadcasting,
                 COALESCE(SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END),0) AS failed
               FROM payouts"""
        ).fetchone()

        orphaned_pending = con.execute(
            """SELECT COUNT(*)
               FROM blocks
               WHERE status='orphan' AND confirmations>=0"""
        ).fetchone()[0]

    stored_mature = int(totals["stored_mature"] or 0)
    stored_immature = int(totals["stored_immature"] or 0)
    stored_earned = int(totals["stored_earned"] or 0)
    stored_paid = int(totals["stored_paid"] or 0)
    expected_mature = int(expected["expected_mature"] or 0)
    expected_immature = int(pending["expected_immature"] or 0)
    expected_earned = int(expected["expected_earned"] or 0)
    expected_paid = int(expected["expected_paid"] or 0)

    checks = {
        "mature_balance": stored_mature == expected_mature,
        "immature_balance": stored_immature == expected_immature,
        "total_earned": stored_earned == expected_earned,
        "total_paid": stored_paid == expected_paid,
    }

    return {
        "ok": all(checks.values()),
        "checked_at": int(time.time()),
        "checks": checks,
        "accounts": int(totals["accounts"] or 0),
        "stored": {
            "mature_atomic": stored_mature,
            "immature_atomic": stored_immature,
            "earned_atomic": stored_earned,
            "paid_atomic": stored_paid,
        },
        "expected": {
            "mature_atomic": expected_mature,
            "immature_atomic": expected_immature,
            "earned_atomic": expected_earned,
            "paid_atomic": expected_paid,
        },
        "difference": {
            "mature_atomic": stored_mature - expected_mature,
            "immature_atomic": stored_immature - expected_immature,
            "earned_atomic": stored_earned - expected_earned,
            "paid_atomic": stored_paid - expected_paid,
        },
        "payouts": {
            "uncertain": int(payout_state["uncertain"] or 0),
            "broadcasting": int(payout_state["broadcasting"] or 0),
            "failed": int(payout_state["failed"] or 0),
        },
        "orphaned_nonnegative_confirmations": int(orphaned_pending or 0),
    }

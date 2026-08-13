import time


def ensure_rejection_schema(pooldb):
    """Add rejection_reason to existing pool databases without data loss."""
    with pooldb.lock, pooldb._connect() as db:
        cols = {row[1] for row in db.execute("PRAGMA table_info(shares)")}
        if "rejection_reason" not in cols:
            db.execute("ALTER TABLE shares ADD COLUMN rejection_reason TEXT")
        db.execute(
            "CREATE INDEX IF NOT EXISTS idx_shares_rejection_reason "
            "ON shares(rejection_reason, ts)"
        )


def record_rejection(pooldb, worker, job_id, difficulty, reason, hash_hex=None):
    """Persist a rejected share attempt and increment the worker reject count.

    This mirrors PoolDB.add_share() but includes a human-readable reason. It is
    intentionally separate so older databases/classes remain compatible while
    the schema rolls forward automatically.
    """
    if not worker:
        return None
    account_id, worker_id = pooldb.get_or_create_worker(worker)
    now = int(time.time())
    with pooldb.lock, pooldb._connect() as db:
        cur = db.execute(
            """INSERT INTO shares(
                   ts,account_id,worker_id,worker,job_id,difficulty,accepted,
                   block_candidate,hash,rejection_reason
               ) VALUES(?,?,?,?,?,?,0,0,?,?)""",
            (
                now,
                account_id,
                worker_id,
                str(worker),
                str(job_id or ""),
                float(difficulty or 0.0),
                hash_hex,
                str(reason or "rejected"),
            ),
        )
        db.execute(
            "UPDATE workers SET rejected_shares=rejected_shares+1,last_seen_at=? WHERE id=?",
            (now, worker_id),
        )
        return int(cur.lastrowid)

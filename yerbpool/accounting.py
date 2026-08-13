import time

from yerbpool.database import PoolDB


class AccountingDB(PoolDB):
    """PoolDB with the round/block insert and payout locking operations used by v2."""

    def record_block(self, worker, job_id, block_hash, height, reward_atomic, round_end_share_id, maturity_height):
        account_id, worker_id = self.get_or_create_worker(worker)
        now = int(time.time())
        with self.lock, self._connect() as db:
            prev = db.execute(
                "SELECT MAX(round_end_share_id) FROM blocks "
                "WHERE round_end_share_id IS NOT NULL AND status NOT IN ('rejected','orphan')"
            ).fetchone()[0]
            round_start = (int(prev) + 1) if prev is not None else 1
            db.execute(
                """INSERT OR IGNORE INTO blocks(
                    height,block_hash,job_id,finder_account_id,finder_worker_id,reward_atomic,status,
                    submitted_at,maturity_height,round_start_share_id,round_end_share_id
                ) VALUES(?,?,?,?,?,?,'submitted',?,?,?,?)""",
                (
                    int(height), block_hash, job_id, account_id, worker_id,
                    int(reward_atomic), now, int(maturity_height),
                    int(round_start), int(round_end_share_id),
                ),
            )
            row = db.execute("SELECT id FROM blocks WHERE block_hash=?", (block_hash,)).fetchone()
            return int(row[0])

    def eligible_payout_accounts(self, default_minimum_atomic):
        # Accounts already reserved by a pending/in-flight/uncertain payout are
        # excluded. This prevents an RPC timeout from causing an automatic
        # second payment of the same balance.
        with self._connect() as db:
            rows = db.execute(
                """SELECT a.id,a.address,a.balance_atomic,a.minimum_payout_atomic
                   FROM accounts a
                   WHERE a.enabled=1
                     AND a.balance_atomic >= CASE
                         WHEN a.minimum_payout_atomic>0 THEN a.minimum_payout_atomic ELSE ? END
                     AND NOT EXISTS (
                         SELECT 1 FROM payout_items pi
                         JOIN payouts p ON p.id=pi.payout_id
                         WHERE pi.account_id=a.id
                           AND p.status IN ('pending','broadcasting','uncertain')
                     )
                   ORDER BY a.id""",
                (int(default_minimum_atomic),),
            ).fetchall()
            return [dict(r) for r in rows]

    def mark_payout_broadcasting(self, payout_id):
        with self.lock, self._connect() as db:
            db.execute(
                "UPDATE payouts SET status='broadcasting',error=NULL WHERE id=? AND status='pending'",
                (int(payout_id),),
            )

    def mark_payout_uncertain(self, payout_id, error):
        with self.lock, self._connect() as db:
            db.execute(
                "UPDATE payouts SET status='uncertain',error=? WHERE id=?",
                (str(error)[:1000], int(payout_id)),
            )

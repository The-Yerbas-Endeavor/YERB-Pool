import time


def allocate_block_with_fee(db, block_id, pool_fee_percent=0.0, pool_fee_address=""):
    """Allocate miner rewards and credit the configured pool fee address.

    Miner allocations continue to use PoolDB.allocate_block_immature(). The
    fee portion already recorded in blocks.pool_fee_atomic is then credited as
    an immature block entry to the configured fee address. Because it uses the
    normal account/ledger path, the fee matures, handles orphan rollback, and
    participates in normal payouts just like any other balance.
    """
    db.allocate_block_immature(block_id, pool_fee_percent)

    address = str(pool_fee_address or "").strip()
    if not address:
        return

    now = int(time.time())
    with db.lock, db._connect() as con:
        block = con.execute(
            "SELECT pool_fee_atomic FROM blocks WHERE id=?",
            (int(block_id),),
        ).fetchone()
        if block is None:
            raise ValueError("unknown block")

        fee = int(block["pool_fee_atomic"] or 0)
        if fee <= 0:
            return

        con.execute(
            "INSERT OR IGNORE INTO accounts(address,created_at,updated_at) VALUES(?,?,?)",
            (address, now, now),
        )
        account_id = con.execute(
            "SELECT id FROM accounts WHERE address=?",
            (address,),
        ).fetchone()[0]

        existing = con.execute(
            """SELECT 1 FROM ledger
               WHERE block_id=? AND account_id=? AND entry_type='block_immature'
                 AND note='Pool fee credit pending coinbase maturity'
               LIMIT 1""",
            (int(block_id), int(account_id)),
        ).fetchone()
        if existing:
            return

        con.execute(
            "INSERT INTO ledger(ts,account_id,block_id,entry_type,amount_atomic,note) VALUES(?,?,?,?,?,?)",
            (
                now,
                int(account_id),
                int(block_id),
                "block_immature",
                fee,
                "Pool fee credit pending coinbase maturity",
            ),
        )
        con.execute(
            "UPDATE accounts SET immature_balance_atomic=immature_balance_atomic+?,updated_at=? WHERE id=?",
            (fee, now, int(account_id)),
        )

import sqlite3
import threading
import time
from decimal import Decimal, ROUND_DOWN


SCHEMA_VERSION = 2
COIN = 100_000_000


class PoolDB:
    def __init__(self, path):
        self.path = path
        self.lock = threading.RLock()
        self._init()

    def _connect(self):
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        db.execute("PRAGMA journal_mode = WAL")
        db.execute("PRAGMA busy_timeout = 5000")
        return db

    def _init(self):
        with self._connect() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS schema_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                address TEXT NOT NULL UNIQUE,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                balance_atomic INTEGER NOT NULL DEFAULT 0,
                immature_balance_atomic INTEGER NOT NULL DEFAULT 0,
                total_earned_atomic INTEGER NOT NULL DEFAULT 0,
                total_paid_atomic INTEGER NOT NULL DEFAULT 0,
                minimum_payout_atomic INTEGER NOT NULL DEFAULT 0,
                enabled INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS workers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                last_seen_at INTEGER NOT NULL,
                accepted_shares INTEGER NOT NULL DEFAULT 0,
                rejected_shares INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY(account_id) REFERENCES accounts(id) ON DELETE CASCADE,
                UNIQUE(account_id, name)
            );
            CREATE TABLE IF NOT EXISTS shares (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts INTEGER NOT NULL,
                account_id INTEGER,
                worker_id INTEGER,
                worker TEXT NOT NULL,
                job_id TEXT NOT NULL,
                difficulty REAL NOT NULL,
                accepted INTEGER NOT NULL,
                block_candidate INTEGER NOT NULL DEFAULT 0,
                hash TEXT,
                FOREIGN KEY(account_id) REFERENCES accounts(id),
                FOREIGN KEY(worker_id) REFERENCES workers(id)
            );
            CREATE TABLE IF NOT EXISTS blocks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                height INTEGER,
                block_hash TEXT UNIQUE,
                job_id TEXT,
                finder_account_id INTEGER,
                finder_worker_id INTEGER,
                reward_atomic INTEGER NOT NULL DEFAULT 0,
                pool_fee_atomic INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'submitted',
                submitted_at INTEGER NOT NULL,
                confirmed_at INTEGER,
                credited_at INTEGER,
                maturity_height INTEGER,
                confirmations INTEGER NOT NULL DEFAULT 0,
                round_start_share_id INTEGER,
                round_end_share_id INTEGER,
                FOREIGN KEY(finder_account_id) REFERENCES accounts(id),
                FOREIGN KEY(finder_worker_id) REFERENCES workers(id)
            );
            CREATE TABLE IF NOT EXISTS ledger (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts INTEGER NOT NULL,
                account_id INTEGER NOT NULL,
                block_id INTEGER,
                payout_id INTEGER,
                entry_type TEXT NOT NULL,
                amount_atomic INTEGER NOT NULL,
                note TEXT,
                FOREIGN KEY(account_id) REFERENCES accounts(id),
                FOREIGN KEY(block_id) REFERENCES blocks(id)
            );
            CREATE TABLE IF NOT EXISTS payouts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at INTEGER NOT NULL,
                sent_at INTEGER,
                txid TEXT UNIQUE,
                total_atomic INTEGER NOT NULL DEFAULT 0,
                fee_atomic INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'pending',
                error TEXT
            );
            CREATE TABLE IF NOT EXISTS payout_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                payout_id INTEGER NOT NULL,
                account_id INTEGER NOT NULL,
                address TEXT NOT NULL,
                amount_atomic INTEGER NOT NULL,
                FOREIGN KEY(payout_id) REFERENCES payouts(id) ON DELETE CASCADE,
                FOREIGN KEY(account_id) REFERENCES accounts(id)
            );
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_shares_worker ON shares(worker);
            CREATE INDEX IF NOT EXISTS idx_shares_ts ON shares(ts);
            CREATE INDEX IF NOT EXISTS idx_shares_account ON shares(account_id, ts);
            CREATE INDEX IF NOT EXISTS idx_blocks_status ON blocks(status, height);
            CREATE INDEX IF NOT EXISTS idx_ledger_account ON ledger(account_id, ts);
            CREATE INDEX IF NOT EXISTS idx_payouts_status ON payouts(status, created_at);
            """)
            self._migrate(db)
            db.execute("INSERT OR REPLACE INTO schema_meta(key,value) VALUES('schema_version',?)", (str(SCHEMA_VERSION),))

    @staticmethod
    def _ensure_column(db, table, name, definition):
        cols = {row[1] for row in db.execute(f"PRAGMA table_info({table})")}
        if name not in cols:
            db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")

    def _migrate(self, db):
        self._ensure_column(db, "shares", "account_id", "INTEGER")
        self._ensure_column(db, "shares", "worker_id", "INTEGER")
        self._ensure_column(db, "blocks", "pool_fee_atomic", "INTEGER NOT NULL DEFAULT 0")
        self._ensure_column(db, "blocks", "credited_at", "INTEGER")
        self._ensure_column(db, "blocks", "round_start_share_id", "INTEGER")
        self._ensure_column(db, "blocks", "round_end_share_id", "INTEGER")

    @staticmethod
    def split_worker(login):
        login = (login or "").strip()
        if "." in login:
            address, worker_name = login.split(".", 1)
        else:
            address, worker_name = login, "default"
        return address.strip(), (worker_name.strip() or "default")

    def get_or_create_worker(self, login):
        address, worker_name = self.split_worker(login)
        if not address:
            raise ValueError("empty payout address")
        now = int(time.time())
        with self.lock, self._connect() as db:
            db.execute("INSERT OR IGNORE INTO accounts(address,created_at,updated_at) VALUES(?,?,?)", (address, now, now))
            db.execute("UPDATE accounts SET updated_at=? WHERE address=?", (now, address))
            account_id = db.execute("SELECT id FROM accounts WHERE address=?", (address,)).fetchone()[0]
            db.execute("INSERT OR IGNORE INTO workers(account_id,name,created_at,last_seen_at) VALUES(?,?,?,?)", (account_id, worker_name, now, now))
            db.execute("UPDATE workers SET last_seen_at=? WHERE account_id=? AND name=?", (now, account_id, worker_name))
            worker_id = db.execute("SELECT id FROM workers WHERE account_id=? AND name=?", (account_id, worker_name)).fetchone()[0]
            return account_id, worker_id

    def add_share(self, worker, job_id, difficulty, accepted, block_candidate=False, hash_hex=None):
        account_id, worker_id = self.get_or_create_worker(worker)
        now = int(time.time())
        with self.lock, self._connect() as db:
            cur = db.execute(
                "INSERT INTO shares(ts,account_id,worker_id,worker,job_id,difficulty,accepted,block_candidate,hash) VALUES(?,?,?,?,?,?,?,?,?)",
                (now, account_id, worker_id, worker, job_id, float(difficulty), int(bool(accepted)), int(bool(block_candidate)), hash_hex),
            )
            counter = "accepted_shares" if accepted else "rejected_shares"
            db.execute(f"UPDATE workers SET {counter}={counter}+1,last_seen_at=? WHERE id=?", (now, worker_id))
            return int(cur.lastrowid)

    def record_block(self, worker, job_id, block_hash, height, reward_atomic, round_end_share_id, maturity_height):
        account_id, worker_id = self.get_or_create_worker(worker)
        now = int(time.time())
        with self.lock, self._connect() as db:
            prev = db.execute(
                "SELECT MAX(round_end_share_id) FROM blocks WHERE round_end_share_id IS NOT NULL AND status != 'rejected'"
            ).fetchone()[0]
            round_start = (int(prev) + 1) if prev is not None else 1
            db.execute(
                """INSERT OR IGNORE INTO blocks(
                    height,block_hash,job_id,finder_account_id,finder_worker_id,reward_atomic,status,
                    submitted_at,maturity_height,round_start_share_id,round_end_share_id
                ) VALUES(?,?,?,?,?,?,'submitted',?,?,?,?,?)""",
                (height, block_hash, job_id, account_id, worker_id, int(reward_atomic), now,
                 int(maturity_height), round_start, int(round_end_share_id)),
            )
            row = db.execute("SELECT id FROM blocks WHERE block_hash=?", (block_hash,)).fetchone()
            return int(row[0])

    @staticmethod
    def _allocate_integer(total_atomic, weighted_rows):
        if total_atomic <= 0 or not weighted_rows:
            return {}
        total_weight = sum(Decimal(str(r["weight"])) for r in weighted_rows)
        if total_weight <= 0:
            return {}
        result = {}
        fractions = []
        used = 0
        for r in weighted_rows:
            aid = int(r["account_id"])
            exact = Decimal(total_atomic) * Decimal(str(r["weight"])) / total_weight
            base = int(exact.to_integral_value(rounding=ROUND_DOWN))
            result[aid] = base
            used += base
            fractions.append((exact - Decimal(base), aid))
        for _, aid in sorted(fractions, key=lambda x: (x[0], -x[1]), reverse=True)[: total_atomic - used]:
            result[aid] += 1
        return result

    def allocate_block_immature(self, block_id, pool_fee_percent=0.0):
        now = int(time.time())
        with self.lock, self._connect() as db:
            block = db.execute("SELECT * FROM blocks WHERE id=?", (int(block_id),)).fetchone()
            if block is None:
                raise ValueError("unknown block")
            existing = db.execute("SELECT 1 FROM ledger WHERE block_id=? AND entry_type='block_immature' LIMIT 1", (block_id,)).fetchone()
            if existing:
                return
            rows = db.execute(
                """SELECT account_id, SUM(difficulty) AS weight FROM shares
                   WHERE accepted=1 AND account_id IS NOT NULL AND id BETWEEN ? AND ?
                   GROUP BY account_id""",
                (block["round_start_share_id"], block["round_end_share_id"]),
            ).fetchall()
            fee = int(Decimal(block["reward_atomic"]) * Decimal(str(pool_fee_percent)) / Decimal("100"))
            distributable = max(0, int(block["reward_atomic"]) - fee)
            allocations = self._allocate_integer(distributable, rows)
            for account_id, amount in allocations.items():
                if amount <= 0:
                    continue
                db.execute("INSERT INTO ledger(ts,account_id,block_id,entry_type,amount_atomic,note) VALUES(?,?,?,?,?,?)",
                           (now, account_id, block_id, "block_immature", amount, "Proportional round credit pending coinbase maturity"))
                db.execute("UPDATE accounts SET immature_balance_atomic=immature_balance_atomic+?,updated_at=? WHERE id=?",
                           (amount, now, account_id))
            db.execute("UPDATE blocks SET pool_fee_atomic=? WHERE id=?", (fee, block_id))

    def pending_blocks(self):
        with self._connect() as db:
            return [dict(r) for r in db.execute(
                "SELECT * FROM blocks WHERE status IN ('submitted','confirmed') ORDER BY height"
            ).fetchall()]

    def update_block_confirmations(self, block_id, confirmations):
        now = int(time.time())
        status = "confirmed" if confirmations > 0 else "submitted"
        with self.lock, self._connect() as db:
            db.execute("UPDATE blocks SET confirmations=?,status=?,confirmed_at=COALESCE(confirmed_at,?) WHERE id=?",
                       (int(confirmations), status, now if confirmations > 0 else None, int(block_id)))

    def mature_block(self, block_id):
        now = int(time.time())
        with self.lock, self._connect() as db:
            block = db.execute("SELECT * FROM blocks WHERE id=?", (int(block_id),)).fetchone()
            if block is None or block["status"] == "mature":
                return False
            credits = db.execute(
                "SELECT account_id, amount_atomic FROM ledger WHERE block_id=? AND entry_type='block_immature'",
                (int(block_id),),
            ).fetchall()
            for row in credits:
                amount = int(row["amount_atomic"])
                aid = int(row["account_id"])
                db.execute("UPDATE accounts SET immature_balance_atomic=MAX(0,immature_balance_atomic-?), balance_atomic=balance_atomic+?, total_earned_atomic=total_earned_atomic+?,updated_at=? WHERE id=?",
                           (amount, amount, amount, now, aid))
                db.execute("INSERT INTO ledger(ts,account_id,block_id,entry_type,amount_atomic,note) VALUES(?,?,?,?,?,?)",
                           (now, aid, block_id, "block_mature", amount, "Coinbase matured; moved to spendable balance"))
            db.execute("UPDATE blocks SET status='mature',credited_at=? WHERE id=?", (now, int(block_id)))
            return True

    def orphan_block(self, block_id, note="Block orphaned/reorged"):
        now = int(time.time())
        with self.lock, self._connect() as db:
            block = db.execute("SELECT status FROM blocks WHERE id=?", (int(block_id),)).fetchone()
            if block is None or block[0] in ("orphan", "mature"):
                return
            credits = db.execute("SELECT account_id,amount_atomic FROM ledger WHERE block_id=? AND entry_type='block_immature'", (int(block_id),)).fetchall()
            for row in credits:
                db.execute("UPDATE accounts SET immature_balance_atomic=MAX(0,immature_balance_atomic-?),updated_at=? WHERE id=?",
                           (int(row["amount_atomic"]), now, int(row["account_id"])))
                db.execute("INSERT INTO ledger(ts,account_id,block_id,entry_type,amount_atomic,note) VALUES(?,?,?,?,?,?)",
                           (now, int(row["account_id"]), int(block_id), "block_orphan", -int(row["amount_atomic"]), note))
            db.execute("UPDATE blocks SET status='orphan' WHERE id=?", (int(block_id),))

    def eligible_payout_accounts(self, default_minimum_atomic):
        with self._connect() as db:
            rows = db.execute(
                """SELECT id,address,balance_atomic,minimum_payout_atomic FROM accounts
                   WHERE enabled=1 AND balance_atomic >= CASE WHEN minimum_payout_atomic>0 THEN minimum_payout_atomic ELSE ? END
                   ORDER BY id""",
                (int(default_minimum_atomic),),
            ).fetchall()
            return [dict(r) for r in rows]

    def create_payout(self, accounts):
        now = int(time.time())
        with self.lock, self._connect() as db:
            cur = db.execute("INSERT INTO payouts(created_at,total_atomic,status) VALUES(?,0,'pending')", (now,))
            payout_id = int(cur.lastrowid)
            total = 0
            for account in accounts:
                amount = int(account["balance_atomic"])
                if amount <= 0:
                    continue
                total += amount
                db.execute("INSERT INTO payout_items(payout_id,account_id,address,amount_atomic) VALUES(?,?,?,?)",
                           (payout_id, int(account["id"]), account["address"], amount))
            db.execute("UPDATE payouts SET total_atomic=? WHERE id=?", (total, payout_id))
            return payout_id

    def payout_items(self, payout_id):
        with self._connect() as db:
            return [dict(r) for r in db.execute("SELECT * FROM payout_items WHERE payout_id=? ORDER BY id", (int(payout_id),)).fetchall()]

    def mark_payout_sent(self, payout_id, txid):
        now = int(time.time())
        with self.lock, self._connect() as db:
            payout = db.execute("SELECT status FROM payouts WHERE id=?", (int(payout_id),)).fetchone()
            if payout is None or payout[0] == "sent":
                return
            items = db.execute("SELECT * FROM payout_items WHERE payout_id=?", (int(payout_id),)).fetchall()
            for item in items:
                amount = int(item["amount_atomic"])
                aid = int(item["account_id"])
                db.execute("UPDATE accounts SET balance_atomic=MAX(0,balance_atomic-?),total_paid_atomic=total_paid_atomic+?,updated_at=? WHERE id=?",
                           (amount, amount, now, aid))
                db.execute("INSERT INTO ledger(ts,account_id,payout_id,entry_type,amount_atomic,note) VALUES(?,?,?,?,?,?)",
                           (now, aid, payout_id, "payout", -amount, f"Payout txid {txid}"))
            db.execute("UPDATE payouts SET status='sent',sent_at=?,txid=?,error=NULL WHERE id=?", (now, txid, int(payout_id)))

    def mark_payout_failed(self, payout_id, error):
        with self.lock, self._connect() as db:
            db.execute("UPDATE payouts SET status='failed',error=? WHERE id=?", (str(error)[:1000], int(payout_id)))

    def account_balance(self, address):
        with self._connect() as db:
            row = db.execute("SELECT balance_atomic,immature_balance_atomic,total_earned_atomic,total_paid_atomic FROM accounts WHERE address=?", (address,)).fetchone()
        if row is None:
            return None
        return dict(row)

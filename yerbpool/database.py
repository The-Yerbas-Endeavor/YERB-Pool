import sqlite3
import threading
import time


SCHEMA_VERSION = 1


class PoolDB:
    def __init__(self, path):
        self.path = path
        self.lock = threading.RLock()
        self._init()

    def _connect(self):
        db = sqlite3.connect(self.path)
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
                status TEXT NOT NULL DEFAULT 'submitted',
                submitted_at INTEGER NOT NULL,
                confirmed_at INTEGER,
                maturity_height INTEGER,
                confirmations INTEGER NOT NULL DEFAULT 0,
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
            self._ensure_share_columns(db)
            db.execute(
                "INSERT OR REPLACE INTO schema_meta(key,value) VALUES('schema_version',?)",
                (str(SCHEMA_VERSION),),
            )

    @staticmethod
    def _ensure_share_columns(db):
        columns = {row[1] for row in db.execute("PRAGMA table_info(shares)")}
        if "account_id" not in columns:
            db.execute("ALTER TABLE shares ADD COLUMN account_id INTEGER")
        if "worker_id" not in columns:
            db.execute("ALTER TABLE shares ADD COLUMN worker_id INTEGER")

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
            db.execute(
                "INSERT OR IGNORE INTO accounts(address,created_at,updated_at) VALUES(?,?,?)",
                (address, now, now),
            )
            db.execute("UPDATE accounts SET updated_at=? WHERE address=?", (now, address))
            account_id = db.execute("SELECT id FROM accounts WHERE address=?", (address,)).fetchone()[0]
            db.execute(
                "INSERT OR IGNORE INTO workers(account_id,name,created_at,last_seen_at) VALUES(?,?,?,?)",
                (account_id, worker_name, now, now),
            )
            db.execute(
                "UPDATE workers SET last_seen_at=? WHERE account_id=? AND name=?",
                (now, account_id, worker_name),
            )
            worker_id = db.execute(
                "SELECT id FROM workers WHERE account_id=? AND name=?",
                (account_id, worker_name),
            ).fetchone()[0]
            return account_id, worker_id

    def add_share(self, worker, job_id, difficulty, accepted, block_candidate=False, hash_hex=None):
        account_id, worker_id = self.get_or_create_worker(worker)
        now = int(time.time())
        with self.lock, self._connect() as db:
            db.execute(
                "INSERT INTO shares(ts,account_id,worker_id,worker,job_id,difficulty,accepted,block_candidate,hash) VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    now,
                    account_id,
                    worker_id,
                    worker,
                    job_id,
                    float(difficulty),
                    int(bool(accepted)),
                    int(bool(block_candidate)),
                    hash_hex,
                ),
            )
            counter = "accepted_shares" if accepted else "rejected_shares"
            db.execute(
                f"UPDATE workers SET {counter}={counter}+1,last_seen_at=? WHERE id=?",
                (now, worker_id),
            )

    def record_block(self, worker, job_id, block_hash, height=None, reward_atomic=0, status="submitted"):
        account_id, worker_id = self.get_or_create_worker(worker)
        with self.lock, self._connect() as db:
            db.execute(
                """INSERT OR IGNORE INTO blocks(
                    height,block_hash,job_id,finder_account_id,finder_worker_id,reward_atomic,status,submitted_at
                ) VALUES(?,?,?,?,?,?,?,?)""",
                (
                    height,
                    block_hash,
                    job_id,
                    account_id,
                    worker_id,
                    int(reward_atomic),
                    status,
                    int(time.time()),
                ),
            )

    def account_balance(self, address):
        with self._connect() as db:
            row = db.execute(
                "SELECT balance_atomic,immature_balance_atomic,total_earned_atomic,total_paid_atomic FROM accounts WHERE address=?",
                (address,),
            ).fetchone()
        if row is None:
            return None
        return {
            "balance_atomic": row[0],
            "immature_balance_atomic": row[1],
            "total_earned_atomic": row[2],
            "total_paid_atomic": row[3],
        }

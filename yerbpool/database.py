import sqlite3
import threading
import time

class PoolDB:
    def __init__(self, path):
        self.path = path
        self.lock = threading.Lock()
        self._init()

    def _connect(self):
        return sqlite3.connect(self.path)

    def _init(self):
        with self._connect() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS shares (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts INTEGER NOT NULL,
                worker TEXT NOT NULL,
                job_id TEXT NOT NULL,
                difficulty REAL NOT NULL,
                accepted INTEGER NOT NULL,
                block_candidate INTEGER NOT NULL DEFAULT 0,
                hash TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_shares_worker ON shares(worker);
            CREATE INDEX IF NOT EXISTS idx_shares_ts ON shares(ts);
            """)

    def add_share(self, worker, job_id, difficulty, accepted, block_candidate=False, hash_hex=None):
        with self.lock, self._connect() as db:
            db.execute(
                "INSERT INTO shares(ts,worker,job_id,difficulty,accepted,block_candidate,hash) VALUES(?,?,?,?,?,?,?)",
                (int(time.time()), worker, job_id, float(difficulty), int(bool(accepted)), int(bool(block_candidate)), hash_hex),
            )

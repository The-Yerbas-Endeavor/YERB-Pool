import sqlite3

from yerbpool.database import PoolDB


class ClosingConnection(sqlite3.Connection):
    """sqlite3.Connection that closes when a with-block exits.

    Python's normal sqlite3 connection context manager only commits/rolls back;
    it does not close the file descriptor. The pool opens short-lived database
    connections throughout Stratum, accounting, maturity, and payout paths, so
    leaving them open eventually exhausts the process file-descriptor limit.
    """

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


def _safe_connect(self):
    db = sqlite3.connect(self.path, factory=ClosingConnection)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    db.execute("PRAGMA journal_mode = WAL")
    db.execute("PRAGMA busy_timeout = 5000")
    return db


def install_safe_sqlite_connections():
    """Make every PoolDB/AccountingDB short-lived connection close reliably."""
    PoolDB._connect = _safe_connect


def install_safe_connections():
    """Backward-compatible alias for older pool.py installations."""
    return install_safe_sqlite_connections()

import ipaddress
import sqlite3
import time


def _connect(path):
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA journal_mode = WAL")
    con.execute("PRAGMA busy_timeout = 5000")
    return con


def ensure_user_control_schema(path):
    with _connect(path) as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS worker_ip_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER NOT NULL,
            worker_id INTEGER NOT NULL,
            address TEXT NOT NULL,
            worker_name TEXT NOT NULL,
            ip_address TEXT NOT NULL,
            first_seen_at INTEGER NOT NULL,
            last_seen_at INTEGER NOT NULL,
            connection_count INTEGER NOT NULL DEFAULT 1,
            UNIQUE(worker_id, ip_address)
        );
        CREATE INDEX IF NOT EXISTS idx_worker_ip_account ON worker_ip_history(account_id, last_seen_at);
        CREATE INDEX IF NOT EXISTS idx_worker_ip_address ON worker_ip_history(ip_address, last_seen_at);
        CREATE TABLE IF NOT EXISTS banned_ips (
            ip_address TEXT PRIMARY KEY,
            banned_at INTEGER NOT NULL,
            reason TEXT
        );
        """)


def normalize_ip(value):
    value = str(value or "").strip()
    if not value:
        return ""
    return str(ipaddress.ip_address(value))


def is_ip_banned(pool_db, ip_address):
    try:
        ip_address = normalize_ip(ip_address)
    except ValueError:
        return False
    if not ip_address:
        return False
    ensure_user_control_schema(pool_db.path)
    with _connect(pool_db.path) as con:
        return con.execute(
            "SELECT 1 FROM banned_ips WHERE ip_address=? LIMIT 1", (ip_address,)
        ).fetchone() is not None


def record_worker_ip(pool_db, login, ip_address):
    try:
        ip_address = normalize_ip(ip_address)
    except ValueError:
        return
    if not ip_address:
        return
    account_id, worker_id = pool_db.get_or_create_worker(login)
    address, worker_name = pool_db.split_worker(login)
    now = int(time.time())
    ensure_user_control_schema(pool_db.path)
    with _connect(pool_db.path) as con:
        con.execute(
            """INSERT INTO worker_ip_history(
                   account_id,worker_id,address,worker_name,ip_address,first_seen_at,last_seen_at,connection_count
               ) VALUES(?,?,?,?,?,?,?,1)
               ON CONFLICT(worker_id,ip_address) DO UPDATE SET
                   last_seen_at=excluded.last_seen_at,
                   connection_count=worker_ip_history.connection_count+1""",
            (account_id, worker_id, address, worker_name, ip_address, now, now),
        )
        con.commit()


def list_users(path, hashrate_window=600, treasury_address=None):
    ensure_user_control_schema(path)
    cutoff = int(time.time()) - max(60, int(hashrate_window))
    treasury_clause = ""
    params = [cutoff, cutoff]
    if treasury_address:
        treasury_clause = "WHERE a.address != ?"
        params.append(str(treasury_address))

    with _connect(path) as con:
        users = [dict(row) for row in con.execute(
            f"""SELECT a.id,a.address,a.created_at,a.updated_at,a.balance_atomic,
                       a.immature_balance_atomic,a.total_earned_atomic,a.total_paid_atomic,
                       a.minimum_payout_atomic,a.enabled,
                       (SELECT COUNT(*) FROM workers w WHERE w.account_id=a.id) worker_count,
                       (SELECT COUNT(*) FROM workers w WHERE w.account_id=a.id AND w.last_seen_at>=?) active_workers,
                       COALESCE((SELECT MAX(w.last_seen_at) FROM workers w WHERE w.account_id=a.id),0) last_seen_at,
                       COALESCE((SELECT SUM(w.accepted_shares) FROM workers w WHERE w.account_id=a.id),0) accepted_shares,
                       COALESCE((SELECT SUM(w.rejected_shares) FROM workers w WHERE w.account_id=a.id),0) rejected_shares,
                       COALESCE((SELECT MAX(s.ts) FROM shares s WHERE s.account_id=a.id),0) last_share_at,
                       COALESCE((SELECT SUM(s.difficulty) FROM shares s WHERE s.account_id=a.id AND s.accepted=1 AND s.ts>=?),0) accepted_diff
                FROM accounts a
                {treasury_clause}
                ORDER BY last_seen_at DESC,a.id DESC""",
            tuple(params),
        ).fetchall()]

        for user in users:
            aid = int(user["id"])
            user["worker_names"] = [
                row[0] for row in con.execute(
                    "SELECT name FROM workers WHERE account_id=? ORDER BY last_seen_at DESC,name LIMIT 12",
                    (aid,),
                ).fetchall()
            ]
            user["ips"] = [dict(row) for row in con.execute(
                """SELECT h.ip_address,MAX(h.last_seen_at) last_seen_at,
                          SUM(h.connection_count) connection_count,
                          CASE WHEN b.ip_address IS NULL THEN 0 ELSE 1 END banned
                   FROM worker_ip_history h
                   LEFT JOIN banned_ips b ON b.ip_address=h.ip_address
                   WHERE h.account_id=?
                   GROUP BY h.ip_address
                   ORDER BY last_seen_at DESC""",
                (aid,),
            ).fetchall()]
        return users


def set_account_payout_enabled(path, address, enabled):
    address = str(address or "").strip()
    if not address:
        raise ValueError("address is required")
    now = int(time.time())
    with _connect(path) as con:
        cur = con.execute(
            "UPDATE accounts SET enabled=?,updated_at=? WHERE address=?",
            (1 if enabled else 0, now, address),
        )
        if cur.rowcount != 1:
            raise ValueError("unknown user address")
        con.commit()
    return bool(enabled)


def set_ip_banned(path, ip_address, banned, reason="Admin pool ban"):
    ip_address = normalize_ip(ip_address)
    if not ip_address:
        raise ValueError("ip_address is required")
    ensure_user_control_schema(path)
    with _connect(path) as con:
        if banned:
            con.execute(
                "INSERT OR REPLACE INTO banned_ips(ip_address,banned_at,reason) VALUES(?,?,?)",
                (ip_address, int(time.time()), str(reason or "Admin pool ban")[:250]),
            )
        else:
            con.execute("DELETE FROM banned_ips WHERE ip_address=?", (ip_address,))
        con.commit()
    return bool(banned)

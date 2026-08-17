import ipaddress
import json
import sqlite3
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed


GEO_CACHE_SECONDS = 30 * 86400
GEO_LOOKUP_TIMEOUT = 2.0


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
        CREATE TABLE IF NOT EXISTS suspended_accounts (
            address TEXT PRIMARY KEY,
            suspended_at INTEGER NOT NULL,
            reason TEXT
        );
        CREATE TABLE IF NOT EXISTS ip_geo_cache (
            ip_address TEXT PRIMARY KEY,
            country TEXT,
            country_code TEXT,
            checked_at INTEGER NOT NULL
        );
        """)


def normalize_ip(value):
    value = str(value or "").strip()
    if not value:
        return ""
    return str(ipaddress.ip_address(value))


def _is_public_ip(value):
    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        return False
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


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


def is_account_suspended(pool_db, address):
    address = str(address or "").strip()
    if not address:
        return False
    ensure_user_control_schema(pool_db.path)
    with _connect(pool_db.path) as con:
        return con.execute(
            "SELECT 1 FROM suspended_accounts WHERE address=? LIMIT 1", (address,)
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


def _cached_country(path, ip_address):
    now = int(time.time())
    with _connect(path) as con:
        row = con.execute(
            "SELECT country,country_code,checked_at FROM ip_geo_cache WHERE ip_address=?",
            (ip_address,),
        ).fetchone()
    if row and now - int(row["checked_at"] or 0) < GEO_CACHE_SECONDS:
        return {
            "country": row["country"] or "",
            "country_code": row["country_code"] or "",
        }
    return None


def _store_country(path, ip_address, country, country_code):
    with _connect(path) as con:
        con.execute(
            """INSERT INTO ip_geo_cache(ip_address,country,country_code,checked_at)
               VALUES(?,?,?,?)
               ON CONFLICT(ip_address) DO UPDATE SET
                   country=excluded.country,
                   country_code=excluded.country_code,
                   checked_at=excluded.checked_at""",
            (ip_address, country, country_code, int(time.time())),
        )
        con.commit()


def _lookup_country_uncached(path, ip_address):
    if not _is_public_ip(ip_address):
        result = {"country": "Private / Local", "country_code": ""}
        _store_country(path, ip_address, result["country"], "")
        return result
    req = urllib.request.Request(
        f"https://ipwho.is/{ip_address}",
        headers={"User-Agent": "YERB-Pool/1.0"},
    )
    country = ""
    country_code = ""
    try:
        with urllib.request.urlopen(req, timeout=GEO_LOOKUP_TIMEOUT) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if payload.get("success") is not False:
            country = str(payload.get("country") or "")
            country_code = str(payload.get("country_code") or "")
    except Exception:
        pass
    _store_country(path, ip_address, country, country_code)
    return {"country": country, "country_code": country_code}


def resolve_countries(path, ip_addresses):
    ensure_user_control_schema(path)
    unique = []
    seen = set()
    results = {}
    for value in ip_addresses:
        try:
            ip = normalize_ip(value)
        except ValueError:
            continue
        if not ip or ip in seen:
            continue
        seen.add(ip)
        cached = _cached_country(path, ip)
        if cached is not None:
            results[ip] = cached
        else:
            unique.append(ip)
    if unique:
        with ThreadPoolExecutor(max_workers=min(8, len(unique))) as executor:
            futures = {executor.submit(_lookup_country_uncached, path, ip): ip for ip in unique}
            for future in as_completed(futures):
                ip = futures[future]
                try:
                    results[ip] = future.result()
                except Exception:
                    results[ip] = {"country": "", "country_code": ""}
    return results


def list_users(path, hashrate_window=600, treasury_address=None):
    ensure_user_control_schema(path)
    now = int(time.time())
    current_cutoff = now - max(60, int(hashrate_window))
    day_cutoff = now - 86400
    treasury_clause = ""
    if treasury_address:
        treasury_clause = "WHERE a.address != ?"

    with _connect(path) as con:
        sql_params = [current_cutoff, current_cutoff, day_cutoff]
        if treasury_address:
            sql_params.append(str(treasury_address))
        users = [dict(row) for row in con.execute(
            f"""WITH worker_stats AS (
                    SELECT account_id,
                           COUNT(*) worker_count,
                           SUM(CASE WHEN last_seen_at>=? THEN 1 ELSE 0 END) active_workers,
                           MAX(last_seen_at) last_seen_at
                    FROM workers GROUP BY account_id
                ),
                share_stats AS (
                    SELECT account_id,
                           MAX(ts) last_share_at,
                           SUM(CASE WHEN accepted=1 AND ts>=? THEN difficulty ELSE 0 END) current_accepted_diff,
                           SUM(CASE WHEN accepted=1 AND ts>=? THEN difficulty ELSE 0 END) accepted_diff_24h,
                           SUM(CASE WHEN accepted=1 THEN 1 ELSE 0 END) accepted_shares,
                           SUM(CASE WHEN accepted=0 THEN 1 ELSE 0 END) rejected_shares
                    FROM shares WHERE account_id IS NOT NULL GROUP BY account_id
                ),
                payout_stats AS (
                    SELECT pi.account_id, MAX(p.sent_at) last_payout_at
                    FROM payout_items pi
                    JOIN payouts p ON p.id=pi.payout_id
                    WHERE p.status='sent'
                    GROUP BY pi.account_id
                )
                SELECT a.id,a.address,a.created_at,a.updated_at,a.balance_atomic,
                       a.immature_balance_atomic,a.total_earned_atomic,a.total_paid_atomic,
                       a.minimum_payout_atomic,a.enabled,
                       COALESCE(ws.worker_count,0) worker_count,
                       COALESCE(ws.active_workers,0) active_workers,
                       COALESCE(ws.last_seen_at,0) last_seen_at,
                       COALESCE(ss.last_share_at,0) last_share_at,
                       COALESCE(ss.current_accepted_diff,0) current_accepted_diff,
                       COALESCE(ss.accepted_diff_24h,0) accepted_diff_24h,
                       COALESCE(ss.accepted_shares,0) accepted_shares,
                       COALESCE(ss.rejected_shares,0) rejected_shares,
                       COALESCE(ps.last_payout_at,0) last_payout_at,
                       CASE WHEN sa.address IS NULL THEN 0 ELSE 1 END suspended
                FROM accounts a
                LEFT JOIN worker_stats ws ON ws.account_id=a.id
                LEFT JOIN share_stats ss ON ss.account_id=a.id
                LEFT JOIN payout_stats ps ON ps.account_id=a.id
                LEFT JOIN suspended_accounts sa ON sa.address=a.address
                {treasury_clause}
                ORDER BY last_seen_at DESC,a.id DESC""",
            tuple(sql_params),
        ).fetchall()]

        latest_ips = []
        for user in users:
            user["worker_names"] = [
                str(row["name"]) for row in con.execute(
                    "SELECT name FROM workers WHERE account_id=? ORDER BY name",
                    (int(user["id"]),),
                ).fetchall()
            ]
            ips = [dict(row) for row in con.execute(
                """SELECT h.ip_address,MIN(h.first_seen_at) first_seen_at,
                          MAX(h.last_seen_at) last_seen_at,
                          SUM(h.connection_count) connection_count,
                          CASE WHEN b.ip_address IS NULL THEN 0 ELSE 1 END banned
                   FROM worker_ip_history h
                   LEFT JOIN banned_ips b ON b.ip_address=h.ip_address
                   WHERE h.account_id=?
                   GROUP BY h.ip_address
                   ORDER BY last_seen_at DESC""",
                (int(user["id"]),),
            ).fetchall()]
            user["ips"] = ips
            if ips:
                latest_ips.append(ips[0]["ip_address"])

    geo = resolve_countries(path, latest_ips)
    for user in users:
        for ip in user.get("ips") or []:
            info = geo.get(ip["ip_address"])
            ip["country"] = info.get("country") if info else ""
            ip["country_code"] = info.get("country_code") if info else ""
        latest = (user.get("ips") or [{}])[0]
        user["country"] = latest.get("country") or ""
        user["country_code"] = latest.get("country_code") or ""
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


def set_account_suspended(path, address, suspended, reason="Admin suspension"):
    address = str(address or "").strip()
    if not address:
        raise ValueError("address is required")
    ensure_user_control_schema(path)
    with _connect(path) as con:
        exists = con.execute(
            "SELECT 1 FROM accounts WHERE address=? LIMIT 1", (address,)
        ).fetchone()
        if not exists:
            raise ValueError("unknown user address")
        if suspended:
            con.execute(
                "INSERT OR REPLACE INTO suspended_accounts(address,suspended_at,reason) VALUES(?,?,?)",
                (address, int(time.time()), str(reason or "Admin suspension")[:250]),
            )
        else:
            con.execute("DELETE FROM suspended_accounts WHERE address=?", (address,))
        con.commit()
    return bool(suspended)


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

import asyncio
import json
import sqlite3
from pathlib import Path


POOL_FEE_KEY = "pool_fee_percent"


def _db_path(cfg):
    path = Path(cfg.get("database", "yerbpool.db"))
    if not path.is_absolute():
        path = Path.cwd() / path
    return path


def _connect(cfg):
    db = sqlite3.connect(_db_path(cfg))
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA busy_timeout = 5000")
    return db


def get_setting(cfg, key, default=None):
    db = _connect(cfg)
    try:
        row = db.execute("SELECT value FROM settings WHERE key=?", (str(key),)).fetchone()
        return row[0] if row else default
    finally:
        db.close()


def set_setting(cfg, key, value):
    import time

    db = _connect(cfg)
    try:
        db.execute(
            "INSERT INTO settings(key,value,updated_at) VALUES(?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at",
            (str(key), str(value), int(time.time())),
        )
        db.commit()
    finally:
        db.close()


def get_pool_fee_percent(cfg):
    fallback = float(cfg.get("payouts", {}).get("pool_fee_percent", 0.0))
    raw = get_setting(cfg, POOL_FEE_KEY, None)
    if raw is None:
        return fallback
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return fallback
    return min(100.0, max(0.0, value))


def set_pool_fee_percent(cfg, value, persist_config=True):
    value = float(value)
    if not 0.0 <= value <= 100.0:
        raise ValueError("pool fee must be between 0 and 100 percent")
    normalized = f"{value:.8f}".rstrip("0").rstrip(".") or "0"
    set_setting(cfg, POOL_FEE_KEY, normalized)
    cfg.setdefault("payouts", {})["pool_fee_percent"] = value

    if persist_config:
        config_path = Path("config.json")
        if config_path.exists():
            disk = json.loads(config_path.read_text(encoding="utf-8"))
            disk.setdefault("payouts", {})["pool_fee_percent"] = value
            config_path.write_text(json.dumps(disk, indent=2) + "\n", encoding="utf-8")
    return value


def ensure_runtime_settings(cfg):
    if get_setting(cfg, POOL_FEE_KEY, None) is None:
        set_pool_fee_percent(
            cfg,
            float(cfg.get("payouts", {}).get("pool_fee_percent", 0.0)),
            persist_config=False,
        )
    cfg.setdefault("payouts", {})["pool_fee_percent"] = get_pool_fee_percent(cfg)


async def sync_runtime_settings(cfg, interval=2):
    """Keep the shared runtime config synchronized with admin-controlled settings."""
    ensure_runtime_settings(cfg)
    while True:
        try:
            cfg.setdefault("payouts", {})["pool_fee_percent"] = get_pool_fee_percent(cfg)
        except Exception:
            pass
        await asyncio.sleep(max(1, int(interval)))

"""Runtime control channel for payout administration.

The pause flag is persisted in the pool settings database. Transient run-now
requests live outside the public web root and are consumed only by the pool
daemon, which remains the sole process that executes payout logic.
"""

import json
import time
import uuid
from pathlib import Path

from yerbpool.admin_settings import get_setting, set_setting
from yerbpool.config import load_config


PAUSED_KEY = "payouts_paused"
RUNTIME_DIR = Path("runtime")
REQUEST_PATH = RUNTIME_DIR / "payout_request.json"
PROCESSING_PATH = RUNTIME_DIR / "payout_request.processing.json"
RESULT_PATH = RUNTIME_DIR / "payout_result.json"


def _read_json(path):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, separators=(",", ":")) + "\n", encoding="utf-8")
    tmp.replace(path)


def _cfg(cfg=None):
    return cfg if cfg is not None else load_config()


def read_control(cfg=None):
    raw = str(get_setting(_cfg(cfg), PAUSED_KEY, "0") or "0").strip().lower()
    return {"paused": raw in ("1", "true", "yes", "on")}


def set_paused(paused, cfg=None):
    value = bool(paused)
    set_setting(_cfg(cfg), PAUSED_KEY, "1" if value else "0")
    return {
        "paused": value,
        "updated_at": int(time.time()),
    }


def request_run_now():
    if REQUEST_PATH.exists() or PROCESSING_PATH.exists():
        raise RuntimeError("A payout check is already queued or running")
    payload = {
        "request_id": uuid.uuid4().hex,
        "requested_at": int(time.time()),
        "action": "run_now",
    }
    _write_json(REQUEST_PATH, payload)
    return payload


def consume_request():
    if PROCESSING_PATH.exists() or not REQUEST_PATH.exists():
        return None
    try:
        REQUEST_PATH.replace(PROCESSING_PATH)
    except FileNotFoundError:
        return None
    data = _read_json(PROCESSING_PATH)
    return data or {"request_id": "unknown", "requested_at": int(time.time()), "action": "run_now"}


def finish_request(payload):
    _write_json(RESULT_PATH, payload)
    try:
        PROCESSING_PATH.unlink()
    except FileNotFoundError:
        pass


def read_request_state():
    if PROCESSING_PATH.exists():
        data = _read_json(PROCESSING_PATH)
        return {"state": "running", **data}
    if REQUEST_PATH.exists():
        data = _read_json(REQUEST_PATH)
        return {"state": "queued", **data}
    return {"state": "idle"}


def read_result():
    return _read_json(RESULT_PATH)

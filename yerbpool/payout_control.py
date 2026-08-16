"""Runtime-only control channel for payout administration.

Control/request files live outside the public web root.  The web process may
request an action, but only the pool daemon consumes requests and executes
payout logic.
"""

import json
import time
import uuid
from pathlib import Path


RUNTIME_DIR = Path("runtime")
CONTROL_PATH = RUNTIME_DIR / "payout_control.json"
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


def read_control():
    data = _read_json(CONTROL_PATH)
    return {
        "paused": bool(data.get("paused", False)),
        "updated_at": int(data.get("updated_at") or 0),
    }


def set_paused(paused):
    data = {
        "paused": bool(paused),
        "updated_at": int(time.time()),
    }
    _write_json(CONTROL_PATH, data)
    return data


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

import json
from pathlib import Path

DEFAULT_PATH = Path("config.json")

def load_config(path=DEFAULT_PATH):
    path = Path(path)
    if not path.exists():
        raise SystemExit(f"Missing {path}. Copy config.example.json to config.json and edit it.")
    with path.open("r", encoding="utf-8") as f:
        cfg = json.load(f)
    for key in ("rpc", "stratum", "database", "pool_address"):
        if key not in cfg:
            raise SystemExit(f"Missing config key: {key}")
    return cfg

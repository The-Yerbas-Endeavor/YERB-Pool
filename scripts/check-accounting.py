#!/usr/bin/env python3
import json
from pathlib import Path

from yerbpool.config import load_config
from yerbpool.diagnostics import accounting_integrity


cfg = load_config()
db_path = Path(cfg.get("database", "yerbpool.db"))
if not db_path.is_absolute():
    db_path = Path.cwd() / db_path

result = accounting_integrity(db_path)
print(json.dumps(result, indent=2, sort_keys=True))
raise SystemExit(0 if result.get("ok") else 1)

#!/usr/bin/env python3
import json
import sys
from pathlib import Path

# Allow this script to be executed directly from scripts/ without requiring
# PYTHONPATH to be set or preserved through sudo.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from yerbpool.config import load_config
from yerbpool.diagnostics import accounting_integrity


cfg = load_config()
db_path = Path(cfg.get("database", "yerbpool.db"))
if not db_path.is_absolute():
    db_path = Path.cwd() / db_path

result = accounting_integrity(db_path)
print(json.dumps(result, indent=2, sort_keys=True))
raise SystemExit(0 if result.get("ok") else 1)

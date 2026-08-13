#!/usr/bin/env python3
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from yerbpool.database import PoolDB


def main():
    config_path = ROOT / "config.json"
    if config_path.exists():
        config = json.loads(config_path.read_text(encoding="utf-8"))
        db_path = Path(config.get("database", "yerbpool.db"))
        if not db_path.is_absolute():
            db_path = ROOT / db_path
    else:
        db_path = ROOT / "yerbpool.db"

    PoolDB(str(db_path))
    print(f"Initialized YERB Pool database: {db_path}")
    print("Schema includes accounts, workers, shares, blocks, ledger, payouts, payout_items, settings, and schema_meta.")


if __name__ == "__main__":
    main()

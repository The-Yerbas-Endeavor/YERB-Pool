import json
import os
import tempfile
import unittest
from pathlib import Path

# The production web stack loads its configuration at import time. Supply a
# short-lived local configuration so these tests never depend on operator files.
_config_path = Path("config.json")
_created_config = not _config_path.exists()
if _created_config:
    _config_path.write_text(json.dumps({
        "rpc": {"url": "http://127.0.0.1:15419", "user": "test", "password": "test"},
        "stratum": {"host": "127.0.0.1", "port": 3333},
        "database": "test.db",
        "pool_address": "yTestPool",
    }))
try:
    import web_enhanced as api
finally:
    if _created_config:
        _config_path.unlink()

from yerbpool.database import PoolDB


class PublicApiTest(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.db = PoolDB(self.path)
        self.original_path = api.admin.live.base.DB_PATH
        api.admin.live.base.DB_PATH = self.path

        first = self.db.add_share("yMinerA.rig1", "job1", 1.0, True)
        self.db.add_share("yMinerA.rig1", "job1", 0.5, False)
        last = self.db.add_share("yMinerA.rig2", "job1", 2.0, True, True)
        self.block_id = self.db.record_block(
            "yMinerA.rig2", "job1", "ab" * 32, 1000,
            300_000_000, 8_000_000_000, last, 1100,
        )
        self.db.allocate_block_immature(self.block_id, 0.5)
        self.db.update_block_confirmations(self.block_id, 100, 100)
        self.db.mature_block(self.block_id)
        payout_id = self.db.create_payout(self.db.eligible_payout_accounts(1))
        self.db.mark_payout_sent(payout_id, "cd" * 32)
        self.assertGreaterEqual(last, first)

    def tearDown(self):
        api.admin.live.base.DB_PATH = self.original_path
        for suffix in ("", "-wal", "-shm"):
            try:
                os.unlink(self.path + suffix)
            except FileNotFoundError:
                pass

    def test_account_summary_has_exact_amounts_and_performance(self):
        result = api.api_account_summary("yMinerA")
        self.assertIsNotNone(result)
        self.assertEqual(result["total_paid"], "2.98500000")
        self.assertEqual(result["paid_24h"], "2.98500000")
        self.assertEqual(result["accepted_shares"], 2)
        self.assertEqual(result["rejected_shares"], 1)
        self.assertEqual(len(result["workers"]), 2)
        self.assertIn("hashrate_24h", result)

    def test_paginated_account_histories(self):
        payments = api.api_account_payments("yMinerA", 1, 0)
        self.assertEqual(payments["pagination"]["total"], 1)
        self.assertEqual(payments["items"][0]["amount"], "2.98500000")

        changes = api.api_account_balance_changes("yMinerA", 2, 0)
        self.assertGreaterEqual(changes["pagination"]["total"], 2)
        self.assertLessEqual(len(changes["items"]), 2)

        earnings = api.api_account_daily_earnings("yMinerA", 30, 10, 0)
        self.assertEqual(earnings["items"][0]["earned"], "2.98500000")

        blocks = api.api_account_blocks("yMinerA", 10, 0)
        self.assertEqual(blocks["pagination"]["total"], 1)
        self.assertEqual(blocks["items"][0]["height"], 1000)

        detail = api.api_payout_detail(payments["items"][0]["id"])
        self.assertEqual(detail["recipient_count"], 1)
        self.assertEqual(detail["recipients"][0]["address"], "yMinerA")
        self.assertEqual(detail["recipients"][0]["amount"], "2.98500000")

    def test_v1_share_pagination_and_help(self):
        page = api.api_v1_list("shares", {"status": ["accepted"], "limit": ["1"], "offset": ["0"]})
        self.assertEqual(page["pagination"]["total"], 2)
        self.assertEqual(len(page["items"]), 1)
        self.assertTrue(page["pagination"]["has_more"])
        with self.db._connect() as con:
            rig1 = con.execute("SELECT id FROM workers WHERE name='rig1'").fetchone()[0]
        rejected = api.api_v1_list("shares", {"status": ["rejected"], "worker": [str(rig1)], "limit": ["25"], "offset": ["0"]})
        self.assertEqual(rejected["pagination"]["total"], 1)
        self.assertEqual(rejected["items"][0]["worker_id"], rig1)
        paths = {item["path"] for item in api.api_help()["endpoints"]}
        self.assertIn("/api/v1/shares", paths)
        self.assertIn("/api/account/{address}/earnings/daily", paths)

    def test_v1_block_pagination(self):
        page = api.api_v1_list("blocks", {"limit": ["1"], "offset": ["0"]})
        self.assertEqual(page["pagination"]["total"], 1)
        self.assertEqual(page["pagination"]["limit"], 1)
        self.assertEqual(len(page["items"]), 1)
        self.assertEqual(page["items"][0]["height"], 1000)

    def test_performance_returns_bounded_history(self):
        result = api.api_performance(address="yMinerA", hours=1, bucket_seconds=300)
        self.assertEqual(result["hours"], 1)
        self.assertEqual(result["bucket_seconds"], 300)
        self.assertEqual(len(result["history"]), 13)

    def test_worker_detail_includes_shares_rejections_and_blocks(self):
        with self.db._connect() as con:
            rig1 = con.execute("SELECT id FROM workers WHERE name='rig1'").fetchone()[0]
            rig2 = con.execute("SELECT id FROM workers WHERE name='rig2'").fetchone()[0]

        detail = api.api_worker_detail(rig1, hours=1, bucket_seconds=300, share_limit=10)
        self.assertEqual(detail["name"], "rig1")
        self.assertEqual(len(detail["recent_shares"]), 2)
        self.assertEqual(detail["rejection_reasons"][0]["reason"], "Unspecified")
        self.assertEqual(detail["blocks_found_total"], 0)
        self.assertIsNotNone(detail["last_share_difficulty"])

        finder = api.api_worker_detail(rig2, hours=1, bucket_seconds=300, share_limit=10)
        self.assertEqual(finder["blocks_found_total"], 1)
        self.assertEqual(finder["blocks_found"][0]["height"], 1000)


if __name__ == "__main__":
    unittest.main()

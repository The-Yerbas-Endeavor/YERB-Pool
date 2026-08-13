import os
import tempfile
import unittest

from yerbpool.accounting import AccountingDB


class AccountingTest(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.db = AccountingDB(self.path)

    def tearDown(self):
        for suffix in ("", "-wal", "-shm"):
            try:
                os.unlink(self.path + suffix)
            except FileNotFoundError:
                pass

    def test_proportional_round_maturity_and_payout(self):
        s1 = self.db.add_share("yMinerA.rig", "job1", 1.0, True)
        self.db.add_share("yMinerB.rig", "job1", 3.0, True)
        s3 = self.db.add_share("yMinerB.rig", "job1", 1.0, True, True)

        block_id = self.db.record_block(
            "yMinerB.rig", "job1", "00" * 32, 1000,
            500_000_000, 8_000_000_000, s3, 1100,
        )
        self.db.allocate_block_immature(block_id, 0.0)

        a = self.db.account_balance("yMinerA")
        b = self.db.account_balance("yMinerB")
        self.assertEqual(a["immature_balance_atomic"], 100_000_000)
        self.assertEqual(b["immature_balance_atomic"], 400_000_000)
        self.assertEqual(a["balance_atomic"], 0)

        self.db.update_block_confirmations(block_id, 99, 100)
        with self.db._connect() as con:
            self.assertEqual(con.execute("SELECT status FROM blocks WHERE id=?", (block_id,)).fetchone()[0], "submitted")

        self.db.update_block_confirmations(block_id, 100, 100)
        with self.db._connect() as con:
            self.assertEqual(con.execute("SELECT status FROM blocks WHERE id=?", (block_id,)).fetchone()[0], "confirmed")

        self.assertTrue(self.db.mature_block(block_id))
        a = self.db.account_balance("yMinerA")
        b = self.db.account_balance("yMinerB")
        self.assertEqual(a["balance_atomic"], 100_000_000)
        self.assertEqual(b["balance_atomic"], 400_000_000)
        self.assertEqual(a["immature_balance_atomic"], 0)

        eligible = self.db.eligible_payout_accounts(1)
        payout_id = self.db.create_payout(eligible)
        self.db.mark_payout_broadcasting(payout_id)
        self.db.mark_payout_sent(payout_id, "txid-test")

        self.assertEqual(self.db.account_balance("yMinerA")["balance_atomic"], 0)
        self.assertEqual(self.db.account_balance("yMinerB")["balance_atomic"], 0)
        self.assertEqual(self.db.account_balance("yMinerA")["total_paid_atomic"], 100_000_000)


if __name__ == "__main__":
    unittest.main()

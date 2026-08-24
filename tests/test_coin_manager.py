import tempfile
import unittest
from pathlib import Path

from yerbpool.coin_manager import deployment_plan, normalize_coin, save_coin


def sample(**overrides):
    data = {
        "slug": "exm", "name": "Example", "ticker": "EXM", "algorithm": "GhostRider",
        "domain": "exm.pool.yerbas.org", "stratum_port": 3334, "web_port": 8081,
        "rpc": {"url": "http://127.0.0.1:8332", "user": "rpcuser", "password": "secret"},
        "payouts": {"coinbase_maturity": 100, "minimum_payout": "1.0", "pool_fee_percent": 1, "check_interval_seconds": 7200},
    }
    data.update(overrides)
    return data


class CoinManagerTests(unittest.TestCase):
    def test_normalizes_identity(self):
        coin = normalize_coin(sample(slug="ExM", ticker="exm"))
        self.assertEqual(coin["slug"], "exm")
        self.assertEqual(coin["ticker"], "EXM")

    def test_rejects_invalid_domain(self):
        with self.assertRaisesRegex(ValueError, "hostname"):
            normalize_coin(sample(domain="not a domain"))

    def test_rejects_port_collision(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "coins.json"
            save_coin(sample(), path)
            with self.assertRaisesRegex(ValueError, "unique"):
                save_coin(sample(slug="two", ticker="TWO", domain="two.pool.yerbas.org", web_port=8082), path)

    def test_plan_uses_isolated_paths_and_services(self):
        plan = deployment_plan(sample())
        self.assertEqual(plan["install_dir"], "/opt/exm-pool")
        self.assertEqual(plan["database"], "/opt/exm-pool/exmpool.db")
        self.assertEqual(plan["pool_service"], "pool@exm.service")
        self.assertEqual(plan["web_service"], "pool-web@exm.service")
        self.assertEqual(plan["firewall"], [3334])


if __name__ == "__main__":
    unittest.main()

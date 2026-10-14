import threading
import time
import unittest
from unittest.mock import patch
import test_public_api as fixtures

api = fixtures.api


class DashboardPerformanceTest(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.PublicApiTest('test_paginated_account_histories')
        self.fixture.setUp()

    def tearDown(self):
        self.fixture.tearDown()

    def test_workers_keep_last_accepted_share_and_recent_hashrate(self):
        now = int(time.time())
        with patch('yerbpool.database.time.time', return_value=now-600):
            self.fixture.db.add_share('yOld.rig', 'old', 100, True)
        with patch('yerbpool.database.time.time', return_value=now):
            self.fixture.db.add_share('yOld.rig', 'new', 200, False)
        workers = {w['address']: w for w in api.admin.live.api_workers()}
        old = workers['yOld']
        self.assertEqual(old['last_share_at'], now-600)
        self.assertEqual(old['recent_diff'], 0)
        self.assertEqual(old['hashrate'], 0)
        self.assertTrue(old['active'])
        self.assertEqual(old['accepted_shares'], 1)
        self.assertEqual(old['rejected_shares'], 1)
        self.assertEqual(len(api.admin.live.api_workers(1)), 1)

    def test_luck_bucket_boundaries_match_raw_history(self):
        start = (int(time.time())//60)*60-137
        with self.fixture.db._connect() as con:
            con.execute('UPDATE blocks SET submitted_at=?', (start,))
        for timestamp in (start-1, start, start+1, ((start//60)+1)*60):
            with patch('yerbpool.database.time.time', return_value=timestamp):
                self.fixture.db.add_share('yBoundary.rig', 'boundary', 3, True)
        with self.fixture.db._connect() as con:
            expected = con.execute('SELECT COUNT(*),SUM(difficulty) FROM shares WHERE accepted=1 AND ts>?', (start,)).fetchone()
        result = api.admin.live._build_luck()
        self.assertEqual(result['round_accepted_shares'], expected[0])
        self.assertAlmostEqual(result['round_stratum_difficulty'], expected[1])

    def test_recent_queries_use_existing_time_range_index(self):
        with self.fixture.db._connect() as con:
            plan = con.execute('EXPLAIN QUERY PLAN SELECT worker_id,SUM(difficulty) FROM shares INDEXED BY idx_shares_ts_accepted_diff WHERE accepted=1 AND ts>=? GROUP BY worker_id', (int(time.time())-120,)).fetchall()
        self.assertTrue(any('idx_shares_ts_accepted_diff' in row[3] and 'ts>?' in row[3] for row in plan), plan)

    def test_stale_snapshot_returns_while_single_refresh_runs(self):
        live = api.admin.live
        cache = {'value': {'old': True}, 'db_path': live.base.DB_PATH, 'completed_at': 0}
        lock = threading.Lock()
        entered, release = threading.Event(), threading.Event()
        calls = []
        def build():
            calls.append(1)
            entered.set()
            release.wait(2)
            return {'new': True}
        try:
            self.assertEqual(live._cached_stat(cache, lock, 5, build), {'old': True})
            self.assertTrue(entered.wait(1))
            self.assertEqual(live._cached_stat(cache, lock, 5, build), {'old': True})
            self.assertEqual(len(calls), 1)
        finally:
            release.set()
            with lock:
                pass
        self.assertEqual(live._cached_stat(cache, lock, 5, build), {'new': True})
        self.assertEqual(len(calls), 1)

    def test_cache_lifetime_starts_after_calculation(self):
        live = api.admin.live
        cache = {}
        lock = threading.Lock()
        with patch.object(live.time, 'monotonic', side_effect=[100, 120, 121]):
            self.assertEqual(live._cached_stat(cache, lock, 5, lambda: 42), 42)
            self.assertEqual(live._cached_stat(cache, lock, 5, lambda: self.fail('Fresh cache rebuilt')), 42)

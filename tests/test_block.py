import unittest

from yerbpool.block import (
    compact_target,
    sha256d,
    stratum_prevhash,
    undo_stratum_prevhash,
)


class BlockHelpersTest(unittest.TestCase):
    def test_stratum_prevhash_roundtrip(self):
        display = "0123456789abcdef" * 4
        encoded = stratum_prevhash(display)
        self.assertEqual(undo_stratum_prevhash(encoded), bytes.fromhex(display)[::-1])

    def test_compact_target(self):
        self.assertEqual(
            compact_target("1d00ffff"),
            int("00000000ffff0000000000000000000000000000000000000000000000000000", 16),
        )

    def test_sha256d_size(self):
        self.assertEqual(len(sha256d(b"yerbas")), 32)


if __name__ == "__main__":
    unittest.main()

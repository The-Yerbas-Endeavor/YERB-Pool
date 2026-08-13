import unittest

from yerbpool.block import (
    _push_data,
    _script_num,
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

    def test_script_num_height_encoding(self):
        # 48350 = 0xBCDE. Since the high byte has its sign bit set,
        # CScriptNum appends a zero byte, and the push length is 3.
        encoded = _script_num(48350)
        self.assertEqual(encoded, bytes.fromhex("debc00"))
        self.assertEqual(_push_data(encoded), bytes.fromhex("03debc00"))


if __name__ == "__main__":
    unittest.main()

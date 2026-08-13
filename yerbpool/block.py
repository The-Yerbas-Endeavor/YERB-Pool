import hashlib
import struct

PUBKEY_ADDRESS = 140
SCRIPT_ADDRESS = 19


def sha256d(data: bytes) -> bytes:
    return hashlib.sha256(hashlib.sha256(data).digest()).digest()


def compact_size(n: int) -> bytes:
    if n < 0:
        raise ValueError("negative CompactSize")
    if n < 253:
        return bytes([n])
    if n <= 0xffff:
        return b"\xfd" + struct.pack("<H", n)
    if n <= 0xffffffff:
        return b"\xfe" + struct.pack("<I", n)
    return b"\xff" + struct.pack("<Q", n)


def _script_num(value: int) -> bytes:
    """Bitcoin/CScriptNum minimal little-endian signed-magnitude encoding."""
    value = int(value)
    if value < 0:
        raise ValueError("negative script number")
    if value == 0:
        return b""
    out = bytearray()
    while value:
        out.append(value & 0xff)
        value >>= 8
    if out[-1] & 0x80:
        out.append(0)
    return bytes(out)


def _push_data(data: bytes) -> bytes:
    if len(data) > 75:
        raise ValueError("small script push too large")
    return bytes([len(data)]) + data


def _b58decode(value: str) -> bytes:
    alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    num = 0
    for ch in value:
        try:
            digit = alphabet.index(ch)
        except ValueError as exc:
            raise ValueError("invalid base58 character") from exc
        num = num * 58 + digit
    raw = num.to_bytes((num.bit_length() + 7) // 8, "big") if num else b""
    pad = len(value) - len(value.lstrip("1"))
    return b"\x00" * pad + raw


def address_to_script(address: str) -> bytes:
    raw = _b58decode(address)
    if len(raw) != 25:
        raise ValueError("Yerbas address must decode to 25 bytes")
    payload, checksum = raw[:-4], raw[-4:]
    if sha256d(payload)[:4] != checksum:
        raise ValueError("Yerbas address checksum mismatch")
    version, h160 = payload[0], payload[1:]
    if version == PUBKEY_ADDRESS:
        return b"\x76\xa9\x14" + h160 + b"\x88\xac"
    if version == SCRIPT_ADDRESS:
        return b"\xa9\x14" + h160 + b"\x87"
    raise ValueError(f"unsupported Yerbas address version {version}")


def serialize_output(value: int, script: bytes) -> bytes:
    if value < 0:
        raise ValueError("negative transaction output")
    return struct.pack("<q", value) + compact_size(len(script)) + script


def template_outputs(template: dict, pool_address: str):
    required = []
    for key in ("smartnode", "superblock"):
        for item in template.get(key) or []:
            required.append((int(item["amount"]), bytes.fromhex(item["script"])))
    founder = template.get("founder") or {}
    if founder.get("script") and founder.get("amount") is not None:
        required.append((int(founder["amount"]), bytes.fromhex(founder["script"])))

    total = int(template["coinbasevalue"])
    required_total = sum(v for v, _ in required)
    miner_value = total - required_total
    if miner_value < 0:
        raise ValueError("required template payments exceed coinbasevalue")
    return [(miner_value, address_to_script(pool_address))] + required


def coinbase_parts(template: dict, pool_address: str, extranonce1_size=4, extranonce2_size=4):
    # Yerbas Core's IncrementExtraNonce() requires the block height to be the
    # first item in the coinbase scriptSig, even when DIP0003 CbTx is active.
    # cpuminer-opt-gr also reads the height from this exact location before it
    # starts GhostRider work.  Keep the height in coinb1 and place Stratum's
    # extranonces immediately after it.
    version_type = 3 | (5 << 16)
    height = int(template["height"])
    height_push = _push_data(_script_num(height))
    script_len = len(height_push) + extranonce1_size + extranonce2_size
    if script_len < 2 or script_len > 100:
        raise ValueError("coinbase scriptSig length out of consensus range")

    prefix = bytearray()
    prefix += struct.pack("<I", version_type)
    prefix += compact_size(1)
    prefix += b"\x00" * 32
    prefix += struct.pack("<I", 0xffffffff)
    prefix += compact_size(script_len)
    prefix += height_push

    suffix = bytearray()
    suffix += struct.pack("<I", 0xffffffff)
    outputs = template_outputs(template, pool_address)
    suffix += compact_size(len(outputs))
    for value, script in outputs:
        suffix += serialize_output(value, script)
    suffix += struct.pack("<I", 0)  # nLockTime

    # DIP0003 coinbase extra payload remains present; it is separate from the
    # consensus-required height item in scriptSig.
    payload = bytes.fromhex(template.get("coinbase_payload", ""))
    suffix += compact_size(len(payload))
    suffix += payload
    return bytes(prefix), bytes(suffix)


def tx_hashes(template: dict):
    # GBT "hash" is displayed big-endian. Merkle hashing uses uint256's raw
    # serialized byte order, hence the reversal.
    return [bytes.fromhex(tx["hash"])[::-1] for tx in template.get("transactions", [])]


def coinbase_merkle_branch(template: dict):
    nodes = [None] + tx_hashes(template)
    branch = []
    while len(nodes) > 1:
        if len(nodes) & 1:
            nodes.append(nodes[-1])
        sibling = nodes[1]
        if sibling is None:
            raise ValueError("invalid coinbase merkle tree")
        branch.append(sibling)
        nxt = []
        for i in range(0, len(nodes), 2):
            left, right = nodes[i], nodes[i + 1]
            if left is None or right is None:
                nxt.append(None)
            else:
                nxt.append(sha256d(left + right))
        nodes = nxt
    return branch


def merkle_root_from_coinbase(coinbase: bytes, branch):
    value = sha256d(coinbase)
    for sibling in branch:
        value = sha256d(value + sibling)
    return value


def stratum_prevhash(previousblockhash: str) -> str:
    desired = bytes.fromhex(previousblockhash)[::-1]
    out = bytearray()
    for i in range(0, 32, 4):
        out += desired[i:i + 4][::-1]
    return out.hex()


def undo_stratum_prevhash(value: str) -> bytes:
    raw = bytes.fromhex(value)
    if len(raw) != 32:
        raise ValueError("prevhash must be 32 bytes")
    out = bytearray()
    for i in range(0, 32, 4):
        out += raw[i:i + 4][::-1]
    return bytes(out)


def header_bytes(template: dict, merkle_root_raw: bytes, ntime_hex: str, nonce_hex: str) -> bytes:
    if len(merkle_root_raw) != 32:
        raise ValueError("merkle root must be 32 bytes")
    version = int(template["version"]) & 0xffffffff
    prev = bytes.fromhex(template["previousblockhash"])[::-1]
    ntime = int(ntime_hex, 16)
    bits = int(template["bits"], 16)
    nonce = int(nonce_hex, 16)
    return (
        struct.pack("<I", version)
        + prev
        + merkle_root_raw[::-1]
        + struct.pack("<I", ntime)
        + struct.pack("<I", bits)
        + struct.pack("<I", nonce)
    )


def compact_target(bits_hex: str) -> int:
    bits = int(bits_hex, 16)
    exponent = bits >> 24
    mantissa = bits & 0x007fffff
    if bits & 0x00800000:
        raise ValueError("negative compact target")
    if exponent <= 3:
        return mantissa >> (8 * (3 - exponent))
    return mantissa << (8 * (exponent - 3))


DIFF1_TARGET = int("00000000ffff0000000000000000000000000000000000000000000000000000", 16)


def share_target(difficulty: float) -> int:
    if difficulty <= 0:
        raise ValueError("difficulty must be positive")
    scaled = max(1, int(difficulty * 1_000_000))
    return (DIFF1_TARGET * 1_000_000) // scaled


def block_bytes(header: bytes, coinbase: bytes, template: dict) -> bytes:
    txs = [coinbase] + [bytes.fromhex(tx["data"]) for tx in template.get("transactions", [])]
    return header + compact_size(len(txs)) + b"".join(txs)

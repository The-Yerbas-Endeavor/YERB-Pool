class GhostRiderUnavailable(RuntimeError):
    pass


def hash_header(header80: bytes) -> bytes:
    """Return the 32-byte GhostRider hash for an 80-byte block header.

    This function is intentionally a hard stop until a verified native
    GhostRider implementation is wired in. Never accept shares without
    independent server-side hashing.
    """
    if len(header80) != 80:
        raise ValueError("GhostRider expects an 80-byte header")
    raise GhostRiderUnavailable(
        "GhostRider hashing backend is not installed. Wire a verified native implementation into yerbpool/ghostrider.py before accepting shares."
    )

import ctypes
import os
from pathlib import Path


class GhostRiderUnavailable(RuntimeError):
    pass


_LIB = None
_LOAD_ERROR = None


def _candidates():
    env = os.environ.get("YERB_GHOSTRIDER_LIB")
    if env:
        yield Path(env)
    root = Path(__file__).resolve().parent.parent
    yield root / "native" / "build" / "libyerb_ghostrider.so"
    yield root / "native" / "build" / "libyerb_ghostrider.dylib"
    yield root / "native" / "build" / "Release" / "yerb_ghostrider.dll"
    yield root / "native" / "build" / "yerb_ghostrider.dll"


def _load():
    global _LIB, _LOAD_ERROR
    if _LIB is not None:
        return _LIB
    last = None
    for path in _candidates():
        if not path.exists():
            continue
        try:
            lib = ctypes.CDLL(str(path))
            fn = lib.yerb_ghostrider_hash
            fn.argtypes = [
                ctypes.POINTER(ctypes.c_ubyte),
                ctypes.c_size_t,
                ctypes.POINTER(ctypes.c_ubyte),
            ]
            fn.restype = ctypes.c_int
            _LIB = lib
            return lib
        except OSError as exc:
            last = exc
    _LOAD_ERROR = last
    detail = f": {last}" if last else ""
    raise GhostRiderUnavailable(
        "native GhostRider library not found; run ./scripts/build-native.sh"
        + detail
    )


def ensure_available():
    _load()


def hash_header(header80: bytes) -> bytes:
    if len(header80) != 80:
        raise ValueError("GhostRider expects an 80-byte Yerbas block header")
    lib = _load()
    src = (ctypes.c_ubyte * 80).from_buffer_copy(header80)
    out = (ctypes.c_ubyte * 32)()
    rc = lib.yerb_ghostrider_hash(src, 80, out)
    if rc != 0:
        raise RuntimeError(f"native GhostRider hash failed with status {rc}")
    return bytes(out)

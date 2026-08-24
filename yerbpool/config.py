import json
from pathlib import Path
from urllib.parse import urlparse

DEFAULT_PATH = Path("config.json")
DEFAULT_RPC_URL = "http://127.0.0.1:15419"


def load_config(path=DEFAULT_PATH):
    path = Path(path)
    if not path.exists():
        raise SystemExit(f"Missing {path}. Copy config.example.json to config.json and edit it.")

    with path.open("r", encoding="utf-8") as f:
        cfg = json.load(f)

    for key in ("rpc", "stratum", "database", "pool_address"):
        if key not in cfg:
            raise SystemExit(f"Missing config key: {key}")

    rpc = cfg.setdefault("rpc", {})
    rpc.setdefault("url", DEFAULT_RPC_URL)
    if not rpc.get("user"):
        raise SystemExit("Missing config key: rpc.user")
    if not rpc.get("password"):
        raise SystemExit("Missing config key: rpc.password")

    parsed = urlparse(str(rpc.get("url", "")))
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in ("http", "https") or not host:
        raise SystemExit(
            f"Invalid rpc.url: {rpc.get('url')!r}. Expected a Yerbas daemon RPC endpoint such as {DEFAULT_RPC_URL}."
        )

    if host not in ("127.0.0.1", "localhost", "::1"):
        raise SystemExit(
            f"Unsafe rpc.url host: {host}. The pool should normally connect directly to the local Yerbas daemon. "
            f"Use {DEFAULT_RPC_URL} unless you intentionally run RPC on a trusted private host."
        )

    stratum = cfg.setdefault("stratum", {})
    stratum.setdefault("host", "0.0.0.0")
    stratum.setdefault("port", 3333)
    stratum.setdefault("difficulty", 0.05)
    vardiff = stratum.setdefault("vardiff", {})
    vardiff.setdefault("enabled", True)
    vardiff.setdefault("min_difficulty", 0.05)
    vardiff.setdefault("max_difficulty", 65536.0)
    vardiff.setdefault("target_share_seconds", 12)
    vardiff.setdefault("retarget_seconds", 60)
    vardiff.setdefault("variance_percent", 30)
    vardiff.setdefault("max_step_factor", 2.0)

    payouts = cfg.setdefault("payouts", {})
    payouts.setdefault("enabled", True)
    payouts.setdefault("coinbase_maturity", 100)
    payouts.setdefault("check_interval_seconds", 60)
    payouts.setdefault("minimum_payout", "1.00000000")
    payouts.setdefault("pool_fee_percent", 0.0)
    payouts.setdefault("transaction_fee_reserve", "0.01000000")

    coin = cfg.setdefault("coin", {})
    coin.setdefault("name", "Yerbas")
    coin.setdefault("ticker", "YERB")
    coin.setdefault("symbol", coin["ticker"])
    coin.setdefault("algorithm", "ghostrider")
    coin.setdefault("adapter", "yerbas")
    coin.setdefault("domain", "pool.yerbas.org")
    coin.setdefault("explorer_url", cfg.get("explorer_url", "https://explorer.yerbas.org"))
    coin.setdefault("decimals", 8)

    from yerbpool.coins import get_adapter
    get_adapter(cfg)

    cfg.setdefault("template_refresh_seconds", 5)
    cfg.setdefault("log_level", "INFO")

    return cfg

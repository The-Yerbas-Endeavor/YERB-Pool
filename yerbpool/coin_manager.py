"""Safe multi-coin registry and deployment-plan generation."""
import json
import re
import socket
from pathlib import Path

SLUG_RE = re.compile(r"^[a-z][a-z0-9-]{1,15}$")
TICKER_RE = re.compile(r"^[A-Z0-9]{2,10}$")
DOMAIN_RE = re.compile(r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,63}$")
DEFAULT_REGISTRY = Path("coins.json")

def _integer(value, name, low, high):
    value = int(value)
    if not low <= value <= high:
        raise ValueError(f"{name} must be between {low} and {high}")
    return value

def normalize_coin(data):
    coin = dict(data or {})
    slug = str(coin.get("slug", "")).strip().lower()
    ticker = str(coin.get("ticker", "")).strip().upper()
    domain = str(coin.get("domain", "")).strip().lower()
    if not SLUG_RE.fullmatch(slug): raise ValueError("slug must contain 2-16 lowercase letters, numbers, or hyphens")
    if not TICKER_RE.fullmatch(ticker): raise ValueError("ticker must contain 2-10 uppercase letters or numbers")
    if not DOMAIN_RE.fullmatch(domain): raise ValueError("domain must be a valid hostname")
    name, algorithm = str(coin.get("name", "")).strip(), str(coin.get("algorithm", "")).strip()
    if not name or not algorithm: raise ValueError("name and algorithm are required")
    pool_address = str(coin.get("pool_address", "")).strip()
    if not pool_address: raise ValueError("pool payout address is required")
    rpc, payouts = dict(coin.get("rpc") or {}), dict(coin.get("payouts") or {})
    fee = float(payouts.get("pool_fee_percent", 0))
    if not 0 <= fee <= 100: raise ValueError("pool_fee_percent must be between 0 and 100")
    return {"slug": slug, "name": name[:64], "ticker": ticker, "algorithm": algorithm[:64],
        "explorer_url": str(coin.get("explorer_url", "")).strip().rstrip("/"), "domain": domain,
        "pool_address": pool_address, "theme_color": str(coin.get("theme_color", "#2b7a3d"))[:16],
        "logo_url": str(coin.get("logo_url", "")).strip()[:512],
        "status": "draft", "stratum_port": _integer(coin.get("stratum_port", 3334), "stratum_port", 1024, 65535),
        "web_port": _integer(coin.get("web_port", 8081), "web_port", 1024, 65535),
        "rpc": {"url": str(rpc.get("url", "http://127.0.0.1:8332")).strip(), "user": str(rpc.get("user", "")).strip(), "password": str(rpc.get("password", ""))},
        "payouts": {"coinbase_maturity": _integer(payouts.get("coinbase_maturity", 100), "coinbase_maturity", 1, 100000),
            "minimum_payout": str(payouts.get("minimum_payout", "1.00000000")), "pool_fee_percent": fee,
            "check_interval_seconds": _integer(payouts.get("check_interval_seconds", 7200), "check_interval_seconds", 30, 604800)}}

def load_registry(path=DEFAULT_REGISTRY):
    path = Path(path)
    return [] if not path.exists() else list(json.loads(path.read_text(encoding="utf-8")).get("coins", []))

def save_coin(data, path=DEFAULT_REGISTRY):
    path, coin = Path(path), normalize_coin(data)
    coins = load_registry(path)
    for item in coins:
        if item.get("slug") != coin["slug"] and (item.get("domain") == coin["domain"] or int(item.get("stratum_port", 0)) == coin["stratum_port"] or int(item.get("web_port", 0)) == coin["web_port"]):
            raise ValueError("domain, Stratum port, and web port must be unique")
    coins = [item for item in coins if item.get("slug") != coin["slug"]] + [coin]
    path.write_text(json.dumps({"version": 1, "coins": coins}, indent=2) + "\n", encoding="utf-8")
    return coin

def validate_plan(coin):
    checks = []
    for label, port in (("Stratum", coin["stratum_port"]), ("Web", coin["web_port"])):
        sock = socket.socket()
        try: sock.bind(("127.0.0.1", int(port))); checks.append({"name": f"{label} port {port}", "ok": True, "detail": "available"})
        except OSError as exc: checks.append({"name": f"{label} port {port}", "ok": False, "detail": str(exc)})
        finally: sock.close()
    try: socket.getaddrinfo(coin["domain"], None); checks.append({"name": "DNS", "ok": True, "detail": "hostname resolves"})
    except OSError: checks.append({"name": "DNS", "ok": False, "detail": "DNS record not found yet"})
    credentials = bool(coin["rpc"]["user"] and coin["rpc"]["password"])
    checks.append({"name": "RPC credentials", "ok": credentials, "detail": "configured" if credentials else "missing"})
    return checks

def deployment_plan(data):
    coin = normalize_coin(data); slug = coin["slug"]
    return {"coin": coin, "install_dir": f"/opt/{slug}-pool", "database": f"/opt/{slug}-pool/{slug}pool.db",
        "config": f"/opt/{slug}-pool/config.json", "service_user": f"{slug}pool", "pool_service": f"pool@{slug}.service",
        "web_service": f"pool-web@{slug}.service", "nginx_site": f"/etc/nginx/sites-available/{slug}-pool",
        "dns": {"type": "A/AAAA", "name": coin["domain"]}, "firewall": [coin["stratum_port"]], "checks": validate_plan(coin)}

def activation_command(data, email):
    coin = normalize_coin(data); email = str(email or "").strip()
    if not EMAIL_RE.fullmatch(email): raise ValueError("a valid Certbot email is required")
    return f"sudo python3 /opt/yerb-pool/scripts/deploy-coin.py activate {coin['slug']} --email {email}"

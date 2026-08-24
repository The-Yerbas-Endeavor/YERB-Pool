#!/usr/bin/env python3
"""Apply an Admin-created coin draft using narrowly bounded system paths.

Run as root from the controller installation:
  sudo python3 scripts/deploy-coin.py activate SLUG --email admin@example.org
"""
import argparse
import json
import os
import pwd
import shutil
import socket
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from yerbpool.coin_manager import deployment_plan, load_registry
from yerbpool.coins import get_adapter
from yerbpool.rpc import YerbasRPC

SYSTEMD = Path("/etc/systemd/system")
NGINX_AVAILABLE = Path("/etc/nginx/sites-available")
NGINX_ENABLED = Path("/etc/nginx/sites-enabled")

def run(*args, check=True):
    return subprocess.run([str(x) for x in args], check=check, text=True, capture_output=True)

def require_root():
    if os.geteuid() != 0: raise SystemExit("This deployment helper must run as root.")

def find_coin(slug):
    coin = next((x for x in load_registry(ROOT / "coins.json") if x.get("slug") == slug), None)
    if not coin: raise SystemExit(f"Coin draft not found: {slug}")
    return coin

def dns_points_here(domain):
    resolved = {item[4][0] for item in socket.getaddrinfo(domain, 80, type=socket.SOCK_STREAM)}
    local = {item[4][0] for host in (socket.gethostname(), "localhost") for item in socket.getaddrinfo(host, 80, type=socket.SOCK_STREAM)}
    try:
        local.update(x.strip() for x in run("hostname", "-I").stdout.split() if x.strip())
    except Exception: pass
    if not resolved.intersection(local):
        raise SystemExit(f"DNS for {domain} does not resolve to this server. Resolved: {', '.join(sorted(resolved))}")

def render_config(coin, install_dir):
    source = json.loads((ROOT / "config.example.json").read_text())
    source["coin"] = {"name": coin["name"], "ticker": coin["ticker"], "symbol": coin["ticker"],
        "algorithm": coin["algorithm"].lower(), "adapter": "bitcoin-rpc", "domain": coin["domain"],
        "explorer_url": coin.get("explorer_url", ""), "decimals": 8}
    source["rpc"] = coin["rpc"]
    source["stratum"]["port"] = coin["stratum_port"]
    source.setdefault("web", {})["host"] = "127.0.0.1"
    source["web"]["port"] = coin["web_port"]
    source["database"] = str(install_dir / (coin["slug"] + "pool.db"))
    source["pool_address"] = coin["pool_address"]
    source["payouts"].update(coin["payouts"])
    source["explorer_url"] = coin.get("explorer_url", "")
    return source

def install_files(coin, plan):
    install_dir = Path(plan["install_dir"]); user = plan["service_user"]
    try: pwd.getpwnam(user)
    except KeyError: run("useradd", "--system", "--home", install_dir, "--shell", "/usr/sbin/nologin", user)
    install_dir.mkdir(parents=True, exist_ok=True)
    run("rsync", "-a", "--delete", "--exclude=.git/", "--exclude=config.json", "--exclude=coins.json",
        "--exclude=*.db", "--exclude=*.db-wal", "--exclude=*.db-shm", str(ROOT) + "/", str(install_dir) + "/")
    config_path = install_dir / "config.json"
    if not config_path.exists(): config_path.write_text(json.dumps(render_config(coin, install_dir), indent=2) + "\n")
    shutil.chown(install_dir, user=user, group=user)
    run("chown", "-R", f"{user}:{user}", install_dir)
    config_path.chmod(0o600)
    return install_dir, user

def install_services(coin):
    shutil.copy2(ROOT / "systemd/pool@.service", SYSTEMD / "pool@.service")
    shutil.copy2(ROOT / "systemd/pool-web@.service", SYSTEMD / "pool-web@.service")
    run("systemctl", "daemon-reload")
    run("systemctl", "enable", f"pool@{coin['slug']}.service", f"pool-web@{coin['slug']}.service")

def install_nginx(coin):
    template = (ROOT / "nginx/coin-pool.conf.template").read_text()
    rendered = template.replace("__DOMAIN__", coin["domain"]).replace("__WEB_PORT__", str(coin["web_port"])).replace("__SLUG__", coin["slug"])
    site = NGINX_AVAILABLE / f"{coin['slug']}-pool"
    backup = site.read_bytes() if site.exists() else None
    site.write_text(rendered)
    enabled = NGINX_ENABLED / site.name
    if enabled.is_symlink() or enabled.exists(): enabled.unlink()
    enabled.symlink_to(site)
    result = run("nginx", "-t", check=False)
    if result.returncode:
        if backup is None: site.unlink(missing_ok=True); enabled.unlink(missing_ok=True)
        else: site.write_bytes(backup)
        raise SystemExit("Nginx validation failed:\n" + result.stderr)
    run("systemctl", "reload", "nginx")

def activate_certbot(coin, email):
    dns_points_here(coin["domain"])
    if not shutil.which("certbot"):
        run("apt-get", "update"); run("apt-get", "install", "-y", "certbot", "python3-certbot-nginx")
    run("certbot", "--nginx", "--non-interactive", "--agree-tos", "--redirect",
        "--keep-until-expiring", "--email", email, "-d", coin["domain"])
    run("nginx", "-t"); run("systemctl", "reload", "nginx")

def activate(slug, email):
    require_root(); coin = find_coin(slug); plan = deployment_plan(coin)
    if coin["algorithm"].lower() != "ghostrider":
        raise SystemExit("Activation currently supports GhostRider coins only; add a verified algorithm adapter first.")
    config = render_config(coin, Path(plan["install_dir"]))
    adapter = get_adapter(config)
    adapter.validate_daemon(YerbasRPC(coin["rpc"]))
    install_files(coin, plan); install_services(coin); install_nginx(coin)
    run("systemctl", "restart", f"pool@{slug}.service", f"pool-web@{slug}.service")
    if shutil.which("ufw"):
        run("ufw", "allow", f"{coin['stratum_port']}/tcp", check=False)
        run("ufw", "allow", "80/tcp", check=False); run("ufw", "allow", "443/tcp", check=False)
    activate_certbot(coin, email)
    print(json.dumps({"ok": True, "coin": coin["ticker"], "website": "https://" + coin["domain"],
        "stratum": f"stratum+tcp://{coin['domain']}:{coin['stratum_port']}"}, indent=2))

def main():
    parser=argparse.ArgumentParser(); sub=parser.add_subparsers(dest="command", required=True)
    command=sub.add_parser("activate"); command.add_argument("slug"); command.add_argument("--email", required=True)
    args=parser.parse_args()
    if args.command == "activate": activate(args.slug, args.email)

if __name__ == "__main__": main()

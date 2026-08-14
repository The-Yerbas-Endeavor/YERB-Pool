#!/usr/bin/env python3
import getpass
import hashlib
import json
import os
import secrets
from pathlib import Path


def hash_password(password, iterations=310000):
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return {
        "scheme": "pbkdf2_sha256",
        "iterations": iterations,
        "salt": salt.hex(),
        "hash": digest.hex(),
    }


def main():
    config_path = Path("/opt/yerb-pool/config.json")
    if not config_path.exists():
        config_path = Path("config.json")
    if not config_path.exists():
        raise SystemExit("config.json not found")

    cfg = json.loads(config_path.read_text(encoding="utf-8"))
    admin = cfg.setdefault("admin", {})
    username = input(f"Admin username [{admin.get('username', 'admin')}]: ").strip() or admin.get("username", "admin")
    password = getpass.getpass("New admin password: ")
    confirm = getpass.getpass("Confirm admin password: ")
    if not password:
        raise SystemExit("Password cannot be empty")
    if password != confirm:
        raise SystemExit("Passwords do not match")

    admin.clear()
    admin.update({"username": username, "password_hash": hash_password(password)})
    config_path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    try:
        os.chmod(config_path, 0o600)
    except PermissionError:
        pass
    print(f"Admin credentials updated for user: {username}")
    print("Restart yerb-pool-web.service to load the new credentials.")


if __name__ == "__main__":
    main()

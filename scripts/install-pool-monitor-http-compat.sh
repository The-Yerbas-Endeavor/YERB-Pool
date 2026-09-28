#!/usr/bin/env bash
set -euo pipefail

SITE="${1:-/etc/nginx/sites-available/yerb-pool}"
MARKER="pool-monitor-http-compat"

if [[ "${EUID}" -ne 0 ]]; then
    echo "Run with sudo: sudo bash scripts/install-pool-monitor-http-compat.sh" >&2
    exit 1
fi

if [[ ! -f "$SITE" ]]; then
    echo "ERROR: Nginx site not found: $SITE" >&2
    exit 1
fi

backup="${SITE}.bak.$(date +%Y%m%d-%H%M%S)"
cp "$SITE" "$backup"

python3 - "$SITE" <<'PY'
import re
import sys
from pathlib import Path

path = Path(sys.argv[1])
text = path.read_text()
compat_regex = r'^/api/(?:summary|stats|status|pool_stats|poolstats|luck|health|blocks|network(?:/stats)?|pool/stats|mps(?:\\.json)?|pools(?:/yerbas(?:/blocks)?)?|pool/yerbas/blocks)
PY

if ! nginx -t; then
    echo "ERROR: Nginx validation failed; restoring $backup" >&2
    cp "$backup" "$SITE"
    nginx -t || true
    exit 1
fi

systemctl reload nginx

echo "Installed/updated pool-monitor HTTP compatibility."
echo "Backup: $backup"
echo
echo "Public monitor endpoints now proxy directly over HTTP; all other HTTP paths still redirect to HTTPS."


if "pool-monitor-http-compat" in text:
    pattern = re.compile(
        r'(?m)^(?P<indent>[ \t]*)location ~ \^/api/\(\?:.*?\)\$ \{
PY

if ! nginx -t; then
    echo "ERROR: Nginx validation failed; restoring $backup" >&2
    cp "$backup" "$SITE"
    nginx -t || true
    exit 1
fi

systemctl reload nginx

echo "Installed pool-monitor HTTP compatibility."
echo "Backup: $backup"
echo
echo "Public monitor endpoints now proxy directly over HTTP; all other HTTP paths still redirect to HTTPS."

    )
    match = pattern.search(text)
    if not match:
        raise SystemExit("ERROR: Could not locate the installed pool-monitor compatibility location.")
    indent = match.group("indent")
    replacement = f"{indent}location ~ {compat_regex} {{"
    text = text[:match.start()] + replacement + text[match.end():]
else:
    pattern = re.compile(
        r'(?m)^(?P<indent>[ \t]*)return 301 https://\$host\$request_uri;[ \t]*
PY

if ! nginx -t; then
    echo "ERROR: Nginx validation failed; restoring $backup" >&2
    cp "$backup" "$SITE"
    nginx -t || true
    exit 1
fi

systemctl reload nginx

echo "Installed pool-monitor HTTP compatibility."
echo "Backup: $backup"
echo
echo "Public monitor endpoints now proxy directly over HTTP; all other HTTP paths still redirect to HTTPS."

    )
    match = pattern.search(text)
    if not match:
        raise SystemExit("ERROR: Could not find the HTTP -> HTTPS return 301 line.")

    indent = match.group("indent")
    block = f'''{indent}# pool-monitor-http-compat
{indent}location ~ {compat_regex} {{
{indent}    proxy_pass http://127.0.0.1:8080;
{indent}    proxy_http_version 1.1;
{indent}    proxy_set_header Host $host;
{indent}    proxy_set_header X-Real-IP $remote_addr;
{indent}    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
{indent}    proxy_set_header X-Forwarded-Proto $scheme;
{indent}    proxy_read_timeout 30s;
{indent}}}

{indent}location / {{
{indent}    return 301 https://$host$request_uri;
{indent}}}'''
    text = text[:match.start()] + block + text[match.end():]

path.write_text(text)
PY

if ! nginx -t; then
    echo "ERROR: Nginx validation failed; restoring $backup" >&2
    cp "$backup" "$SITE"
    nginx -t || true
    exit 1
fi

systemctl reload nginx

echo "Installed pool-monitor HTTP compatibility."
echo "Backup: $backup"
echo
echo "Public monitor endpoints now proxy directly over HTTP; all other HTTP paths still redirect to HTTPS."

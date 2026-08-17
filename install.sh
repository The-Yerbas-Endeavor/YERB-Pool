#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

bash "$ROOT/scripts/install.sh" "$@"

# Apply host-level security after the application is installed so the
# installer can safely allow the actual SSH, HTTP(S), and Stratum ports before
# enabling the default-deny firewall policy.
bash "$ROOT/scripts/security-hardening.sh"

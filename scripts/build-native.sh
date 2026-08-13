#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if command -v apt-get >/dev/null 2>&1; then
    if ! dpkg-query -W -f='${Status}' libboost-dev 2>/dev/null | grep -q 'install ok installed'; then
        echo "Installing required Boost headers (libboost-dev)..."
        apt-get update
        apt-get install -y libboost-dev
    fi
fi

cmake -S "$ROOT/native" -B "$ROOT/native/build" -DCMAKE_BUILD_TYPE=Release
cmake --build "$ROOT/native/build" --config Release -j"$(nproc 2>/dev/null || echo 2)"
echo "GhostRider native library built in $ROOT/native/build"

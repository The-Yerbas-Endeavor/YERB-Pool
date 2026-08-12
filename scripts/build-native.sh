#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cmake -S "$ROOT/native" -B "$ROOT/native/build" -DCMAKE_BUILD_TYPE=Release
cmake --build "$ROOT/native/build" --config Release -j"$(nproc 2>/dev/null || echo 2)"
echo "GhostRider native library built in $ROOT/native/build"

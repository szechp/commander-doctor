#!/usr/bin/env bash
# Moved to forge-spike/setup-forge.sh; kept so existing environment setup
# scripts that call this path keep working.
exec "$(cd "$(dirname "$0")/../.." && pwd)/forge-spike/setup-forge.sh" "$@"

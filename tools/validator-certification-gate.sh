#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

# The Python gate is the evidence authority.  This wrapper only provides the
# canonical repository entry point and leaves non-pass manifest gaps visible.
exec python3 tools/validator-certification-gate.py "$@"

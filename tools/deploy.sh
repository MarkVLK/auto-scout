#!/bin/bash
# Compatibility wrapper for the clean-slate CLI deployment path.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
exec "${REPO_ROOT}/auto-scout" deploy scout "$@"

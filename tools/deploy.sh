#!/bin/bash
# Compatibility wrapper for the clean-slate CLI deployment path.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ROLE="${1:-scout}"
if [[ "${ROLE}" == "scout" || "${ROLE}" == "companion" ]]; then
  shift
  exec "${REPO_ROOT}/auto-scout" deploy "${ROLE}" "$@"
fi

exec "${REPO_ROOT}/auto-scout" deploy scout "$@"

#!/usr/bin/env bash
set -euo pipefail

KNOWN_HOSTS="${AUTO_SCOUT_KNOWN_HOSTS:-${HOME}/.ssh/known_hosts}"

if [ "$#" -gt 0 ]; then
  HOSTS=("$@")
else
  HOSTS=("moorebot-scout.local" "auto-scout-pi5.local")
fi

mkdir -p "$(dirname "${KNOWN_HOSTS}")"
touch "${KNOWN_HOSTS}"
chmod 700 "$(dirname "${KNOWN_HOSTS}")"
chmod 600 "${KNOWN_HOSTS}"

for host in "${HOSTS[@]}"; do
  if ssh-keygen -F "${host}" -f "${KNOWN_HOSTS}" >/dev/null; then
    printf '%s already present in %s\n' "${host}" "${KNOWN_HOSTS}"
    continue
  fi

  printf 'Adding SSH host key for %s to %s\n' "${host}" "${KNOWN_HOSTS}"
  ssh-keyscan -H "${host}" >> "${KNOWN_HOSTS}"
done

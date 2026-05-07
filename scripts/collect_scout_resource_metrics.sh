#!/bin/bash
set -euo pipefail

METRICS_DIR="${AUTO_SCOUT_RESOURCE_METRICS_DIR:-/userdata/auto-scout/resource-metrics}"
MAX_AGE_DAYS="${AUTO_SCOUT_RESOURCE_METRICS_MAX_AGE_DAYS:-14}"
TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUTPUT="${METRICS_DIR}/snapshot-${TIMESTAMP}.txt"
TEMP_OUTPUT="${OUTPUT}.tmp"

mkdir -p "${METRICS_DIR}"

{
  printf "timestamp_utc=%s\n" "${TIMESTAMP}"

  printf "\n[uptime]\n"
  uptime || true
  cat /proc/loadavg || true

  printf "\n[memory]\n"
  free -m || true

  printf "\n[swaps]\n"
  cat /proc/swaps || true

  printf "\n[vmstat]\n"
  vmstat 1 3 || true

  printf "\n[disk]\n"
  df -h / /userdata /tmp 2>/dev/null || df -h || true

  printf "\n[top_rss]\n"
  ps -eo pid,ppid,comm,%cpu,%mem,rss,args --sort=-rss | head -30 || true

  printf "\n[top_cpu]\n"
  ps -eo pid,ppid,comm,%cpu,%mem,rss,args --sort=-%cpu | head -30 || true

  printf "\n[auto_scout_processes]\n"
  ps -eo pid,ppid,etimes,%cpu,%mem,rss,args | grep -E '/auto-scout/|auto-scout' | grep -v grep || true
} > "${TEMP_OUTPUT}"

mv "${TEMP_OUTPUT}" "${OUTPUT}"
find "${METRICS_DIR}" -type f -name 'snapshot-*.txt' -mtime "+${MAX_AGE_DAYS}" -delete

#!/usr/bin/env bash
# scripts/status.sh -- lists every stage run so far under results/, with exit code, elapsed
# time (from the .time file, if /usr/bin/time -v was available), sampled memory peak (for
# pipeline stages), and whether a pipeline is still running.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./_common.sh
source "${SCRIPT_DIR}/_common.sh"

echo "=== Bundle status (${RESULTS_DIR}) ==="
shopt -s nullglob
FOUND=0
for exitf in "${RESULTS_DIR}"/*.exit; do
    FOUND=1
    label="$(basename "${exitf}" .exit)"
    rc="$(cat "${exitf}" 2>/dev/null || echo '?')"
    timef="${RESULTS_DIR}/${label}.time"
    elapsed="n/a"
    peak="n/a"
    if [[ -f "${timef}" ]]; then
        elapsed="$(grep -i 'Elapsed (wall clock) time' "${timef}" 2>/dev/null | sed 's/.*: *//' | head -1 || true)"
        if [[ -z "${elapsed}" ]]; then
            elapsed="n/a"
        fi
        peak_kb="$(grep -i 'Maximum resident set size' "${timef}" 2>/dev/null | grep -oE '[0-9]+' | head -1 || true)"
        if [[ -n "${peak_kb:-}" ]]; then
            peak="$(awk "BEGIN{printf \"%.3f GiB\", ${peak_kb}/1024/1024}")"
        fi
    fi
    memfile="${RESULTS_DIR}/${label}_memory_samples.txt"
    if [[ -f "${memfile}" ]]; then
        sampled_peak="$(awk '{print $2}' "${memfile}" 2>/dev/null | sort -g | tail -1 || true)"
        if [[ -n "${sampled_peak:-}" ]]; then
            peak="${sampled_peak} GiB (whole process tree, sampled)"
        fi
    fi
    status="done"
    if [[ "${label}" == pipeline_* ]]; then
        pidf="${RESULTS_DIR}/${label}.pid"
        if [[ -f "${pidf}" ]]; then
            pid="$(cat "${pidf}")"
            if kill -0 "${pid}" 2>/dev/null; then
                status="RUNNING (pid ${pid})"
                rc="(running)"
            fi
        fi
    fi
    printf "  %-28s exit=%-10s elapsed=%-14s peak=%-30s %s\n" "${label}" "${rc}" "${elapsed}" "${peak}" "${status}"
done
if [[ "${FOUND}" -eq 0 ]]; then
    echo "  (no stages have been run yet -- start with scripts/setup_env.sh)"
fi

echo
echo "=== In-progress pipeline runs ==="
ANY_RUNNING=0
for pidf in "${RESULTS_DIR}"/pipeline_*.pid; do
    [[ -f "${pidf}" ]] || continue
    label="$(basename "${pidf}" .pid)"
    pid="$(cat "${pidf}")"
    if kill -0 "${pid}" 2>/dev/null; then
        ANY_RUNNING=1
        echo "  ${label}: PID ${pid} still running. Tail its log with:"
        echo "    tail -f ${RESULTS_DIR}/${label}.stdout ${RESULTS_DIR}/${label}.stderr"
        memfile="${RESULTS_DIR}/${label}_memory_samples.txt"
        if [[ -f "${memfile}" ]]; then
            echo "    latest memory sample: $(tail -1 "${memfile}" 2>/dev/null || echo n/a)"
        fi
    fi
done
if [[ "${ANY_RUNNING}" -eq 0 ]]; then
    echo "  (none)"
fi

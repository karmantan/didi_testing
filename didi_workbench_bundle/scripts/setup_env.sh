#!/usr/bin/env bash
# scripts/setup_env.sh [--self-test]
#
# Creates venv_didi inside this bundle with a pinned Python 3.9.x interpreter (found via
# bundle_settings.env's PYTHON_CANDIDATES) and the exact package versions in
# requirements.txt. Run this first, on Workbench, before anything else.
#
# --self-test: instead of (re)building the venv, runs `python psm_260915.py --self-test`
# under /usr/bin/time -v, saves stdout/stderr/timing to results/, and prints PASS/FAIL with
# elapsed time and peak memory. Run this AFTER a plain `setup_env.sh` has succeeded once.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./_common.sh
source "${SCRIPT_DIR}/_common.sh"

run_self_test() {
    local py="${VENV_DIR}/bin/python"
    if [[ ! -x "${py}" ]]; then
        echo "ERROR: venv_didi not found. Run 'scripts/setup_env.sh' (without --self-test) first." >&2
        exit 1
    fi
    local out="${RESULTS_DIR}/self_test.stdout"
    local err="${RESULTS_DIR}/self_test.stderr"
    local timef="${RESULTS_DIR}/self_test.time"
    local exitf="${RESULTS_DIR}/self_test.exit"
    echo "Running 'python psm_260915.py --self-test' under /usr/bin/time -v ..."
    set +e
    if command -v /usr/bin/time >/dev/null 2>&1 && /usr/bin/time -v true >/dev/null 2>&1; then
        /usr/bin/time -v -o "${timef}" "${py}" "${BUNDLE_ROOT}/psm_260915.py" --self-test \
            > "${out}" 2> "${err}"
        rc=$?
    else
        # macOS (BSD) has no -v flag and no free peak-RSS report; fall back to /usr/bin/time
        # plain form, and note this limitation plainly instead of pretending we measured it.
        echo "NOTE: /usr/bin/time -v is not available on this OS (this looks like macOS)." \
            | tee "${timef}"
        echo "Peak memory will NOT be measured here; it WILL be measured on the Linux Workbench session." \
            | tee -a "${timef}"
        { time "${py}" "${BUNDLE_ROOT}/psm_260915.py" --self-test > "${out}" 2> "${err}"; } 2>> "${timef}"
        rc=$?
    fi
    set -e
    echo "$rc" > "${exitf}"
    if [[ "$rc" -eq 0 ]] && grep -q '"status": "PASS"' "${out}"; then
        echo "SELF-TEST: PASS (exit 0, status=PASS in output). See ${out}, ${timef}."
    else
        echo "SELF-TEST: FAIL (exit ${rc}). See ${out}, ${err}, ${timef}."
    fi
    if grep -qi "Maximum resident set size" "${timef}" 2>/dev/null; then
        grep -i "Elapsed (wall clock) time\|Maximum resident set size" "${timef}"
    fi
    return "$rc"
}

if [[ "${1:-}" == "--self-test" ]]; then
    run_self_test
    exit $?
fi

echo "=== scripts/setup_env.sh ==="
echo "Bundle root: ${BUNDLE_ROOT}"

PY39="$(find_python39 || true)"
if [[ -z "${PY39}" ]]; then
    echo
    echo "ERROR: no Python 3.9.x interpreter was found among PYTHON_CANDIDATES in bundle_settings.env:"
    load_settings
    echo "  ${SETTING_PYTHON_CANDIDATES:-<unset>}"
    echo
    echo "On Posit Workbench: start (or restart) this Jupyter session with Python 3.9.1"
    echo "explicitly selected in the session launcher's Python version dropdown, then re-run"
    echo "this script. If 3.9.1 is not offered, run 'ls /opt/python' to see what IS installed"
    echo "-- any 3.9.x patch is acceptable -- and if none exists, ask your Workbench admin to"
    echo "install one. Do NOT proceed with a 3.10+/3.8- interpreter: the pinned polars==0.20.16"
    echo "and numpy==1.25.0 wheels in requirements.txt are tied to the CPython 3.9 ABI and will"
    echo "either fail to install or silently misbehave under a different major/minor version."
    exit 1
fi
PY39_VERSION="$("${PY39}" -c 'import sys; print(".".join(map(str, sys.version_info[:3])))')"
echo "Found Python 3.9.x: ${PY39} (version ${PY39_VERSION})"
if [[ "${PY39_VERSION}" != "3.9.1" ]]; then
    echo "  NOTE: this is Python ${PY39_VERSION}, not exactly 3.9.1. Proceeding, since any 3.9.x"
    echo "  patch is acceptable per this bundle's rules -- but if something behaves differently"
    echo "  than the real run, this patch difference is the first thing to check."
fi

if [[ ! -d "${VENV_DIR}" ]]; then
    echo "Creating venv at ${VENV_DIR} ..."
    "${PY39}" -m venv "${VENV_DIR}"
else
    echo "venv_didi already exists at ${VENV_DIR}; reusing it."
fi

VENV_PY="${VENV_DIR}/bin/python"
echo "Upgrading pip ..."
"${VENV_PY}" -m pip install --no-cache-dir --upgrade pip >/dev/null

echo "Installing pinned requirements from requirements.txt ..."
REQ_FAIL=0
while IFS= read -r line; do
    line="${line%%#*}"
    line="$(echo "${line}" | xargs || true)"
    [[ -z "${line}" ]] && continue
    echo "  pip install ${line}"
    if ! "${VENV_PY}" -m pip install --no-cache-dir "${line}"; then
        echo "  FAILED to install pin: ${line}"
        REQ_FAIL=1
        break
    fi
done < "${BUNDLE_ROOT}/requirements.txt"

if [[ "${REQ_FAIL}" -ne 0 ]]; then
    echo
    echo "ERROR: a pinned dependency failed to install (see the failing line above)."
    echo "This script does NOT substitute a different version -- fix requirements.txt or the"
    echo "environment (e.g. missing system build tools for a package with no wheel for this"
    echo "platform/Python combination) and re-run."
    exit 1
fi

echo
echo "Running 'python psm_260915.py --environment-check' ..."
ENV_CHECK_JSON="${RESULTS_DIR}/environment_check.json"
if ! "${VENV_PY}" "${BUNDLE_ROOT}/psm_260915.py" --environment-check > "${ENV_CHECK_JSON}.tmp" 2> "${RESULTS_DIR}/environment_check.stderr"; then
    echo "ERROR: 'python psm_260915.py --environment-check' exited non-zero. See ${RESULTS_DIR}/environment_check.stderr."
    cat "${RESULTS_DIR}/environment_check.stderr" >&2
    exit 1
fi
mv "${ENV_CHECK_JSON}.tmp" "${ENV_CHECK_JSON}"

"${VENV_PY}" - "${ENV_CHECK_JSON}" << 'PYEOF'
import json, sys
path = sys.argv[1]
d = json.load(open(path))
py = d.get("python", "unknown")
target_py = d.get("target_python", "3.9.1")
polars_v = d.get("polars_version", "unknown")
target_polars = d.get("target_polars", "0.20.16")
streaming = d.get("streaming_collect_mode", "unknown")
roundtrip = d.get("polars_pandas_roundtrip_ok", None)

print()
print("=== Environment check (results/environment_check.json) ===")
py_head = py.split()[0] if py else "unknown"
if py_head == target_py:
    print(f"Python: {py_head} -- EXACT match to target {target_py}.")
elif py_head.startswith("3.9."):
    print(f"Python: {py_head} -- a different 3.9.x patch than target {target_py} (acceptable).")
else:
    print(f"Python: {py_head} -- DOES NOT match the required 3.9.x line (target {target_py}). This is a problem.")

if polars_v == target_polars:
    print(f"Polars: {polars_v} -- EXACT match to target {target_polars}.")
else:
    print(f"Polars: {polars_v} -- DOES NOT match target {target_polars}. This is a problem: re-check requirements.txt install.")

if streaming == "streaming=True":
    print(f"Streaming collect mode: '{streaming}' -- matches the real 20% run's runtime log line exactly.")
else:
    print(f"Streaming collect mode: '{streaming}' -- differs from the real run's 'streaming=True'; note this, it may still be fine on a newer/older polars build.")

if roundtrip is True:
    print("Pandas/Arrow round-trip: PASSED.")
elif roundtrip is False:
    print(f"Pandas/Arrow round-trip: FAILED -- error: {d.get('error')}")
else:
    print("Pandas/Arrow round-trip: status unknown (key not found in output).")
print()
print(f"Full JSON saved at {path}")
PYEOF

echo
echo "setup_env.sh complete. Next: 'scripts/setup_env.sh --self-test', then 'python scripts/check_machine.py'."

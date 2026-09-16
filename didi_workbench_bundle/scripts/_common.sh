#!/usr/bin/env bash
# _common.sh -- sourced by every other .sh script in this folder. Not a standalone entry
# point. Resolves the bundle root from its own location (never an absolute path), loads
# bundle_settings.env, and finds a usable Python 3.9.x interpreter.
set -euo pipefail

# BASH_SOURCE[0] is this file's own path; walk up to the bundle root regardless of the
# caller's current working directory.
_COMMON_SH_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUNDLE_ROOT="$(cd "${_COMMON_SH_DIR}/.." && pwd)"
RESULTS_DIR="${BUNDLE_ROOT}/results"
VENV_DIR="${BUNDLE_ROOT}/venv_didi"
mkdir -p "${RESULTS_DIR}"

load_settings() {
    # Populate shell variables from bundle_settings.env (KEY=value, no quoting, # comments).
    local settings_file="${BUNDLE_ROOT}/bundle_settings.env"
    if [[ ! -f "${settings_file}" ]]; then
        echo "ERROR: ${settings_file} not found." >&2
        exit 1
    fi
    while IFS='=' read -r key value; do
        [[ -z "${key}" || "${key}" == \#* ]] && continue
        # Trim any trailing carriage return (defensive; the bundle is authored with LF only).
        value="${value%$'\r'}"
        export "SETTING_${key}=${value}"
    done < "${settings_file}"
}

data_root() {
    load_settings
    local raw="${SETTING_DATA_ROOT:-../didi_data}"
    python3 - "$BUNDLE_ROOT" "$raw" << 'PYEOF'
import sys, os
bundle_root, raw = sys.argv[1], sys.argv[2]
print(os.path.normpath(os.path.join(bundle_root, raw)))
PYEOF
}

find_python39() {
    # Try each candidate in bundle_settings.env's PYTHON_CANDIDATES, in order; return the
    # first one that reports major.minor == 3.9. Globs (e.g. /opt/python/3.9.*/bin/python3)
    # are expanded. Never falls back to a non-3.9 interpreter.
    load_settings
    local candidates="${SETTING_PYTHON_CANDIDATES:-python3.9:python3}"
    local IFS=':'
    local -a parts
    read -ra parts <<< "${candidates}"
    for pattern in "${parts[@]}"; do
        for candidate in ${pattern}; do
            [[ -x "$(command -v "${candidate}" 2>/dev/null)" ]] || continue
            local resolved
            resolved="$(command -v "${candidate}")"
            local ver
            ver="$("${resolved}" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || true)"
            if [[ "${ver}" == "3.9" ]]; then
                echo "${resolved}"
                return 0
            fi
        done
    done
    return 1
}

bundle_python() {
    # The interpreter to use for running bundle scripts after setup_env.sh has created
    # venv_didi: prefer the venv, fall back to a bare 3.9 interpreter (e.g. for
    # check_machine.py, which has no third-party dependencies and can run pre-venv).
    if [[ -x "${VENV_DIR}/bin/python" ]]; then
        echo "${VENV_DIR}/bin/python"
    elif py="$(find_python39)"; then
        echo "${py}"
    else
        echo "ERROR: no venv_didi and no Python 3.9.x interpreter found. Run scripts/setup_env.sh first." >&2
        exit 1
    fi
}

timestamp() {
    date -u +"%Y-%m-%dT%H:%M:%SZ"
}

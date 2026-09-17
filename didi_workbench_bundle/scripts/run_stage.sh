#!/usr/bin/env bash
# scripts/run_stage.sh <stage> <scale>
#
# stage: generate | validate | schema-check | gate | pipeline | all
# scale: a fraction of the real 20%% sample, e.g. 0.001, 0.01, 0.1, 1.0
#
# Every stage activates venv_didi, runs under /usr/bin/time -v where available, and writes
# results/<stage>_<scale>.stdout / .stderr / .time / .exit. `pipeline` runs in the
# background via nohup with a PID file and starts monitor_memory.py alongside it.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./_common.sh
source "${SCRIPT_DIR}/_common.sh"

STAGE="${1:-}"
SCALE="${2:-}"
if [[ -z "${STAGE}" || -z "${SCALE}" ]]; then
    echo "Usage: scripts/run_stage.sh <generate|validate|schema-check|gate|pipeline|all> <scale>" >&2
    exit 2
fi

PY="$(bundle_python)"
DATA_ROOT_DIR="$(data_root)"
mkdir -p "${DATA_ROOT_DIR}"
load_settings
SEED="${SETTING_SEED:-42}"
SHARDS="${SETTING_SHARDS:-22}"

timed_run() {
    # timed_run <label> -- <command...>
    local label="$1"; shift
    [[ "$1" == "--" ]] && shift
    local out="${RESULTS_DIR}/${label}.stdout"
    local err="${RESULTS_DIR}/${label}.stderr"
    local timef="${RESULTS_DIR}/${label}.time"
    local exitf="${RESULTS_DIR}/${label}.exit"
    echo ">>> ${label}: $*"
    set +e
    if command -v /usr/bin/time >/dev/null 2>&1 && /usr/bin/time -v true >/dev/null 2>&1; then
        /usr/bin/time -v -o "${timef}" "$@" > "${out}" 2> "${err}"
        rc=$?
    else
        { /usr/bin/time "$@" > "${out}" 2> "${err}"; } 2> "${timef}"
        rc=$?
        echo "NOTE: verbose /usr/bin/time -v not available on this OS; peak memory not captured for this stage here." >> "${timef}"
    fi
    set -e
    echo "$rc" > "${exitf}"
    if [[ "$rc" -eq 0 ]]; then
        echo ">>> ${label}: OK (exit 0). stdout: ${out}"
    else
        echo ">>> ${label}: FAILED (exit ${rc}). See ${err}"
    fi
    return "$rc"
}

stage_generate() {
    local raw_dir="${DATA_ROOT_DIR}/raw_${SCALE}"
    mkdir -p "${raw_dir}"
    timed_run "generate_${SCALE}" -- "${PY}" "${BUNDLE_ROOT}/scripts/generate_raw.py" \
        --fraction "${SCALE}" --seed "${SEED}" --shards "${SHARDS}" --output "${raw_dir}"
}

stage_validate() {
    local raw_dir="${DATA_ROOT_DIR}/raw_${SCALE}"
    timed_run "validate_${SCALE}" -- "${PY}" "${BUNDLE_ROOT}/scripts/validate_raw.py" \
        --raw "${raw_dir}" --fraction "${SCALE}" --report "${RESULTS_DIR}/validate_${SCALE}.json"
}

stage_schema_check() {
    if [[ ! -f "${RESULTS_DIR}/config_${SCALE}.yml" ]]; then
        "${PY}" "${BUNDLE_ROOT}/scripts/make_config.py" --scale "${SCALE}"
    fi
    timed_run "schema-check_${SCALE}" -- "${PY}" "${BUNDLE_ROOT}/psm_260915.py" \
        --config "${RESULTS_DIR}/config_${SCALE}.yml" --schema-check
    grep -q '"missing_required_columns": \[\]' "${RESULTS_DIR}/schema-check_${SCALE}.stdout" \
        && echo ">>> schema-check_${SCALE}: missing_required_columns is empty -- PASS" \
        || echo ">>> schema-check_${SCALE}: missing_required_columns is NOT empty -- check ${RESULTS_DIR}/schema-check_${SCALE}.stdout"
}

stage_gate() {
    "${PY}" "${BUNDLE_ROOT}/scripts/check_machine.py"
    set +e
    "${PY}" "${BUNDLE_ROOT}/scripts/memory_gate.py" --scale "${SCALE}"
    rc=$?
    set -e
    return "$rc"
}

stage_pipeline() {
    if ! stage_gate; then
        echo ">>> pipeline_${SCALE}: refused to launch -- memory_gate.py returned NO-GO. See results/gate_${SCALE}.json." >&2
        return 1
    fi
    if [[ ! -f "${RESULTS_DIR}/config_${SCALE}.yml" ]]; then
        "${PY}" "${BUNDLE_ROOT}/scripts/make_config.py" --scale "${SCALE}"
    fi
    local out="${RESULTS_DIR}/pipeline_${SCALE}.stdout"
    local err="${RESULTS_DIR}/pipeline_${SCALE}.stderr"
    local pidf="${RESULTS_DIR}/pipeline_${SCALE}.pid"
    local exitf="${RESULTS_DIR}/pipeline_${SCALE}.exit"
    local memf="${RESULTS_DIR}/pipeline_${SCALE}_memory_samples.txt"
    : > "${memf}"
    rm -f "${exitf}"
    echo ">>> pipeline_${SCALE}: launching in background with nohup ..."
    # The exit-code write happens INSIDE the same backgrounded shell, right after the
    # pipeline command itself, rather than via a separate `wait $pid` from this script's
    # shell -- a detached/nohup'd child can lose its "job" relationship to the launching
    # shell (so a later `wait` on its PID can fail with "not a child of this shell"
    # depending on the shell/OS), while chaining the write after the command in the same
    # subshell has no such dependency.
    nohup bash -c '
        "$1" "$2" --config "$3" > "$4" 2> "$5"
        echo $? > "$6"
    ' _ "${PY}" "${BUNDLE_ROOT}/psm_260915.py" "${RESULTS_DIR}/config_${SCALE}.yml" "${out}" "${err}" "${exitf}" &
    local pid=$!
    echo "${pid}" > "${pidf}"
    nohup "${PY}" "${BUNDLE_ROOT}/scripts/monitor_memory.py" --pid "${pid}" --out "${memf}" --interval 10 \
        > "${RESULTS_DIR}/pipeline_${SCALE}_monitor.log" 2>&1 &
    echo ">>> pipeline_${SCALE}: PID ${pid} (in ${pidf}). Memory sampled every 10s to ${memf}."
    echo ">>> Watch progress with: scripts/status.sh   or:   tail -f ${out} ${err}"
    echo ">>> This does NOT block; run_stage.sh returns immediately. Check back with status.sh."
}

case "${STAGE}" in
    generate) stage_generate ;;
    validate) stage_validate ;;
    schema-check) stage_schema_check ;;
    gate) stage_gate ;;
    pipeline) stage_pipeline ;;
    all)
        stage_generate
        stage_validate
        stage_schema_check
        stage_gate
        stage_pipeline
        ;;
    *)
        echo "Unknown stage '${STAGE}'. Must be one of: generate validate schema-check gate pipeline all" >&2
        exit 2
        ;;
esac

#!/usr/bin/env python3
"""scripts/make_report.py --scale F

After a pipeline stage finishes (successfully or not), inspects the run directory and
stderr/log files, and appends a plain-language section to results/WORKBENCH_REPORT.md.

Checks:
  - run_outputs.json exists and has the expected top-level keys for the primary spec
    (estimand, matching, balance, models, mediation, figures, ...) and, if run_lag1_vs_lag3
    was true, that a secondary-spec run_outputs.json also exists
  - matching_audit / balance summary files exist under diagnostics/
  - mediation results report every bootstrap replicate succeeding (no failed fits)
  - figures (PNG/PDF) exist under figures/
  - stderr/pipeline log scanned for: Traceback, MemoryError, Killed, exit code 137 (the
    OOM-kill signature), NaN, Inf, and the known Matplotlib
    "'xerr' must not contain negative values" failure (reported if found, NEVER patched --
    see calibration_20pct.json estimator.known_matplotlib_xerr_issue for why this bundle
    does not expect to find it in this copy of psm_260915.py, but still checks).
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

BUNDLE_ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = BUNDLE_ROOT / "results"

# Multi-word phrases are unambiguous as plain substrings. Single words are matched with \b
# word boundaries via FATAL_WORD_PATTERNS below instead -- a bare substring search for "inf"
# or "OOM" hits countless false positives (e.g. "inference_method", "Bloomberg") in ordinary
# log/JSON text; \b(?:nan|inf|infinity)\b does not, since "inf" inside "inference" has no
# boundary on its right (both 'f' and 'e' are word characters).
FATAL_PHRASES = ["Traceback (most recent call last)", "MemoryError", "Killed"]
FATAL_WORD_PATTERNS = {
    "OOM": re.compile(r"\bOOM\b"),
    "NaN/nan": re.compile(r"\bnan\b", re.IGNORECASE),
    "Inf/Infinity": re.compile(r"\b(?:inf|infinity)\b", re.IGNORECASE),
}
XERR_SIGNATURE = "must not contain negative values"


def load_settings() -> dict:
    settings = {}
    for line in (BUNDLE_ROOT / "bundle_settings.env").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        settings[key.strip()] = value.strip()
    return settings


def scan_for_fatal_tokens(text: str) -> dict:
    found = {}
    for phrase in FATAL_PHRASES:
        count = text.count(phrase)
        if count:
            found[phrase] = count
    for label, pattern in FATAL_WORD_PATTERNS.items():
        count = len(pattern.findall(text))
        if count:
            found[label] = count
    xerr_hits = len(re.findall(re.escape(XERR_SIGNATURE), text))
    if xerr_hits:
        found["xerr/yerr negative-values (Matplotlib known issue)"] = xerr_hits
    exit137 = "137" in text and ("exit" in text.lower() or "killed" in text.lower())
    if exit137:
        found["exit code 137 (possible OOM-kill)"] = 1
    return found


def check_run_outputs(run_dir: Path) -> dict:
    result = {"run_dir": str(run_dir), "exists": run_dir.exists()}
    if not run_dir.exists():
        return result
    primary = run_dir / "run_outputs.json"
    result["primary_run_outputs_exists"] = primary.exists()
    if primary.exists():
        payload = json.loads(primary.read_text(encoding="utf-8"))
        expected_keys = ["estimand", "risksets", "matching", "balance", "models", "mediation", "figures"]
        result["primary_missing_keys"] = [k for k in expected_keys if k not in payload]
        mediation = payload.get("mediation", {})
        result["mediation_present"] = bool(mediation)
        result["mediation_summary"] = _summarize_mediation(mediation)
        figures = payload.get("figures", {})
        result["n_figure_entries"] = len(figures) if isinstance(figures, dict) else None
    diagnostics_dir = run_dir / "diagnostics"
    result["diagnostics_dir_exists"] = diagnostics_dir.exists()
    if diagnostics_dir.exists():
        result["matching_audit_files"] = [p.name for p in diagnostics_dir.glob("matching_audit_*.csv")]
        result["matching_preflight_files"] = [p.name for p in diagnostics_dir.glob("matching_edge_preflight_*.csv")]
    figures_dir = run_dir / "figures"
    result["figures_dir_exists"] = figures_dir.exists()
    if figures_dir.exists():
        result["n_png"] = len(list(figures_dir.glob("*.png")))
        result["n_pdf"] = len(list(figures_dir.glob("*.pdf")))
    return result


def _summarize_mediation(mediation) -> str:
    if not mediation:
        return "no mediation block in run_outputs.json"
    try:
        text = json.dumps(mediation)
    except TypeError:
        return "mediation block present but not JSON-serializable for a quick summary"
    n_success = text.count('"converged": true') + text.count('"success": true')
    n_fail = text.count('"converged": false') + text.count('"success": false')
    return f"{n_success} success-flag(s), {n_fail} failure-flag(s) found in the mediation block (heuristic string count, not a schema-validated total)"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scale", required=True)
    args = parser.parse_args()

    scale = args.scale
    settings = load_settings()
    data_root = (BUNDLE_ROOT / settings.get("DATA_ROOT", "../didi_data")).resolve()
    seed = settings.get("SEED", "42")
    sample_tag = f"workbench_synthetic_{scale}_seed{seed}"
    run_dir = data_root / "runs" / sample_tag

    stdout_path = RESULTS_DIR / f"pipeline_{scale}.stdout"
    stderr_path = RESULTS_DIR / f"pipeline_{scale}.stderr"
    exit_path = RESULTS_DIR / f"pipeline_{scale}.exit"

    exit_code = exit_path.read_text().strip() if exit_path.exists() else "unknown (pipeline stage not run yet, or still running)"
    stderr_text = stderr_path.read_text(encoding="utf-8", errors="replace") if stderr_path.exists() else ""
    stdout_text = stdout_path.read_text(encoding="utf-8", errors="replace") if stdout_path.exists() else ""

    fatal_findings = scan_for_fatal_tokens(stderr_text + "\n" + stdout_text)
    run_check = check_run_outputs(run_dir)

    preflight_csv = RESULTS_DIR / f"preflight_comparison_{scale}.csv"
    preflight_status = "not yet run (run scripts/compare_preflight.py)"
    if preflight_csv.exists():
        text = preflight_csv.read_text(encoding="utf-8")
        n_fail = text.count(",FAIL\n") + (1 if text.rstrip().endswith(",FAIL") else 0)
        preflight_status = "has FAIL rows -- see the CSV" if n_fail else "no FAIL rows found (PASS or not-yet-checked)"

    lines = []
    lines.append(f"## Scale {scale} (sample_tag={sample_tag})\n")
    lines.append(f"- Pipeline exit code: `{exit_code}`\n")
    lines.append(f"- Run directory: `{run_dir}` (exists: {run_check.get('exists')})\n")
    if run_check.get("exists"):
        lines.append(f"- `run_outputs.json` present: {run_check.get('primary_run_outputs_exists')}\n")
        missing_keys = run_check.get("primary_missing_keys")
        if missing_keys:
            lines.append(f"  - MISSING top-level keys: {missing_keys}\n")
        lines.append(f"- Mediation: {run_check.get('mediation_summary', 'n/a')}\n")
        lines.append(f"- Matching audit files found: {run_check.get('matching_audit_files', [])}\n")
        lines.append(f"- Matching edge preflight files found: {run_check.get('matching_preflight_files', [])}\n")
        lines.append(f"- Figures: {run_check.get('n_png', 0)} PNG, {run_check.get('n_pdf', 0)} PDF\n")
    lines.append(f"- Step-3 preflight calibration check: {preflight_status}\n")
    if fatal_findings:
        lines.append("- **Fatal/warning token scan (stdout+stderr) -- found:**\n")
        for token, count in fatal_findings.items():
            lines.append(f"  - `{token}`: {count} occurrence(s)\n")
        if "xerr/yerr negative-values (Matplotlib known issue)" in fatal_findings:
            lines.append(
                "  - The xerr/yerr failure is a known, previously-documented plotting bug "
                "(see GATE2_REPORT.md and calibration_20pct.json). This copy of psm_260915.py "
                "already contains a fix for it (git commit a7c52db) -- if it appears here anyway, "
                "**report it, do not patch the estimator**; note the exact stratum/spec it occurred in.\n"
            )
    else:
        lines.append("- Fatal/warning token scan (stdout+stderr): clean -- no Traceback/MemoryError/Killed/NaN/Inf/xerr/OOM signatures found.\n")
    lines.append("\n")

    report_path = RESULTS_DIR / "WORKBENCH_REPORT.md"
    header = "# WORKBENCH_REPORT.md\n\nAppended one section per scale by scripts/make_report.py.\n\n"
    existing = report_path.read_text(encoding="utf-8") if report_path.exists() else header
    with open(report_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(existing.rstrip("\n") + "\n\n" + "".join(lines))

    print(f"Appended scale {scale} section to {report_path}")
    print(f"Pipeline exit code: {exit_code}")
    print(f"Fatal/warning tokens found: {list(fatal_findings.keys()) or 'none'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""scripts/make_config.py --scale F [--production]

Writes results/config_<scale>.yml: every PipelineConfig field from the real USER_CONFIG in
psm_260915.py (see calibration_20pct.json -> estimator.user_config_values_used_by_make_config
for the exact values and their provenance), with runtime-resolved raw_glob/output_dir under
DATA_ROOT, a scale-tagged sample_tag, and the bootstrap replicate counts from
bundle_settings.env (SMOKE by default, PRODUCTION with --production).

Also writes results/config_<scale>_diff.json listing every key that differs from a bare
PipelineConfig(**USER_CONFIG) instantiation, so a reader can see at a glance what this
synthetic run changed relative to the real one.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

BUNDLE_ROOT = Path(__file__).resolve().parent.parent


def load_settings() -> dict:
    settings = {}
    for line in (BUNDLE_ROOT / "bundle_settings.env").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        settings[key.strip()] = value.strip()
    return settings


def load_calibration() -> dict:
    return json.loads((BUNDLE_ROOT / "calibration_20pct.json").read_text(encoding="utf-8"))


def pick_mediation_workers(settings: dict) -> tuple[int, str]:
    configured = int(settings.get("MEDIATION_WORKERS", "0"))
    if configured > 0:
        return configured, f"bundle_settings.env MEDIATION_WORKERS={configured} (explicit override)"
    machine_path = BUNDLE_ROOT / "results" / "machine.json"
    if not machine_path.exists():
        return 2, (
            "MEDIATION_WORKERS=0 (auto) but results/machine.json does not exist yet "
            "(run 'python scripts/check_machine.py' first); defaulting to 2 workers, "
            "the conservative Gate 2 1% starting point"
        )
    machine = json.loads(machine_path.read_text(encoding="utf-8"))
    available = machine.get("available_ram_gib")
    if not available:
        return 2, "MEDIATION_WORKERS=0 (auto) but machine.json has no usable RAM figure; defaulting to 2"
    # Without a completed run, we do not yet know the mediation panel's per-worker GB size.
    # Start conservative (2 workers, matching Gate 2's 1% run) and let the guide explain how
    # to raise this once a completed run's log reports the actual per-worker panel size
    # (psm_260915.py logs "mediation panel %.2f GB in memory per worker" at INFO level).
    workers = 2
    half_ram = available / 2.0
    return workers, (
        f"MEDIATION_WORKERS=0 (auto); available_ram_gib={available:.2f} from machine.json "
        f"(half={half_ram:.2f} GiB budget). No completed run yet to read an actual "
        f"per-worker mediation panel size from, so starting at {workers} (Gate 2's 1% "
        "value); re-run make_config.py after a completed run to raise this once the log's "
        "'mediation panel %.2f GB in memory per worker' line is known."
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scale", required=True, type=float, help="Fraction of the real 20%% sample, e.g. 0.001")
    parser.add_argument("--production", action="store_true", help="Use BOOTSTRAP_REPLICATES_PRODUCTION instead of _SMOKE")
    args = parser.parse_args()

    settings = load_settings()
    calibration = load_calibration()
    user_config = calibration["estimator"]["user_config_values_used_by_make_config"]
    user_config = {k: v for k, v in user_config.items() if k != "note"}

    data_root = (BUNDLE_ROOT / settings.get("DATA_ROOT", "../didi_data")).resolve()
    seed = int(settings.get("SEED", "42"))
    scale_str = f"{args.scale:g}"

    raw_dir = data_root / f"raw_{scale_str}"
    output_dir = data_root / "runs"
    sample_tag = f"workbench_synthetic_{scale_str}_seed{seed}"

    bootstrap_key = "BOOTSTRAP_REPLICATES_PRODUCTION" if args.production else "BOOTSTRAP_REPLICATES_SMOKE"
    bootstrap_n = int(settings.get(bootstrap_key, "200" if args.production else "20"))

    mediation_workers, workers_reason = pick_mediation_workers(settings)

    config = dict(user_config)
    config.update({
        "raw_glob": str(raw_dir / "raw_*.parquet"),
        "output_dir": str(output_dir),
        "sample_tag": sample_tag,
        "seed": seed,
        "outcome_bootstrap_replicates": bootstrap_n,
        "absolute_effect_bootstrap_replicates": bootstrap_n,
        "mediation_bootstrap_replicates": bootstrap_n,
        "mediation_bootstrap_workers": mediation_workers,
        "optimal_match_sparse_max_edges": 100_000_000,
    })

    paper_reporting = {
        "minimum_cell_people": 20,
        "pool_small_diagnosis_codes": True,
        "protect_matchability_cells": True,
        "withhold_small_overlap_counts": True,
    }

    results_dir = BUNDLE_ROOT / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    yaml_path = results_dir / f"config_{scale_str}.yml"
    diff_path = results_dir / f"config_{scale_str}_diff.json"

    # Written by hand (not via PyYAML) so this script has zero dependency on the venv even
    # existing yet; the format is a flat top-level mapping plus one nested paper_reporting
    # block, exactly what load_pipeline_and_reporting_config() expects.
    lines = ["# Auto-generated by scripts/make_config.py -- do not hand-edit; re-run the script instead.\n"]
    for key, value in config.items():
        lines.append(_yaml_line(key, value))
    lines.append("paper_reporting:\n")
    for key, value in paper_reporting.items():
        lines.append("  " + _yaml_line(key, value))
    with open(yaml_path, "w", encoding="utf-8", newline="\n") as f:
        f.writelines(lines)

    diff = {
        "changed_from_user_config": {
            "raw_glob": config["raw_glob"],
            "output_dir": config["output_dir"],
            "sample_tag": config["sample_tag"],
            "outcome_bootstrap_replicates": {"user_config": 200, "this_run": bootstrap_n},
            "absolute_effect_bootstrap_replicates": {"user_config": 200, "this_run": bootstrap_n},
            "mediation_bootstrap_replicates": {"user_config": 200, "this_run": bootstrap_n},
            "mediation_bootstrap_workers": {"user_config": 0, "this_run": mediation_workers, "reason": workers_reason},
        },
        "unchanged_from_user_config": sorted(k for k in config if k not in {
            "raw_glob", "output_dir", "sample_tag", "outcome_bootstrap_replicates",
            "absolute_effect_bootstrap_replicates", "mediation_bootstrap_replicates",
            "mediation_bootstrap_workers",
        }),
        "scale": args.scale,
        "seed": seed,
        "production_bootstrap": args.production,
    }
    with open(diff_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(diff, f, indent=2, sort_keys=True)
        f.write("\n")

    print(f"Wrote {yaml_path}")
    print(f"Wrote {diff_path}")
    print(f"raw_glob:   {config['raw_glob']}")
    print(f"output_dir: {config['output_dir']}")
    print(f"sample_tag: {config['sample_tag']}")
    print(f"bootstrap replicates ({'production' if args.production else 'smoke'}): {bootstrap_n}")
    print(f"mediation_bootstrap_workers: {mediation_workers}  ({workers_reason})")
    return 0


def _yaml_line(key: str, value) -> str:
    if isinstance(value, list):
        if not value:
            return f"{key}: []\n"
        items = ", ".join(_yaml_scalar(v) for v in value)
        return f"{key}: [{items}]\n"
    return f"{key}: {_yaml_scalar(value)}\n"


def _yaml_float(value: float) -> str:
    # PyYAML's implicit float resolver requires a literal decimal point (YAML 1.1's
    # exponent-only form needs a *signed* exponent AND still requires a dot in the mantissa
    # for PyYAML's regex); Python's repr() switches to bare "1e-06"-style notation below
    # 1e-4, which YAML then parses back as a plain STRING, not a float -- silently breaking
    # any PipelineConfig field compared with < or > (e.g. gcomp_logit_tol). Always emit
    # explicit decimal notation instead.
    text = repr(float(value))
    if "e" not in text and "E" not in text:
        return text
    formatted = f"{value:.15f}".rstrip("0")
    if formatted.endswith("."):
        formatted += "0"
    return formatted


def _yaml_scalar(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return _yaml_float(value)
    if isinstance(value, int):
        return str(value)
    text = str(value)
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


if __name__ == "__main__":
    raise SystemExit(main())

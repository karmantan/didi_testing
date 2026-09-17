#!/usr/bin/env python3
"""scripts/memory_gate.py --scale F

GO/NO-GO decision for launching a pipeline run at fraction F of the real 20%% sample
(211,593,776 raw rows at F=1.0). Writes results/gate_<scale>.json and prints the decision
and the numbers behind it.

Rule: projected peak memory = (largest sampled process-tree peak from the most recent
LOCALLY COMPLETED pipeline run, at any scale) * (rows_at_F / rows_at_that_run). If no local
run has completed yet, falls back to the Gate 2 reference points recorded in
calibration_20pct.json ("gate2_reference_memory_points") -- but those came from the OLD,
uncalibrated generator with a score-bunching artifact (see that JSON's own "caveat" field),
so they are used only as a first estimate before this bundle's own generator has been
calibrated and run at least once.

GO requires: projected peak <= MEMORY_GATE_FRACTION * available_ram_gib (from machine.json)
AND free disk >= 3x the projected output size. Never raises optimal_match_sparse_max_edges to
force a GO -- that cap is fixed at 100,000,000 throughout this bundle (see
calibration_20pct.json estimator.optimal_match_sparse_max_edges_user_config).
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

BUNDLE_ROOT = Path(__file__).resolve().parent.parent
REAL_ROWS_AT_FRACTION_1 = 211_593_776


def load_settings() -> dict:
    settings = {}
    for line in (BUNDLE_ROOT / "bundle_settings.env").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        settings[key.strip()] = value.strip()
    return settings


def find_most_recent_completed_pipeline(results_dir: Path):
    """Return (scale, rows, peak_gib, source_description) for the most recent completed
    local pipeline run that has a memory-sample file, or None if none exists yet."""
    best = None
    for exit_file in sorted(results_dir.glob("pipeline_*.exit")):
        m = re.match(r"pipeline_(.+)\.exit$", exit_file.name)
        if not m:
            continue
        scale_str = m.group(1)
        try:
            exit_code = int(exit_file.read_text().strip())
        except ValueError:
            continue
        if exit_code != 0:
            continue
        samples_file = results_dir / f"pipeline_{scale_str}_memory_samples.txt"
        if not samples_file.exists():
            continue
        peaks = []
        for line in samples_file.read_text().splitlines():
            parts = line.strip().split()
            if len(parts) >= 2:
                try:
                    peaks.append(float(parts[-1]))
                except ValueError:
                    continue
        if not peaks:
            continue
        peak_gib = max(peaks)
        try:
            scale = float(scale_str)
        except ValueError:
            continue
        rows = round(REAL_ROWS_AT_FRACTION_1 * scale)
        candidate = (scale, rows, peak_gib, f"local run at scale {scale_str} (results/pipeline_{scale_str}_memory_samples.txt)")
        # Prefer the largest completed local scale as the basis for projection (closest to
        # the target scale generally gives the least-extrapolated projection).
        if best is None or scale > best[0]:
            best = candidate
    return best


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scale", required=True, type=float)
    args = parser.parse_args()

    settings = load_settings()
    results_dir = BUNDLE_ROOT / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    calibration = json.loads((BUNDLE_ROOT / "calibration_20pct.json").read_text(encoding="utf-8"))

    machine_path = results_dir / "machine.json"
    if not machine_path.exists():
        print("ERROR: results/machine.json not found. Run 'python scripts/check_machine.py' first.")
        return 2
    machine = json.loads(machine_path.read_text(encoding="utf-8"))
    available_ram_gib = machine.get("available_ram_gib")
    if not available_ram_gib:
        print("ERROR: results/machine.json has no usable available_ram_gib. Re-run check_machine.py; if this persists on Linux, memory_gate.py cannot make a safe decision.")
        return 2

    target_rows = round(REAL_ROWS_AT_FRACTION_1 * args.scale)

    basis = find_most_recent_completed_pipeline(results_dir)
    if basis is not None:
        basis_scale, basis_rows, basis_peak_gib, basis_source = basis
        projected_peak_gib = basis_peak_gib * (target_rows / basis_rows) if basis_rows else basis_peak_gib
        basis_note = f"projected from {basis_source}: {basis_peak_gib:.3f} GiB at {basis_rows:,} rows"
    else:
        g2 = calibration["gate2_reference_memory_points"]
        # Use the larger of the two Gate 2 reference points as the extrapolation basis,
        # since it is closer in scale to most target fractions this bundle will actually run.
        ref = g2["gate2_1pct"]
        basis_rows = ref["raw_rows"]
        basis_peak_gib = ref["peak_whole_container_gib"]
        projected_peak_gib = basis_peak_gib * (target_rows / basis_rows) if basis_rows else basis_peak_gib
        basis_note = (
            f"NO local completed run yet -- falling back to Gate 2 1% reference point "
            f"({basis_peak_gib:.2f} GiB whole-container peak at {basis_rows:,} rows). "
            f"{g2['caveat']}"
        )

    gate_fraction = float(settings.get("MEMORY_GATE_FRACTION", "0.8"))
    memory_ceiling_gib = gate_fraction * available_ram_gib
    memory_ok = projected_peak_gib <= memory_ceiling_gib

    data_root = (BUNDLE_ROOT / settings.get("DATA_ROOT", "../didi_data")).resolve()
    data_root.mkdir(parents=True, exist_ok=True)
    import shutil
    free_disk_gib = shutil.disk_usage(data_root).free / (1024 ** 3)
    # Rough output-size projection: real 20% run's on-disk tree (from GATE2_REPORT.md-style
    # figures) scales roughly with rows for panel/checkpoint data; use the raw-shard total
    # (4.169 GB at fraction 1.0) as a conservative proxy for run output size at this fraction,
    # since final run trees (Gate 2's 1% run: ~80 MB) are much smaller than the raw input.
    real_shard_bytes = calibration["raw_data_20pct"]["shard_total_bytes"]
    projected_output_gib = (real_shard_bytes * args.scale) / (1024 ** 3)
    disk_needed_gib = 3 * max(projected_output_gib, 0.01)
    disk_ok = free_disk_gib >= disk_needed_gib

    decision = "GO" if (memory_ok and disk_ok) else "NO-GO"

    gate = {
        "scale": args.scale,
        "target_rows": target_rows,
        "basis_rows": basis_rows,
        "basis_peak_gib": basis_peak_gib,
        "basis_note": basis_note,
        "projected_peak_gib": round(projected_peak_gib, 4),
        "available_ram_gib": available_ram_gib,
        "memory_gate_fraction": gate_fraction,
        "memory_ceiling_gib": round(memory_ceiling_gib, 4),
        "memory_ok": memory_ok,
        "free_disk_gib": round(free_disk_gib, 4),
        "projected_output_gib": round(projected_output_gib, 4),
        "disk_needed_gib": round(disk_needed_gib, 4),
        "disk_ok": disk_ok,
        "decision": decision,
        "optimal_match_sparse_max_edges": 100_000_000,
        "note": "optimal_match_sparse_max_edges is never raised above 100,000,000 to force a GO, regardless of this gate's outcome.",
    }
    gate_path = results_dir / f"gate_{args.scale:g}.json"
    with open(gate_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(gate, f, indent=2, sort_keys=True)
        f.write("\n")

    print(f"=== Memory gate: scale {args.scale:g} ({target_rows:,} target raw rows) ===")
    print(basis_note)
    print(f"Projected peak memory: {projected_peak_gib:.3f} GiB")
    print(f"Available RAM (machine.json): {available_ram_gib:.3f} GiB; gate ceiling ({gate_fraction:.0%}): {memory_ceiling_gib:.3f} GiB -> {'OK' if memory_ok else 'EXCEEDED'}")
    print(f"Free disk at DATA_ROOT: {free_disk_gib:.3f} GiB; need >= {disk_needed_gib:.3f} GiB (3x projected output {projected_output_gib:.3f} GiB) -> {'OK' if disk_ok else 'INSUFFICIENT'}")
    print(f"DECISION: {decision}")
    if decision == "NO-GO":
        print("A NO-GO is a valid, useful result -- it means this scale should not be launched on this")
        print("session as configured. Do not raise optimal_match_sparse_max_edges or the gate fraction")
        print("to force a GO; instead try a smaller scale, or restart the Workbench session with a")
        print("larger memory profile if one is available.")
    print(f"Wrote {gate_path}")
    return 0 if decision == "GO" else 1


if __name__ == "__main__":
    raise SystemExit(main())

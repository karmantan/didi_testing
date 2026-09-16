#!/usr/bin/env python3
"""scripts/compare_preflight.py --run RUN_DIR

Mandatory Step-3 calibration check (see BUILD_LOG.md and calibration_20pct.json
"matching_edge_preflight"): compares a synthetic pipeline run's OWN
matching_edge_preflight_not_yet_divorced_lag1.csv (written by psm_260915.py itself into
<run_dir>/diagnostics/ during matching) against the real one bundled at
export_20260911/20pct/260909/matching_edge_preflight_not_yet_divorced_lag1.csv.

For the 20 real strata with the largest candidate_real_edges (listed in
calibration_20pct.json matching_edge_preflight.top_20_strata_by_candidate_real_edges), finds
the matching synthetic stratum by (t0, lag1_age_band, lag1_ever_rehab_to_date, lag1_ge_cat)
and checks:
  1. synthetic admissible_share is within 15 percentage points of the real admissible_share
  2. the synthetic treated and control propensity-score ranges overlap the real ranges

PASSES only if every one of the 20 strata that has a synthetic counterpart passes both
checks (a stratum absent from the synthetic run at very small scales -- e.g. 0.1%, where a
252-treated stratum may simply not exist -- is reported as "not present at this scale", not
a failure, but at least half of the 20 strata must be present for the comparison to be
meaningful).

Writes results/preflight_comparison_<scale>.csv (one row per matched stratum) and prints a
plain-language PASS/FAIL verdict. Do not ship a generator that fails this check.
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

BUNDLE_ROOT = Path(__file__).resolve().parent.parent
REAL_PREFLIGHT_CSV = BUNDLE_ROOT / "export_20260911" / "20pct" / "260909" / "matching_edge_preflight_not_yet_divorced_lag1.csv"
ADMISSIBLE_SHARE_TOLERANCE_PP = 15.0


def load_calibration() -> dict:
    return json.loads((BUNDLE_ROOT / "calibration_20pct.json").read_text(encoding="utf-8"))


def load_synthetic_preflight(run_dir: Path) -> list[dict]:
    candidates = list(run_dir.glob("diagnostics/matching_edge_preflight_not_yet_divorced_lag1.csv"))
    if not candidates:
        candidates = list(run_dir.glob("**/matching_edge_preflight_not_yet_divorced_lag1.csv"))
    if not candidates:
        return []
    with open(candidates[0], newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    out = []
    for r in rows:
        stratum = json.loads(r["exact_stratum"])
        nt = int(r["n_treated_in_stratum"])
        nc = int(r["n_controls_in_stratum"])
        out.append({
            "t0": int(r["t0"]),
            "lag1_age_band": stratum.get("lag1_age_band"),
            "lag1_ever_rehab_to_date": str(stratum.get("lag1_ever_rehab_to_date")),
            "lag1_ge_cat": str(stratum.get("lag1_ge_cat")),
            "n_treated_in_stratum": nt,
            "n_controls_in_stratum": nc,
            "candidate_real_edges": int(r["candidate_real_edges"]),
            "admissible_share": (int(r["candidate_real_edges"]) / (nt * nc)) if nt * nc else 0.0,
            "treated_pscore_min": float(r["treated_pscore_min"]),
            "treated_pscore_max": float(r["treated_pscore_max"]),
            "control_pscore_min": float(r["control_pscore_min"]),
            "control_pscore_max": float(r["control_pscore_max"]),
        })
    return out


def ranges_overlap(a_min: float, a_max: float, b_min: float, b_max: float) -> bool:
    return a_min <= b_max and b_min <= a_max


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", required=True, help="Path to the pipeline run directory (config.output_dir / config.sample_tag)")
    parser.add_argument("--scale", default=None, help="Scale label for the output filename; inferred from --run if omitted")
    args = parser.parse_args()

    run_dir = Path(args.run)
    scale_label = args.scale or run_dir.name

    calibration = load_calibration()
    real_top20 = calibration["matching_edge_preflight"]["top_20_strata_by_candidate_real_edges"]

    synthetic_rows = load_synthetic_preflight(run_dir)
    synthetic_by_key = {
        (r["t0"], r["lag1_age_band"], r["lag1_ever_rehab_to_date"], r["lag1_ge_cat"]): r
        for r in synthetic_rows
    }

    if not synthetic_rows:
        print(f"FAIL: no matching_edge_preflight_not_yet_divorced_lag1.csv found under {run_dir}.")
        print("This file is written by psm_260915.py itself during matching -- if the pipeline run")
        print("did not reach the matching stage (e.g. it crashed earlier), there is nothing to compare yet.")
        return 1

    comparison_rows = []
    n_present = 0
    n_pass = 0
    for real in real_top20:
        key = (real["t0"], real["lag1_age_band"], real["lag1_ever_rehab_to_date"], real["lag1_ge_cat"])
        synth = synthetic_by_key.get(key)
        if synth is None:
            comparison_rows.append({
                "t0": real["t0"], "lag1_age_band": real["lag1_age_band"],
                "lag1_ever_rehab_to_date": real["lag1_ever_rehab_to_date"], "lag1_ge_cat": real["lag1_ge_cat"],
                "real_admissible_share": real["admissible_share"], "synthetic_admissible_share": "",
                "share_diff_pp": "", "score_ranges_overlap": "", "status": "NOT_PRESENT_AT_THIS_SCALE",
            })
            continue
        n_present += 1
        share_diff_pp = abs(synth["admissible_share"] - real["admissible_share"]) * 100.0
        overlap = ranges_overlap(
            synth["treated_pscore_min"], synth["treated_pscore_max"],
            real["treated_pscore_min"], real["treated_pscore_max"],
        ) and ranges_overlap(
            synth["control_pscore_min"], synth["control_pscore_max"],
            real["control_pscore_min"], real["control_pscore_max"],
        )
        passed = share_diff_pp <= ADMISSIBLE_SHARE_TOLERANCE_PP and overlap
        if passed:
            n_pass += 1
        comparison_rows.append({
            "t0": real["t0"], "lag1_age_band": real["lag1_age_band"],
            "lag1_ever_rehab_to_date": real["lag1_ever_rehab_to_date"], "lag1_ge_cat": real["lag1_ge_cat"],
            "real_admissible_share": round(real["admissible_share"], 6),
            "synthetic_admissible_share": round(synth["admissible_share"], 6),
            "share_diff_pp": round(share_diff_pp, 3),
            "score_ranges_overlap": overlap,
            "status": "PASS" if passed else "FAIL",
        })

    results_dir = BUNDLE_ROOT / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    out_csv = results_dir / f"preflight_comparison_{scale_label}.csv"
    with open(out_csv, "w", newline="\n", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(comparison_rows[0].keys()))
        writer.writeheader()
        writer.writerows(comparison_rows)

    print(f"=== compare_preflight.py: {run_dir} ===")
    print(f"{n_present} of the 20 largest real strata are present in this synthetic run's own preflight CSV.")
    if n_present == 0:
        print("FAIL: none of the 20 largest real strata exist in this synthetic run at all -- cannot calibrate.")
        print(f"Wrote {out_csv}")
        return 1
    if n_present < 10:
        print(f"WARNING: only {n_present}/20 strata present -- this is likely too small a scale for a meaningful comparison (try a larger --fraction).")
    for row in comparison_rows:
        if row["status"] == "NOT_PRESENT_AT_THIS_SCALE":
            continue
        print(
            f"  t0={row['t0']} age={row['lag1_age_band']:>6} rehab={row['lag1_ever_rehab_to_date']} sex={row['lag1_ge_cat']}: "
            f"real={row['real_admissible_share']*100:.1f}%  synthetic={row['synthetic_admissible_share']*100:.1f}%  "
            f"diff={row['share_diff_pp']:.1f}pp  overlap={row['score_ranges_overlap']}  -> {row['status']}"
        )

    overall_pass = n_present > 0 and n_pass == n_present
    print()
    if overall_pass:
        print(f"PASS: all {n_present} present strata are within {ADMISSIBLE_SHARE_TOLERANCE_PP:.0f}pp of the real admissible share with overlapping score ranges.")
    else:
        print(f"FAIL: {n_present - n_pass} of {n_present} present strata failed the {ADMISSIBLE_SHARE_TOLERANCE_PP:.0f}pp tolerance and/or score-overlap check.")
        print("Do not proceed to larger scales or ship this generator until this passes -- see calibration_20pct.json")
        print("'matching_edge_preflight.admissible_share_pattern' for what the generator's latent divorce-propensity")
        print("function needs to reproduce, and BUILD_LOG.md for this bundle's own calibration iteration history.")
    print(f"Wrote {out_csv}")
    return 0 if overall_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())

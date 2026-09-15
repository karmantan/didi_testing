#!/usr/bin/env python3
"""Isolated lag-3 scale-test harness; set LAG3_TEST_PANEL/OUT for smoke runs."""

import json
import os
import resource
import sys
import time
import traceback
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import psm_260915 as psm

ROOT = Path(__file__).resolve().parent
PANEL = Path(os.environ.get("LAG3_TEST_PANEL", ROOT / "lag3_scale_test_panel" / "analysis_panel.parquet")).resolve()
OUT = Path(os.environ.get("LAG3_TEST_OUT", ROOT / "lag3_scale_test_out")).resolve()
SMOKE = os.environ.get("LAG3_TEST_SMOKE") == "1"

base = psm.PipelineConfig(**{
    **psm.USER_CONFIG,
    "raw_glob": str(PANEL),
    "output_dir": str(OUT),
    "sample_tag": "synthetic_20pct_smoke" if SMOKE else "synthetic_20pct",
})
cfg = replace(
    base,
    sample_tag=f"{base.sample_tag}__lag3_common_2014_2018",
    year_start=2014,
    year_cap=2018,
    lag_depth=3,
    lag_comparison_common_year_start=2014,
    run_lag1_vs_lag3=False,
    run_longitudinal_mediation=False,
    run_msk_dropout_sensitivity=False,
    generate_figures=False,
    outcome_bootstrap_replicates=20,
    absolute_effect_bootstrap_replicates=20,
    optimal_match_sparse_max_edges=500_000_000,
    strict_main_run=False,
    protect_matching=False,
    # Logging is configured before the secondary entry point. Its default
    # total_rebuild=True would unlink the active logs/pipeline.log handler.
    total_rebuild=False,
)
cfg.validate()
psm._configure_logging(cfg)
reporting = psm.PaperReportingConfig(**psm.PAPER_REPORTING_CONFIG)

stage_seconds = {}
for name in (
    "relabel_panel_rehab_codes", "build_risk_sets", "fit_and_match",
    "audit_matched_sample_rehab_definition", "build_balance_tables",
    "build_marital_status_tables", "build_paper_summary_tables",
    "build_pair_event_study_panel", "build_msk_followup", "build_mortality_followup",
):
    original = getattr(psm, name)

    def timed(*args, _name=name, _original=original, **kwargs):
        start = time.perf_counter()
        try:
            return _original(*args, **kwargs)
        finally:
            elapsed = round(time.perf_counter() - start, 3)
            stage_seconds.setdefault(_name, []).append(elapsed)
            psm.log.info("[harness timing] %s %.3f s", _name, elapsed)

    setattr(psm, name, timed)

start = time.time()
result = None
status = "completed"
error_traceback = None
try:
    result = psm._run_secondary_specification_from_panel(cfg, PANEL, force=True, reporting=reporting)
except Exception as exc:
    status = f"crashed: {exc!r}"
    error_traceback = traceback.format_exc()
    traceback.print_exc()
finally:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / ("lag3_smoke_status.json" if SMOKE else "lag3_harness_status.json")).write_text(
        json.dumps({
            "status": status,
            "wall_seconds": round(time.time() - start, 1),
            "panel": str(PANEL),
            "config": cfg.to_dict(),
            "stage_seconds": stage_seconds,
            "peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            "traceback": error_traceback,
            "run_outputs_written": result is not None,
        }, indent=2), encoding="utf-8",
    )
print(status, round(time.time() - start, 1), "s", flush=True)
if error_traceback:
    sys.exit(1)

# Lag-3 scale test, 15 September 2026

## Result and scope

The lag-3 smoke run completed risk-set generation, propensity scoring and matching for 2014–2018, balance tables, and the downstream work called by `_run_secondary_specification_from_panel`. **The full-scale question remains unanswered.** This machine is an Apple M2 MacBook Pro with **24 GB RAM**, below the task's explicit 64 GB minimum. No 148.5M-row or ~200M-row lag-3 process was started. Consequently, there are no full-scale stage times, peak RSS, candidate-edge counts, or production-cap verdict. This is a hardware precondition, not a pipeline crash; there is no traceback.

## Panel and setup

Path **A** supplied the panel: `/Users/tankarman/psm_scale_test_260914/pipeline_runs/scale_test_200m/panels/analysis_panel.parquet`. It was copied to `lag3_scale_test_panel/analysis_panel.parquet`, with its rehab-code marker copied alongside it. Parquet metadata and Polars scans give **148,481,454 rows**, **13,498,314 unique people**, and **2011–2021** coverage. There are exactly **13,498,314 rows in each year**. The schema contains every lag-3 risk-set column and every required per-slot relabel column. The marker's applied codes match the config (MSK `[20,53,56]`, mental health `[30]`), so relabel would be **skipped** on the copied full panel. Its original lag-1 run had relabelled the panel in 202.1 seconds.

The smoke panel is a 0.5% person-hash slice, sorted by `(simple_id, ja)`, at `lag3_smoke_panel/analysis_panel.parquet`: **741,774 rows**, **67,434 people**, 2011–2021. It had no copied marker, so the smoke run **ran relabel** in 7.095 seconds; MSK starts remained 2,956 and mental-health starts remained 4,915. `python3 psm_260915.py --self-test` passed before this run.

This Path A panel is smaller than the requested ~200M rows and has no staggered entry: every person has all three preceding years. The lag-3-specific eligibility filter therefore measures zero attrition here. Its age-band and annual-count distributions also differ from the real 20% panel. The smoke edge counts must not be extrapolated to full scale.

## Measured smoke timings and memory

The harness status is `lag3_scale_test_out/lag3_smoke_status.json`; the timestamped log is `lag3_scale_test_out/synthetic_20pct_smoke__lag3_common_2014_2018/logs/pipeline.log`. Total secondary-run wall time was **373.3 s**. Peak RSS from macOS `resource.getrusage(RUSAGE_SELF).ru_maxrss` was **1,523,187,712 bytes (1.419 GiB)**. Linux `/usr/bin/time -v` was unavailable on this Mac; `/usr/bin/time -l` also failed on a sandboxed `sysctl` call.

| Stage | Smoke wall time |
|---|---:|
| Relabel | 7.095 s |
| `build_risk_sets` | 27.997 s; one partition, 27.85 s from build log to partition log |
| `fit_and_match` | 312.994 s |
| Matched-sample rehab audit | 0.262 s |
| `build_balance_tables` | 3.488 s |
| Marital-status tables | 1.671 s |
| Paper-summary tables | 1.466 s |
| Pair event-study panel | 0.087 s |
| MSK follow-up | 0.856 s |
| Mortality follow-up | 0.791 s |
| Other downstream work and entry-point overhead | 16.593 s (total minus instrumented stages) |

From `pipeline.log`, yearly fit / scoring / matching intervals, measured between the respective fit-start, convergence, scored, and checkpoint messages, were approximately: 2014 **63.4 / 1.2 / 2.8 s**; 2015 **66.9 / 1.0 / 1.5 s**; 2016 **51.9 / 1.1 / 1.1 s**; 2017 **69.1 / 1.1 / 2.5 s**; 2018 **42.0 / 1.3 / 2.3 s**. File partitioning, writing merged outputs, and matcher setup account for the rest of `fit_and_match`.

## Lag-3 filter and smoke matching

The `filter_audit_not_yet_divorced_lag3.csv` shows **0 treated rows/persons** and **0 control person-years/persons** removed at `require observed t0-2 and t0-3 records`. Immediately before and after that filter, treated stayed at **429 rows/429 persons**; controls stayed at **322,874 person-years/65,690 persons**. One risk-set partition completed with these final counts.

`fit_and_match` deletes `_matching_temp` after successful completion, so the final yearly numbers below come from `matching_audit_not_yet_divorced_lag3.csv`; the edge-stratum numbers come from `matching_edge_preflight_not_yet_divorced_lag3.csv`.

| t0 | Treated | Controls available after prior-year use | Matched | Rate | Candidate real edges | Optimal solver counts | Largest stratum real edges (plus dummies) |
|---:|---:|---:|---:|---:|---:|---|---:|
| 2014 | 90 | 56,578 | 90 | 1.000 | 155,468 | dense Hungarian: 36 | 10,782 (10,788) |
| 2015 | 107 | 58,465 | 107 | 1.000 | 167,406 | dense Hungarian: 41 | 12,925 (12,932) |
| 2016 | 102 | 52,185 | 97 | 0.951 | 160,062 | dense Hungarian: 39 | 21,210 (21,216) |
| 2017 | 70 | 51,139 | 67 | 0.957 | 107,220 | dense Hungarian: 34 | 7,256 (7,260) |
| 2018 | 60 | 50,529 | 58 | 0.967 | 90,564 | dense Hungarian: 34 | 5,256 (5,259) |

No smoke stratum exceeded **100,000,000** admissible edges, and all `would_fail_current_matcher` values were false. The largest exact strata, respectively, were `{age_band:25-29, ever_rehab:0, sex:1}`, `{<20,0,2}`, `{90+,0,2}`, `{80-84,0,2}`, and `{65-69,0,2}`. The edge-cap comparison for the full panel is **unknown**. There were no propensity non-convergence or rare-category-pooling warnings in the smoke `pipeline.log`; all five propensity fits converged. Polars emitted LazyFrame schema-resolution performance warnings to stdout.

## Deviations and remaining work

The full run was withheld because the machine has 24 GB RAM. The harness uses environment variables to select the smoke panel/output, adds stage timing and peak-RSS instrumentation, and sets `total_rebuild=False` while still calling the secondary entry point with `force=True`: configuring logging before the entry point with the default `total_rebuild=True` would unlink the active `logs/pipeline.log`. The smoke slice was relabelled because its marker was omitted; the copied full panel would skip relabel. The existing Path A panel has 148.5M rows and constant person coverage rather than the requested ~200M rows with staggered entry. No changes were made to `psm_260915.py`; `RISK_SET_PARTITION_TARGET_ROWS` remains 20,000,000. The 500M sparse-edge cap was used only in the smoke harness; no full-scale matcher ran.

To finish the requested stress test, run the copied panel and `run_lag3_test.py` on a machine meeting the stated RAM minimum, start the long process with `nohup` and a log file, and monitor `pipeline.log`. The panel's zero lag-coverage attrition remains a design limitation even on that hardware; a panel with staggered entry would be needed to test that aspect representatively.

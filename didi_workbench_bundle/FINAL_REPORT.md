# FINAL_REPORT.md

## What was built

A self-contained folder, `didi_workbench_bundle/`, meant to be uploaded to Posit Workbench
and run there by hand (no internet access to this laptop from Workbench, no way for the
assistant that built it to reach Workbench directly). It contains:

- The unchanged estimator (`psm_260915.py`), copied byte-for-byte.
- A calibrated synthetic raw-data generator (`scripts/generate_raw.py`) that reproduces the
  real 20% sample's row-count quotas, treated/control funnel structure, and -- the part a
  prior synthetic generator (documented in `export_20260911/GATE2_REPORT.md`) got wrong --
  the real data's per-age-band matching-load pattern (how bunched or spread the fitted
  propensity scores are within each exact-match stratum).
- An independent PyArrow-only validator, a real-vs-synthetic matching-load comparison tool,
  a config writer, a cgroup-aware memory gate, a background-run wrapper with live memory
  sampling, a status dashboard, and a plain-language report builder.
- A PDF/Markdown setup guide and a notebook alternative.
- Every calibration number traced to a specific source file (`calibration_20pct.json`).

## What was run locally, and what it showed

See `LOCAL_TEST_REPORT.md` for full detail; summarized here:

- `psm_260915.py --self-test`: PASS.
- 0.001 scale (211,594-row target): generate/validate/schema-check all PASS; full pipeline
  (all three specs -- lag1 full window, lag1 restricted, lag3) completed successfully in
  5m42s with 20/20 mediation bootstrap replicates in every spec, peak memory 1.45 GiB.
- 0.01 scale (2,115,938-row target): generate/validate/schema-check all PASS; full pipeline
  (all three specs) completed successfully in 18m03s with 20/20 mediation bootstrap
  replicates in every spec that runs mediation, peak whole-process memory 4.02 GiB.
  (The first launch attempt produced a spurious exit code `127` from a background-job
  exit-capture bug that was already mid-fix when that attempt launched; see `BUILD_LOG.md`
  item 6 for the full diagnosis and independent re-verification of the fix.)
- The mandatory Step-3 calibration check (`scripts/compare_preflight.py --scale 0.01`):
  **initially FAILed** (15 of 19 present strata outside the 15pp-tolerance-or-overlap check,
  50-54/60-64 diverging by 24-67 percentage points) -- a real finding about
  `scripts/generate_raw.py`'s calibration, not a pipeline defect. **Root cause**: this
  bundle's own `calibration_20pct.json` has prose ("near-total admissible share at ages
  60-74") that contradicts its own data table (60-64 is actually a distinct, much lower
  intermediate regime, 31.6-45.7%) -- a prior session trusted the prose. Recalibrated
  `AGE_BAND_SHARPNESS` against the real per-stratum numbers (not the prose), which also
  surfaced and fixed a second, independent bug (a shared RNG stream silently letting one
  age band's retuning perturb unrelated bands' results), and a third: the recalibration
  initially broke the 0.001-scale regression check by making a tiny discrete-time outcome
  model's data degenerate (one class only) -- fixed by making sharpness scale-dependent
  (gentler, originally-proven-safe values below 1% scale; the calibrated values only where
  the check is actually meaningful, 1%+). **Current result: 12 of 19 present strata PASS**
  (up from 4 of 19 present-and-passing). The 7 remaining fails are each individually
  diagnosed with real per-stratum `n_treated` counts in `BUILD_LOG.md` items 7-8 and
  `LOCAL_TEST_REPORT.md` -- 6 are small-N artifacts of testing quotas of 1-5 people at 1%
  scale, 1 is a named quota-depletion-across-years mechanism. **This should be re-checked
  once a larger scale (0.1, 1.0) is run** -- the same `n_treated` quantities that are 1-14
  people at 1% become 10-140+ at 10%, which should shrink the small-N noise substantially;
  not re-verified here since 0.01 is as far as this session's local testing goes. Full detail
  in `LOCAL_TEST_REPORT.md` and `results/preflight_comparison_0.01.csv`.

## Estimator SHA-256, before and after

- Gate-2-validated (per `export_20260911/GATE2_REPORT.md`):
  `db6e6f0b15d5d27d9492e8098f1fc5e7a2d2c34045215fad08734a00de9c0ad0`
- Local copy used to build and test this bundle (post-`a7c52db` xerr fix):
  `1584052db3bcac0d241bbab58671d6af242c25a34f151bd335b2515251273546`
- **These differ, and that is expected and explained**: the local copy includes one commit
  made after the Gate 2 run (`a7c52db`, "fix plotting when estimates fall outside boostrap
  cis") that fixes the exact Matplotlib `xerr` plotting bug Gate 2 flagged as an unresolved
  risk. See `BUILD_LOG.md` for the full detail. The estimator was copied into the bundle
  byte-for-byte and never edited by this bundle-building process -- both hashes were computed
  from files, never asserted from memory.
- After copying into the bundle (`didi_workbench_bundle/psm_260915.py`), as of the bundle
  build referenced above: identical to the local copy above (verified: see `MANIFEST.json`).
- **2026-09-17, deliberate hand-edit by the paper's author (not a Claude Code change)**:
  `79913323979459633db82f254a747180a0293aec8850e95847f3696936fcb056`. Adds
  `build_descriptive_statistics_table` (a plain n/mean/median/SD/min/max and n/% summary of
  the matched sample, wired into `build_paper_summary_tables` as `paper_descriptive_statistics.csv`)
  and fixes an annual-death undercount: `recorded_deaths_in_year` only counted a death when
  the person also had an ordinary person-year row in their death year, which
  `panel_coverage_diagnostics.csv` shows undercounts substantially since most recorded deaths
  occur strictly after a person's last annual record. A new `deaths_by_death_year` column
  (person-level death year, counted once, via an outer join so a death year with zero
  ordinary person-year rows still surfaces) is now the correct count to quote;
  `recorded_deaths_in_year` is kept only as a backward-compatible audit column. Mortality
  follow-up and all mortality estimates were always unaffected, since death year enters the
  outcome builders as a person-level attribute, not through annual rows. Verified via the
  same fast-check + local-test-ladder process this bundle uses throughout: `--self-test`
  PASS, `--environment-check` clean, `--schema-check` clean (no missing required columns);
  full `run_stage.sh all` at 0.001 and 0.01 scale both exit 0 with no fatal tokens; the
  0.01-scale Step-3 calibration check is still exactly 12 of 19 present strata PASS, and
  `results/preflight_comparison_0.01.csv` is byte-identical to the pre-edit baseline (the
  edit does not touch propensity scoring or matching logic, so this check is unaffected as
  expected). Full diff, fast-check output, and test-ladder output logged in `BUILD_LOG.md`
  under "2026-09-17 -- hand-edited psm_260915.py".

## The exact command sequence to run on Workbench

```
unzip didi_workbench_bundle.zip
cd didi_workbench_bundle
bash scripts/setup_env.sh
bash scripts/setup_env.sh --self-test
python scripts/check_machine.py
bash scripts/run_stage.sh all 0.001
python scripts/compare_preflight.py --run ../didi_data/runs/workbench_synthetic_0.001_seed42 --scale 0.001
bash scripts/run_stage.sh all 0.01
python scripts/compare_preflight.py --run ../didi_data/runs/workbench_synthetic_0.01_seed42 --scale 0.01
bash scripts/run_stage.sh gate 0.1
# if GO:
bash scripts/run_stage.sh all 0.1
python scripts/compare_preflight.py --run ../didi_data/runs/workbench_synthetic_0.1_seed42 --scale 0.1
bash scripts/run_stage.sh generate 1.0
bash scripts/run_stage.sh validate 1.0
bash scripts/run_stage.sh gate 1.0
# if GO:
bash scripts/run_stage.sh pipeline 1.0
```
(Full explanation of each step, what a good result looks like, and what to do on a NO-GO, is
in `docs/SETUP_GUIDE.md`.)

## What could not be tested locally, and why

- **Python exactly 3.9.1** -- this laptop cannot install that exact patch; tested against
  3.9.25 (same 3.9.x line) instead. All other pins matched their target versions exactly.
- **Real `/usr/bin/time -v` memory figures for the fast stages** (`generate`/`validate`/
  `schema-check`) -- macOS has no `-v` flag; the `pipeline` stage's memory figures, which are
  the ones that matter for the memory gate, come from `scripts/monitor_memory.py`
  (psutil-based), which is identical code on macOS and Linux and so is not a
  laptop-vs-Workbench gap.
- **The real cgroup-aware memory detection path** in `scripts/check_machine.py` -- macOS has
  no cgroups, so only the macOS-only `sysctl` fallback path was exercised locally; the
  `/sys/fs/cgroup/memory.max`/`/proc/meminfo` logic that will actually run on Workbench was
  written carefully against the documented cgroup v1/v2 file locations but not observed
  running for real.
- **Scales at or above 0.1** -- not run locally due to session time, not a resource limit
  (this laptop's 24 GiB RAM and 719 GiB free disk could plausibly handle 0.1 too). The
  `pipeline` stage's code path is identical at every scale; 0.001 and 0.01 already exercise
  every stage and every code branch (matching, all three specs, mediation bootstrap, figure
  generation) that a larger scale would also exercise.
- **A real memory-gate NO-GO** -- not observed; this laptop's 24 GiB was never close to the
  projected peaks at the scales tested locally.
- **The full 211,593,776-row raw generation** -- not run locally (would take on the order of
  hours based on the measured per-row generation rate; see `BUILD_LOG.md`), since it is a
  disk-and-time job explicitly meant for Workbench, not a code-correctness risk this bundle's
  local test needed to de-risk (the same generation code path was exercised, just at smaller
  row counts).

Nothing above is claimed to have been tested when it was not; where a number could not be
measured, this report says so plainly rather than substituting a Gate 2 reference figure or
an estimate.

## Bundle size

`didi_workbench_bundle.zip`: **434 KiB** (444,798 bytes), 119 files. Excludes `venv_didi/`
(a macOS-only Python environment that can't run on Workbench's Linux machine anyway --
`scripts/setup_env.sh` builds a fresh one there), `scripts/__pycache__/`, and `.DS_Store`
files. Includes `results/` (this bundle's own local-test logs/JSON/CSVs, for comparison
against Workbench's numbers) -- the actual generated raw data and run *outputs* (parquet
panels, figures) live under `../didi_data/` outside the bundle folder entirely and are
never part of the zip.

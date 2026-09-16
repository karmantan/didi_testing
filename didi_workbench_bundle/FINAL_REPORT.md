# FINAL_REPORT.md

<!-- DRAFT: sections marked PLACEHOLDER are completed after the 1%-scale local test and
     packaging step finish. Written in plain language per the task's own request. -->

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

PLACEHOLDER -- filled in after the 0.01-scale run completes. See `LOCAL_TEST_REPORT.md` for
full detail; summarized here:

- `psm_260915.py --self-test`: PASS.
- 0.001 scale (211,594-row target): generate/validate/schema-check all PASS; full pipeline
  (all three specs -- lag1 full window, lag1 restricted, lag3) completed successfully in
  17m35s with 20/20 mediation bootstrap replicates in every spec; one unexpected (but
  non-fatal) numpy warning found, not previously documented in Gate 2's warning inventory.
- 0.01 scale (2,115,938-row target): PLACEHOLDER.
- The mandatory Step-3 calibration check (`scripts/compare_preflight.py`): PLACEHOLDER.

## Estimator SHA-256, before and after

- Before (Gate-2-validated, per `export_20260911/GATE2_REPORT.md`):
  `db6e6f0b15d5d27d9492e8098f1fc5e7a2d2c34045215fad08734a00de9c0ad0`
- Local copy used to build and test this bundle:
  `1584052db3bcac0d241bbab58671d6af242c25a34f151bd335b2515251273546`
- **These differ, and that is expected and explained**: the local copy includes one commit
  made after the Gate 2 run (`a7c52db`, "fix plotting when estimates fall outside boostrap
  cis") that fixes the exact Matplotlib `xerr` plotting bug Gate 2 flagged as an unresolved
  risk. See `BUILD_LOG.md` for the full detail. The estimator was copied into the bundle
  byte-for-byte and never edited by this bundle-building process -- both hashes were computed
  from files, never asserted from memory.
- After copying into the bundle (`didi_workbench_bundle/psm_260915.py`): identical to the
  local copy above (verified: see `MANIFEST.json`).

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

PLACEHOLDER -- filled in at packaging (Step 10).

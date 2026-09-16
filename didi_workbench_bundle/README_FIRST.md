# README_FIRST.md

## What this is

A portable, self-contained test bundle for `psm_260915.py` (the divorce/rehabilitation
matched-cohort PSM estimator), meant to be uploaded to Posit Workbench and run there by
hand. It generates synthetic raw data calibrated against the real 20% administrative
sample's own diagnostics, validates it, and runs the unchanged estimator against it at
whatever scale your Workbench session can honestly handle -- to catch crashes and measure
timing/memory for the pipeline stages that have never run at the real matched-sample scale
(~115,000 pairs), before spending secure-machine time on them.

It does **not** prove anything about the real data's actual results (overlap, effect sizes,
identification) -- only that the code runs correctly and behaves the way the real data's own
matching-load pattern predicts it should. See `docs/SETUP_GUIDE.md` section 1 for the full
explanation, and `export_20260911/GATE2_REPORT.md` for why this exists (a prior,
uncalibrated synthetic generator produced an unrealistic matching-edge explosion that made
an earlier scale test uninformative).

## What to run first

1. Upload and unzip this folder on Posit Workbench (see `docs/SETUP_GUIDE.md` section 2).
2. Start a session with the **largest memory profile you're allowed** and **Python 3.9.1**
   selected (section 3).
3. Open a Terminal and run, in order:
   ```
   bash scripts/setup_env.sh
   bash scripts/setup_env.sh --self-test
   python scripts/check_machine.py
   bash scripts/run_stage.sh all 0.001
   ```
4. Then follow `docs/SETUP_GUIDE.md` section 4 for the rest of the scale ladder.

## Where things are

- `psm_260915.py` -- the unchanged estimator (copied byte-for-byte; see `MANIFEST.json` for
  its SHA-256 and how it compares to the Gate-2-validated hash).
- `calibration_20pct.json` -- every calibration number this bundle uses, each traced to a
  specific file under `export_20260911/20pct/` (bundled alongside, for you to check).
- `scripts/` -- every stage's entry point; see `docs/SETUP_GUIDE.md` for what each one does.
- `docs/SETUP_GUIDE.md` (and `SETUP_GUIDE.pdf`) -- the full walkthrough. **Read this before
  typing anything else.**
- `BUILD_LOG.md` -- what was built, measured, and decided while assembling this bundle,
  including the generator's calibration-iteration history.
- `LOCAL_TEST_REPORT.md` -- what was actually run and measured on the laptop that built this
  bundle, for comparison against your own Workbench numbers.
- `FINAL_REPORT.md` -- the top-level summary: what was built, what was tested locally, and
  what could not be tested locally (and why).

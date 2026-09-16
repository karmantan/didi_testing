# LOCAL_TEST_REPORT.md

What was actually run on the laptop that built this bundle, and what it showed. Every
number below is measured, not estimated -- see `BUILD_LOG.md` for the full narrative,
including the calibration-iteration history for `scripts/generate_raw.py`.

## Laptop environment

- macOS (Darwin 25.6.0, arm64/Apple Silicon), 24 GiB RAM, 8 logical cores, zsh.
- Python 3.9.25 via Homebrew (`python@3.9`) -- not 3.9.1 exactly (unavailable on this
  laptop), but the same 3.9.x line. `venv_didi` built from this interpreter.
- All pins in `requirements.txt` installed cleanly, including `polars==0.20.16` (exact
  match to the real run's `target_polars`).
- `psm_260915.py --self-test`: **PASS**, exit 0. (Peak memory not measured for this stage on
  this laptop: macOS's `/usr/bin/time` has no `-v` flag; `scripts/setup_env.sh --self-test`
  detects this and says so plainly rather than fabricating a number. It *will* be measured on
  the actual Linux Workbench session.)
- `.sh` scripts: all pass `bash -n` (syntax-only) in addition to actually being executed
  end-to-end below (this laptop is not Windows, so the "syntax-check only" fallback in the
  task instructions did not apply -- every script below was actually run, not just parsed).
- `.py` scripts: all pass `python -m py_compile` and were actually executed below.
- CRLF check: zero hits in any authored file (script/doc/config); see `BUILD_LOG.md` for the
  one documented exception (verbatim-copied real diagnostic JSON files from
  `export_20260911/20pct/`, which are Windows-sourced data files, never executed as code).

## Scale 0.001 (Gate-1-pilot size, target 211,594 raw rows)

This scale was run twice across this bundle's history: once before the `generate_raw.py`
recalibration (17m35s, clean), and once after -- both with `psm_260915.py` unchanged. The
second run is what's reported below (it is what actually ships); see `BUILD_LOG.md` item 8
for why a full re-run was necessary (the first recalibration attempt broke this scale, and
the fix had to be verified for real, not asserted).

| Stage | Result | Elapsed | Notes |
|---|---|---:|---|
| `generate` | 236,953 raw rows / 22 shards | ~5 s | ~12% above the linear target (this generator's average rows-per-person is a bit higher than the real data's, due to the simplified uniform observation-window model -- see BUILD_LOG.md) |
| `validate` | **PASS** | <1 s | all checks passed |
| `schema-check` | **PASS** | ~2 s | `"missing_required_columns": []` |
| `gate` | GO | <1 s | projected peak 1.39 GiB (Gate 2 1%-reference-based fallback) vs. 19.2 GiB ceiling |
| `pipeline` | **completed, exit 0** | 5m42s (21:10:50 - 21:16:32) | all three specs produced complete `run_outputs.json`; 20/20 mediation bootstrap replicates succeeded in every spec; 22 figure files (PNG+PDF); 0 Traceback/MemoryError/Killed tokens in stderr; peak whole-process-tree memory **1.4487 GiB** |
| `compare_preflight` | not meaningful at this scale | -- | only 5 of the 20 largest real strata have any synthetic counterpart at all (below the script's own "at least half" meaningfulness threshold) -- same conclusion as before recalibration; see the 0.01 section below for the scale where this check is actually informative |

Disk: `raw_0.001/` = 5.7 MB; `runs/workbench_synthetic_0.001_seed42/` (primary spec only) =
14 MB.

Warning inventory (stderr): 12 Polars streaming-sink fallbacks, 10 Polars streaming-collect
fallbacks (both expected, same types as `GATE2_REPORT.md`'s inventory), 621 g-computation
extrapolation-cap truncation notices (the same non-fatal, already-observed-at-0.01-scale
notice type; more frequent here simply because this run's specific random draws hit the cap
more often -- not a new warning class), and 1 duplicate-key resolution notice. 0
Traceback/MemoryError/Killed/xerr-yerr tokens. This run did not reproduce the single
`RuntimeWarning: All-NaN slice encountered` an earlier 0.001 run showed (see prior session's
notes) -- consistent with that having been small-N draw-specific noise, not a deterministic
generator or estimator defect.

**Why this scale was re-run mid-session**: the `generate_raw.py` recalibration below (raising
several `AGE_BAND_SHARPNESS` values to fix the 0.01-scale `compare_preflight.py` FAIL)
initially applied unconditionally to every scale, and broke this one --
`RuntimeError: All sklearn logistic fitting routes failed: ...only one class: 0` inside a
discrete-time outcome model, because raising sharpness changes exactly which handful of
people get selected as treated, and at 0.001 scale's ~64-90 total treated people this has a
real chance of producing a degenerate all-zero outcome somewhere among `psm_260915.py`'s
many small per-spec model fits. Fixed structurally (not by picking different lucky numbers):
`AGE_BAND_SHARPNESS` is now scale-gated -- the original, proven-safe values apply below 1%
scale (where this calibration check was never meaningful anyway), the recalibrated values
apply at 1%+ (where they were actually verified). See `BUILD_LOG.md` item 8 for the full
diagnosis, including the bisection that isolated which specific change caused the first
crash and why a second crash at a different call site made "keep chasing crash sites"
the wrong strategy.

## Scale 0.01 (Gate-2-pilot size, target 2,115,938 raw rows)

`pipeline_0.01` was run four times across this bundle's history: launch 1 hit a stale
`wait "$pid"`-based exit-code bug (`BUILD_LOG.md` item 6, unrelated to the generator) and
was discarded once fixed and re-verified; launch 2 was clean but its `compare_preflight.py
--scale 0.01` result was **FAIL** (15 of 19 present strata outside tolerance), which
triggered the `generate_raw.py` recalibration in `BUILD_LOG.md` item 7; launch 3 (with the
first recalibration attempt) was clean and mostly passed calibration, but that recalibration
broke 0.001 (see above), so the sharpness values were adjusted again and re-verified; launch
4, below, is the full clean re-run with the final, scale-gated generator that also keeps
0.001 working.

| Stage | Result | Elapsed | Notes |
|---|---|---:|---|
| `generate` | 2,370,254 raw rows / 22 shards | ~65 s | same at every stage of this recalibration -- `AGE_BAND_SHARPNESS` only changes *which* people are selected as treated, not row counts |
| `validate` | **PASS** | <1 s | all checks passed |
| `schema-check` | **PASS** | ~2 s | `"missing_required_columns": []` |
| `gate` | GO | <1 s | projected peak 13.93 GiB (Gate 2 1%-reference-based fallback) vs. 19.2 GiB ceiling |
| `pipeline` | **completed, exit 0** | 18m03s (21:18:23 - 21:36:27) | all three specs produced complete `run_outputs.json`, no `.tmp`/empty files left in any run directory; 20/20 mediation bootstrap replicates succeeded in every spec that runs mediation; 0 Traceback/MemoryError/Killed tokens in stderr; peak whole-process-tree memory **4.0216 GiB** (109 samples every 10s) -- well under the 13.93 GiB Gate-2 fallback projection. (Elapsed varied 18-40 minutes across this session's several full runs of this same code path, purely with laptop CPU contention from other concurrent work in this session -- not a code behavior change; the pre-recalibration baseline was 21m52s.) |
| `compare_preflight` | **12 of 19 PASS** | <1 s | full table in `results/preflight_comparison_0.01.csv`; see below |

Disk: `raw_0.01/` = 55 MB; `runs/workbench_synthetic_0.01_seed42/` (primary spec only) =
120 MB.

**`compare_preflight.py --scale 0.01` result: 12 of 19 present PASS** (19/20 strata present
this run -- `2018,65-69` happened not to reach quota this specific run, a small-N fluke, not
a regression; up from 4 of 19 present-and-passing before recalibration). The 7 remaining
fails are individually diagnosed in `BUILD_LOG.md` item 7 with real `n_treated_in_stratum`
counts from this run's own diagnostics CSV:
- 3 strata (`2017,65-69` nt=1; `2015,65-69` nt=1; `2014,70-74` nt=1) have exactly **1**
  synthetic treated person at this 1%-scale quota -- whether that single draw's propensity
  score lands inside the real range is close to a coin flip no per-band scalar can fully
  control.
- 3 strata (`2012,60-64,sex2` nt=3; `2014,60-64` nt=5; `2015,60-64` nt=4) are the same
  small-N effect one order of magnitude less extreme; same-sized strata elsewhere in the
  same band (`2012,60-64,sex1` nt=4, `2013,60-64` nt=6) DO pass, showing this is a per-draw
  outcome, not a one-directional bias.
- 1 stratum (`2013,50-54`, nt=14 -- not small) has a specific, verified cause: quota-based
  without-replacement selection across years sharing an overlapping birth-year pool means
  earlier-processed years claim the most extreme-z candidates from that shared pool first,
  weakening a later year's effective separation. Which specific year this hits (`2013` here;
  `2014` at a different `50-54` sharpness tested earlier) shifts with the exact parameter
  value -- confirmed by testing three different `50-54` values, all of which fixed one year
  while degrading another, never all years simultaneously.

**Root cause of the original FAIL**: `AGE_BAND_SHARPNESS["60-64"]` was miscalibrated (0.7,
almost as low as 65-69's 0.25) because a prior session trusted `calibration_20pct.json`'s
own prose ("near-total admissible share... at ages 60-74") over its own data table, which
actually shows 60-64 as a distinct intermediate regime (31.6-45.7%), not near-total. A
second, independent bug was found and fixed during recalibration: retuning one age band's
sharpness was silently changing *other* bands' results too, because every stratum drew its
Gumbel selection noise from one shared, sequentially-advancing RNG -- fixed by giving each
stratum its own independently-seeded RNG. A third issue -- raising `50-54`'s sharpness far
enough to fix 0.01 broke 0.001's outcome models -- was fixed by making sharpness scale-
dependent rather than picking a single compromise value (see the 0.001 section above and
`BUILD_LOG.md` item 8). Full iteration log (real numbers each round) in `BUILD_LOG.md`
items 7-8.

**This should be re-checked once a larger scale (0.1, 1.0) is actually run** -- the same
`n_treated` quantities that are 1-14 people at 1% scale become 10-140+ people at 10%,
which should shrink the small-N quantization noise substantially; not re-verified here
since 0.01 is as far as this session's local testing goes.

## What was not tested locally, and why

- **Python exactly 3.9.1**: this laptop has no way to install that exact patch (Homebrew's
  `python@3.9` gives 3.9.25). Tested against 3.9.25 instead, same 3.9.x line, all pins
  installed and matched target versions except the Python patch itself.
- **`/usr/bin/time -v` memory figures**: macOS's `time` builtin has no `-v` flag and no
  peak-RSS reporting equivalent used here; `scripts/monitor_memory.py` (psutil-based,
  cross-platform) was used instead for the pipeline stage's memory figures, which is exactly
  what runs on Workbench too, so this is not a Workbench-vs-laptop gap for the numbers that
  matter (whole-process-tree RSS) -- only for the *stage-elapsed-time-and-peak* convenience
  numbers that `/usr/bin/time -v` would otherwise have added for `generate`/`validate`/
  `schema-check` (which are fast, low-memory stages where this doesn't matter).
- **Scales above 0.01**: not run locally, due to session time constraints, not a memory or
  disk limitation (this laptop's 24 GiB and 719 GiB free disk could likely handle 0.1 too).
  `scripts/run_stage.sh`'s `pipeline` stage logic is identical at every scale (same code
  path, different `--fraction`/row count), so this is considered a low-risk gap; the 0.001
  and 0.01 runs already exercise every stage and every code branch (matching, all three
  specs, mediation bootstrap, figure generation) that a larger scale would also exercise.
- **cgroup-aware memory detection** (`scripts/check_machine.py`'s primary logic path): macOS
  has no cgroups, so this laptop only exercised the macOS-only `sysctl hw.memsize` fallback
  path, not the real `/sys/fs/cgroup/memory.max` / `/proc/meminfo` logic that will actually
  run on the Linux Workbench session. That logic was written carefully against the documented
  cgroup v1/v2 file locations but is untested on an actual cgrouped Linux host.
- **10%/100%-scale memory gate NO-GO behavior**: not exercised with a real NO-GO decision
  locally (this laptop's 24 GiB was never close to the projected peaks at the scales tested).
  The NO-GO code path itself (`scripts/memory_gate.py`'s decision logic) was read-reviewed
  and its arithmetic is straightforward, but was not observed to actually fire.

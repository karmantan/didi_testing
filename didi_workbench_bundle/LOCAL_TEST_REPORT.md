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

| Stage | Result | Elapsed | Notes |
|---|---|---:|---|
| `generate` | 236,953 raw rows / 22 shards | 4.7 s | ~12% above the linear target (this generator's average rows-per-person is a bit higher than the real data's, due to the simplified uniform observation-window model -- see BUILD_LOG.md) |
| `validate` | **PASS** | <1 s | all checks passed: schema, dtypes, per-shard SHA-256, duplicate-key count self-consistency, gap-count self-consistency, per-year treated-row sanity range |
| `schema-check` | **PASS** | ~2 s | `"missing_required_columns": []`; only expected absence is `maciufzt_succeed_1/2` (the OTHER accepted incapacity spelling -- this data uses `mcaiufzt_succeed_1/2`, matching the real 20% data exactly) |
| `gate` | GO | <1 s | projected peak 1.39 GiB (Gate 2 1%-reference-based fallback, no local run existed yet) vs. 19.2 GiB ceiling (80% of 24 GiB) |
| `pipeline` | **completed, exit success** | 17m35s (16:45:58 - 17:03:33) | all three specs (lag1 full window, lag1 restricted 2014-2018, lag3 2014-2018) produced `run_outputs.json`; 20/20 mediation bootstrap replicates succeeded in every spec; 16 figure files (PNG+PDF) generated; 0 Traceback/MemoryError/Killed/xerr-yerr tokens in stderr; **1 unexpected warning found** -- see below |
| `compare_preflight` | not meaningful at this scale | -- | only 6 of the 20 largest real strata have any synthetic counterpart at all (real treated counts of 130-260 people, times 0.001, round to 1-3 people -- too few for the admissible-share statistic to carry signal); see the 0.01 section below for the scale where this check is actually informative |

Disk: `raw_0.001/` = 5.7 MB; `runs/workbench_synthetic_0.001_seed42/` (primary spec only) =
14 MB.

Warning inventory (stderr): 4 Polars streaming-sink fallbacks, 24 Polars streaming-collect
fallbacks -- both are the same expected warning types `GATE2_REPORT.md`'s own warning
inventory documents. No g-computation extrapolation-cap warnings appeared yet at this tiny
scale (too few simulated draws to hit the cap).

**One warning outside GATE2_REPORT.md's expected-warning list was found**: a single numpy
`RuntimeWarning: All-NaN slice encountered` from `numpy/lib/nanfunctions.py` inside a
`nanquantile` call, during the lag-3 spec's mortality-followup stage. This is not
Traceback/MemoryError/Killed/xerr-yerr and did not affect the run's exit code (still 0) or
any `run_outputs.json` completeness -- but it is new, so it is reported here rather than
folded into the "expected" bucket. Working theory: at this extremely small 0.001 scale
(target 211,594 raw rows), some sex/stratum cell in a pooled mortality-curve confidence-band
computation has zero people, making a quantile computation over an all-missing slice. Checked
at 0.01 scale below to see whether it is a small-N artifact of 0.001 specifically or a
generator issue that persists at scale.

## Scale 0.01 (Gate-2-pilot size, target 2,115,938 raw rows)

`pipeline_0.01` was run twice: the first launch (17:43:38) was made with a `run_stage.sh`
that still had the `wait "$pid"`-based exit-code bug (see `BUILD_LOG.md` item 6) and its
result was correctly discarded and re-run once that bug was fixed and independently
re-verified. The table below is the second, trustworthy run.

| Stage | Result | Elapsed | Notes |
|---|---|---:|---|
| `generate` | 2,370,254 raw rows / 22 shards | 67.1 s | ~12% above the linear target (175,595 target people -> 2,370,254 raw rows), same known generator behavior as 0.001 |
| `validate` | **PASS** | <1 s | all checks passed; 103,458 duplicate `(simple_id, ja)` keys found and resolved (expected -- logged and reported, not silent) |
| `schema-check` | **PASS** | ~2 s | `"missing_required_columns": []` |
| `gate` | GO | <1 s | projected peak 13.93 GiB (Gate 2 1%-reference-based fallback, no local run existed yet) vs. 19.2 GiB ceiling (80% of 24 GiB) |
| `pipeline` | **completed, exit 0** | 21m52s (18:40:54 - 19:02:47) | all three specs (lag1 full window, lag1 restricted 2014-2018, lag3 2014-2018) produced complete `run_outputs.json`; 20/20 mediation bootstrap replicates succeeded in every spec that runs mediation; 22 figure files (PNG+PDF) across the three run directories; 0 Traceback/MemoryError/Killed tokens in stderr; peak whole-process-tree memory **3.6184 GiB** (132 samples every 10s, `pipeline_0.01_memory_samples.txt`) -- well under the 13.93 GiB Gate-2 fallback projection |
| `compare_preflight` | **FAIL** | <1 s | 19 of the 20 largest real strata present at this scale; 15 of 19 failed the 15pp-tolerance-or-overlap check -- see below |

Disk: `raw_0.01/` = 55 MB; `runs/workbench_synthetic_0.01_seed42/` (primary spec only) =
120 MB.

Warning inventory (stderr, 25 `[WARNING]` lines total): 12 Polars streaming-sink fallbacks,
12 Polars streaming-collect fallbacks (both expected, same types as 0.001 and
`GATE2_REPORT.md`'s inventory), plus 1 duplicate-key resolution notice (matches
`validate_0.01.json`'s `n_duplicate_person_year_keys: 103458`, already counted above). The
0.001-scale run's one unexplained numpy `RuntimeWarning: All-NaN slice encountered` did
**not** recur here (zero `RuntimeWarning` lines in this run's stderr) -- consistent with
that being a small-N artifact specific to the 0.001 scale's tiny per-cell counts, not a
generator or estimator issue that persists at scale.

**`compare_preflight.py --scale 0.01` result: FAIL.** This is the first scale at which the
check is actually informative (19/20 of the largest real strata have a synthetic
counterpart, vs. only 6/20 at 0.001). Full table in
`results/preflight_comparison_0.01.csv`. Real vs. synthetic admissible-share (propensity-
score spread) diverges sharply in the 50-54 and 60-64 age bands -- e.g. `t0=2012,
age=60-64, rehab=0, sex=1`: real 33.1% vs. synthetic 98.6% (65.5pp gap); `t0=2015, age=60-64`:
real 31.6% vs. synthetic 98.8% (67.1pp gap). The 65-69 band is much closer (2-7pp gaps) but
several of those still fail on the score-range-overlap check specifically, not the tolerance
check. **This means the generator's calibration against the real 20% sample's matching-load
pattern, which BUILD_LOG.md documents as iterated on and believed adequate, does not hold up
once measured at a scale where enough strata are populated to test it** -- the same kind of
failure this bundle exists to catch before Workbench time is spent on 0.1/1.0 scales. This
result is reported as measured, not corrected here: fixing `generate_raw.py`'s admissible-
share function is a real recalibration task in its own right (see `BUILD_LOG.md`'s existing
calibration-iteration history for the scope of that kind of work) and was out of scope for
this exit-code investigation. **Do not treat a 0.1 or 1.0 scale run as informative about
real-world matching load until this is re-run and passes**, per this script's own
`calibration_20pct.json`-referencing guidance.

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

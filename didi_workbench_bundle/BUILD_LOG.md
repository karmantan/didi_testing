# BUILD_LOG.md

Running log of what was built, measured, and decided while assembling `didi_workbench_bundle/`.
All timestamps are local (laptop) time on 2026-09-16 unless noted.

## Step 0 — Local inventory

- Laptop: macOS (Darwin 25.6.0, arm64 / Apple Silicon), shell zsh.
- RAM: 24 GiB. Free disk on `/System/Volumes/Data`: 719 GiB of 926 GiB (21% used).
- No `python3.9` on PATH initially; no `pyenv`, `uv`, or `conda`. Homebrew present
  (`/opt/homebrew/bin/brew`). `pandoc` present (`/usr/local/bin/pandoc`). No `docker`.
- Installed `python@3.9` via Homebrew -> Python 3.9.25 at `/opt/homebrew/bin/python3.9`
  (bottled; upstream-deprecated formula, scheduled for Homebrew removal 2026-10-15, but
  installable and usable today). This is used for ALL local testing in this bundle build,
  in place of an unavailable 3.9.1 build. It is not 3.9.1 exactly; the bundle's own
  `setup_env.sh` still requires 3.9.x on Workbench and will report the exact patch found
  there. Recorded in `LOCAL_TEST_REPORT.md`.
- No `scale_validation/` folder exists anywhere under this project directory or the laptop
  (`find` for `*scale_validation*` returned nothing). `vm_setup.md` (this project's own
  session log) confirms why: that folder lived only on a separate rented VM
  (`/home/tankmcarmen/didi_scale_workspace/`) used for the Gate 1/Gate 2 scale-validation
  work described in `export_20260911/GATE2_REPORT.md`; it was never copied back to this
  laptop. Per the task's Step 0 instruction ("If the folder is absent, build from
  scratch"), `scripts/generate_raw.py`, `validate_raw.py`, `compare_preflight.py`, and the
  rest are written fresh for this bundle, using `GATE2_REPORT.md` and the real
  `export_20260911/20pct/` diagnostics as the calibration source, and Gate 2's own
  generator design choices (documented in `GATE2_REPORT.md` and `vm_setup.md`) as a design
  reference where useful (e.g. per-shard streaming, deterministic seeding, treated
  modulus/people-batch approach).
- Folder naming note: the task text refers to `export_260911/20pct/`; the actual folder in
  this project is `export_20260911/20pct/` (the zip is dated 2026-09-11, hence the "2026"
  prefix the task text dropped). All bundle scripts and docs use the real name,
  `export_20260911`.
- `psm_260915.py` is present directly in the project root (not only inside a zip),
  402,715 bytes, last modified 2026-09-15 19:40 local time. This is the exact estimator
  script copied byte-for-byte into the bundle.
- **Estimator hash check (mandatory, Hard Rule 1):** local `psm_260915.py` SHA-256 is
  `1584052db3bcac0d241bbab58671d6af242c25a34f151bd335b2515251273546`. The Gate-2-validated
  hash recorded in `export_20260911/GATE2_REPORT.md` is
  `db6e6f0b15d5d27d9492e8098f1fc5e7a2d2c34045215fad08734a00de9c0ad0`. **These differ.**
  Cause identified via `git log`/`git show`: local git history has one commit after the
  Gate 2 run, `a7c52db "fix plotting when estimates fall outside boostrap cis"`
  (2026-09-15 19:52), which replaces `Axes.errorbar(..., xerr=...)`/`yerr=...` calls in the
  mediation/pretrend plotting functions with a new helper
  `_plot_point_estimates_with_intervals` that draws the CI as an explicit line segment
  between the recorded `ci_low`/`ci_high` endpoints instead of as a +/- offset from the
  point estimate — this is precisely the fix for the `ValueError: 'xerr' must not contain
  negative values` failure that `GATE2_REPORT.md` documents as an unresolved
  "sample-dependent production risk." So: the hash mismatch is expected and explained, the
  estimator was not edited by this bundle-build process (only copied), and the previously
  known plotting bug already appears fixed in this exact copy — but `make_report.py` still
  scans for the `xerr`/`yerr` failure signature defensively, because (a) this bundle must
  never assume a fix is complete without observing it hold under an actual run, and (b) the
  task's Hard Rule 6 says never patch the estimator ourselves regardless. Both hashes are
  recorded in `MANIFEST.json`.
- `psm_260915_testing.zip` in the project root contains prior Claude working notes
  (`claude_260908_runtime_and_resume_notes.md`, `claude_260914_msk_codes_and_resume_notes.md`,
  `claude_psm_260914.py` — an earlier estimator draft, `claude_section4_1_descriptive_summary_draft_260914.tex`,
  `claude_260914_code_testing.md`, `claude_260915_gcomp_overflow_fix_notes.md`,
  `claude_260914_scale_test_212M_rows_notes.md`). None of these are the current estimator
  or the calibration source of record; not used.

## Calibration source extraction (Step 3 groundwork)

All of the following were read directly from files under `export_20260911/20pct/` on this
laptop (not re-derived from the task prompt's summary numbers), per Hard Rule 7. Full
detail and exact source file names are recorded in `calibration_20pct.json`.

- `260909/run_manifest.json`: confirms 22 raw shards, sizes 44,719,675 to 248,418,891 bytes
  (44.7-248.4 MB), total 4.169 GB; the exact 40 `found_raw_columns` names (list captured
  verbatim); `target_runtime` = Python 3.9.1 / Polars 0.20.16; the real `USER_CONFIG`-shaped
  `config` block used for the run (this is the *initial* config recorded at manifest-write
  time, with `optimal_match_sparse_max_edges: 20000000` — see below for why this differs
  from the config actually used to finish the run).
- `260909/resolved_config.json`: the config actually resolved/used for the completed run —
  `optimal_match_sparse_max_edges: 100000000` (raised from the manifest's stale 20,000,000
  after a real stratum needed 54,715,054 edges; consistent with `GATE2_REPORT.md`'s
  account of this exact cap change), plus `mediation_bootstrap_workers: 0` and
  `propensity_solver: "lbfgs"`, which are absent from `run_manifest.json`'s earlier
  snapshot. Treat `resolved_config.json` as authoritative for real run settings, and
  `run_manifest.json` as authoritative for raw-file/column facts.
- `260909/pipeline.log`: `Runtime: Python=3.9.1; Polars=0.20.16; collect=streaming=True;
  collect_batches=False; fallback=lazy-slice`; "Bucketing 211,593,776 raw rows into 212
  person-hash buckets" across the 22 shards (per-shard cumulative counts read directly from
  the log, confirming the 211,593,776 total); "Building lag-1 risk sets from 200,295,283
  panel rows in 11 person-hash partition(s)"; per-year propensity/matching lines for all
  seven years 2012-2018, cross-checked against the `year_20XX_audit.json` files below and
  found consistent.
- `260908/panel_coverage_diagnostics.csv`: 17,559,407 retained people; records span
  2011-2024; 329,898 people with internal year gaps, 559,195 total gap-years; 2,514,450
  people with a recorded death year, of whom 1,915,117 have that death recorded after their
  last annual record and 599,333 on or before it.
- `260908/duplicate_person_year_keys_resolution.json`: 10,345,764 duplicate `(simple_id,
  ja)` keys, 11,297,317 excess rows dropped; rule = keep least-missing row per key, ties by
  first-encountered row.
- `260908/conflicting_person_death_years_resolution.json`: 102 of 17,559,509 total
  `simple_id`s have conflicting non-null death years and are excluded entirely (not just
  nulled); 0.0% of excluded people vs. 1.31% of retained people have `divorcing==1` in at
  least one year (recorded as an identification-ignorability check, not acted on further
  here).
- `260909/filter_audit_not_yet_divorced_lag1.csv`: treated funnel 140,063 -> 127,397 across
  six named steps (first-marriage restriction -1,117; alive-at-t0 -10; MSK-rehab-at-t0
  -2,604; observed-t0-1-record -758; valid-age-at-t0-1 -0; prior-MSK-rehab-through-t0-1
  -8,177); control funnel 98,657,411 -> 92,951,108 across the parallel six steps. Exact
  per-step counts captured, not just the endpoints, so the generator's `--fraction`-scaled
  funnel can match proportions at each step, not only start/end.
- `260909/matching_edge_preflight_not_yet_divorced_lag1.csv`: 347 (t0 x exact-stratum)
  rows across all seven years. Computed `admissible_share = candidate_real_edges /
  (n_treated_in_stratum * n_controls_in_stratum)` for every row (this column does not exist
  in the source file; it is derived, scale-free, and is exactly the quantity Step 3 of the
  task asks the generator to reproduce). Confirmed the task's own qualitative claim: the
  20 largest-edge-count strata are heavily age-65-69/no-prior-rehab (admissible share
  92.7-99.2%, propensity scores for both treated and control bunched near 0) plus a
  handful of age-45-54/no-prior-rehab strata (admissible share only 3.2-6.4%, propensity
  scores spread out over 0-0.3+). The single largest stratum is 2012, age 65-69, no prior
  rehab, sex 1: 252 treated x 401,030 controls = 98,612,694 candidate real edges (98.6M;
  the task prompt's own text says "98,612,946" for this cell — off by 252 from what the
  source CSV actually contains; per Hard Rule 7 the file wins, so `calibration_20pct.json`
  and `compare_preflight.py` use the file's 98,612,694). Full top-20-by-edges table and
  every stratum's fields are in `calibration_20pct.json`; `compare_preflight.py` reads the
  real CSV directly out of the bundled `export_20260911/20pct/260909/` copy rather than
  duplicating all 347 rows a second time.
- `260909/year_20XX_audit.json` (all seven years): treated counts 21,754 / 20,535 / 19,611
  / 18,373 / 16,791 / 15,739 / 14,594 (2012-2018; matches the task prompt's list exactly);
  eligible-control counts per year 13,226,732-13,370,917 (matches the prompt's
  "about 13.2-13.4 million" claim); match rates fall from 99.9% (2012) to 51.9% (2018,
  7,577/14,594) because `reuse_controls_across_years: false` and controls are consumed
  year over year — matches the prompt's "~52% by 2018" framing (task text said "about
  52%"; source gives 51.9%, close enough not to need reconciliation, but the source value
  is what is stored); per-year `mean_abs_ps_diff` among matched pairs ranges
  4.4e-05 (2012) to 3.5e-04 (2018).

## Step 7 local testing: bugs found and fixed

All found by actually running the scripts (not by inspection), consistent with Hard Rule 9
("if something fails locally, do not silently patch around it -- diagnose, then fix or
stop"). Each was diagnosed to a root cause before fixing.

1. **`Path.read_text(encoding=..., newline=...)` -- `TypeError`.** `pathlib.Path.read_text`
   has never accepted a `newline` keyword (only the builtin `open()` does). Every script that
   loaded `bundle_settings.env` with this pattern (`check_machine.py`, `make_config.py`,
   `memory_gate.py`, `make_report.py`) crashed on first real use. Fixed by dropping the
   invalid kwarg from the four `Path.read_text()` call sites (the `open(..., newline="\n")`
   calls used for *writing* files are correct and unaffected -- only the read side used the
   wrong API).

2. **YAML float formatting -- `TypeError: '<' not supported between instances of 'int' and
   'str'` from `PipelineConfig.validate()`.** `scripts/make_config.py`'s hand-written YAML
   writer emitted small floats (e.g. `gcomp_logit_tol: 1e-06`, from Python's `repr()`
   switching to exponential notation below 1e-4) without a decimal point. PyYAML's implicit
   float resolver requires a literal `.` in the mantissa even for the signed-exponent form,
   so `1e-06` parsed back as a plain *string*, and `pipeline.validate()`'s
   `0 < self.gcomp_logit_tol < 1e-2` comparison then crashed comparing an int to a str. Fixed
   by adding `_yaml_float()`, which always emits explicit decimal notation
   (`0.000001` instead of `1e-06`) for any float whose `repr()` contains `e`/`E`.

3. **`status.sh` -- silent early exit under `set -euo pipefail`.** `elapsed="$(grep ... |
   sed ... | head -1)"`: when the `grep` found no match (a normal case -- not every `.time`
   file has a `/usr/bin/time -v` "Elapsed" line, e.g. this laptop's macOS fallback files
   don't), `pipefail` made the whole pipeline's exit status non-zero even though `sed`/`head`
   individually succeeded, and since this was a plain assignment (not guarded by an
   `if`/`&&`/`||`), `set -e` killed the script with no error message -- `status.sh` printed
   only its header line and exited 1. Fixed by appending `|| true` to both `grep`-driven
   pipelines and converting the two bare `[[ cond ]] && action` statements that followed to
   explicit `if` blocks for clarity (those two were technically already safe under `set -e`'s
   `&&`/`||` exemption rule, but the explicit form is less fragile to future edits).

4. **`run_stage.sh`'s `pipeline` stage -- background-process exit code never captured.**
   The original design launched the pipeline with `nohup ... &`, then tried to capture its
   exit code via `(wait "$pid"; echo $? > exitfile) &` in a second backgrounded subshell.
   Discovered by hand-testing this exact pattern separately: `wait` failed with `pid N is not
   a child of this shell`, because a `nohup`'d, backgrounded child's job-table relationship to
   the launching shell is not guaranteed to survive for a later `wait` call in this execution
   environment. Fixed by moving the exit-code write *inside* the same backgrounded process,
   immediately after the pipeline command, via `nohup bash -c '"$1" "$2" ... ; echo $? > "$6"'
   _ ...` -- this has no dependency on shell job-control semantics at all. Verified the fixed
   pattern directly with a throwaway `bash -c 'exit N'` test before relying on it for a real
   (17+ minute) pipeline run.

5. **`make_report.py`'s fatal-token scanner -- false positives from naive substring
   matching.** `FATAL_TOKENS` included bare `"inf"`/`"Inf"`, matched via `str.count()`. This
   flagged the run's own `run_outputs.json` as containing 18 "Inf" occurrences at 0.001
   scale -- all of them were the substring inside `"inference_method"` (a legitimate field
   name describing the model's standard-error method), not a single actual infinite value.
   Fixed by switching single-word tokens (`OOM`, `NaN`, `Inf`/`Infinity`) to `\b`-word-bounded
   regexes (`\binf\b` correctly does NOT match inside `inference`, since there is no boundary
   between `f` and the following `e`), while keeping unambiguous multi-word phrases
   (`"Traceback (most recent call last)"`, `"MemoryError"`, `"Killed"`) as plain substrings.
   After the fix, the 0.001-scale run's real warning inventory reduced to exactly one
   genuine, non-fatal `RuntimeWarning: All-NaN slice encountered` (see the 0.001-scale test
   log below) -- a real finding, correctly surfaced once the false positives were removed.

## Line-ending check (Hard Rule 4)

Ran a CRLF scan (`grep -lU $'\r'`) over every `.py`/`.sh`/`.md`/`.env`/`.txt`/`.json`/`.ipynb`
file in the bundle. Result: zero CRLF hits in any file this bundle authored (every script,
every doc, every generated config). The only CRLF hits are in the 23 verbatim-copied real
diagnostic JSON files under `export_20260911/20pct/` (produced on the Windows secure
machine per `pipeline.log`'s `platform: Windows-10` line) -- these are data files, never
executed as code, so the actual risk Hard Rule 4 warns about (a `.sh` script failing on
Linux with a confusing `^M` error) does not apply to them. They are kept byte-identical to
their source, the same principle as copying `psm_260915.py` unedited, since Step 3's own
instruction is to copy `export_20260911/20pct/` in "for auditability" -- converting their
line endings would make them no longer byte-identical to what the secure machine produced.

## Fork: estimator config-surface introspection

Dispatched a background `Explore` agent to read all 8,778 lines of `psm_260915.py` and
report back (not paste back) the exact `PipelineConfig` field names/types/defaults,
`CANONICAL_DEFINITIONS`/`CORE_RAW_COLUMNS`/`DATE_COLUMNS`/`INCAPACITY_CANDIDATES`,
`USER_CONFIG`, `PAPER_REPORTING_CONFIG`, the `--config`/`--environment-check`/`--self-test`/
`--schema-check` CLI surface and exact output keys, the `matching_edge_preflight` CSV
naming/columns, `checkpoint_row_group_size`, and the `xerr` plotting bug location — all
needed before `generate_raw.py`, `make_config.py`, `memory_gate.py`, and
`compare_preflight.py` can be written correctly. Findings will be appended below once it
returns.

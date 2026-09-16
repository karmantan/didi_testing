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

6. **`pipeline_0.01.exit` read `127` even though `pipeline_0.01.stdout`/`.stderr` show a
   fully completed, correct run.** Root cause: `pipeline_0.01` was *launched* at 17:43:38-48
   (config birth 17:43:38, gate birth 17:43:42, pid-file birth 17:43:48) using the **still-
   buggy** `run_stage.sh` from item 4 above -- the `(wait "$pid"; echo $? > exitfile) &`
   pattern. `scripts/run_stage.sh`'s own mtime is 17:50:45, i.e. the item-4 fix landed
   *seven minutes after* `pipeline_0.01` was already running in the background. `wait "$pid"`
   in that detached subshell failed immediately with "not a child of this shell" (bash's
   documented behavior for `wait` on a PID outside the calling shell's job table), and a
   failed `wait` itself returns 127 -- so `echo $?` wrote `127` to `pipeline_0.01.exit`
   within seconds of launch. Evidence: `stat -f "%SB %Sm"` shows `pipeline_0.01.exit`'s birth
   time *equals* its modify time (17:43:48, a single write, never touched again) -- i.e. it
   was written once, right after launch, not after the ~30-minute run finished. The real
   `psm_260915.py` process launched by the same `nohup ... &` line was *not* affected by
   that bug (it doesn't depend on `wait`/job-control at all) and ran to completion
   independently: its first log line is 17:43:52 and its last is 18:13:42-45, matching the
   run directories' own `mtime`s (`workbench_synthetic_0.01_seed42__lag1_common_2014_2018`
   at 18:06:48, `..._lag3_common_2014_2018` and the top-level run dir both at 18:13:45-46).
   Confirmed no other explanation fits: `grep -n "subprocess\|os\.system\|check_call\|
   shell=True\|sys\.exit" psm_260915.py` still returns nothing, so the script cannot have
   deliberately produced 127 itself, and the currently-committed `run_stage.sh` (with item
   4's fix already applied) has no code path that writes to `*.exit` early. This was purely
   a stale artifact from a bug that already existed for part of one run's lifetime and was
   fixed mid-flight, with nothing left to re-check the already-running job's real exit code
   once psm_260915.py actually finished.

   Before trusting the item-4 fix for the real rerun below, re-verified it under the actual
   failure-prone conditions (a 15+ second backgrounded job with a concurrent sibling
   "monitor" process polling its PID, mirroring `monitor_memory.py`), not just the original
   short `bash -c 'exit N'` smoke test: a throwaway dummy pipeline script that sleeps ~15s
   and exits 3, launched via the exact `nohup bash -c '"$1" "$2" --config "$3" > "$4" 2>
   "$5"; echo $? > "$6"' _ ...` snippet with a sibling poller running alongside it, produced
   an exit file containing `3` with a birth/modify time ~16 seconds *after* the pid file's
   birth time (18:39:48 -> 18:40:04) and only after the sibling poller observed the target
   PID disappear -- i.e. the fix genuinely waits for the real command (not the wait-based
   job-control shortcut) and is not merely luck for interpreter-shutdown timing.
   `pipeline_0.01` was then re-run for real with the fixed script to get a trustworthy exit
   code end-to-end (see below).

7. **`generate_raw.py` recalibration for the 0.01-scale `compare_preflight.py` FAIL (15 of
   19 present strata).** The CSV (`results/preflight_comparison_0.01.csv` from the prior
   session) split into two distinct patterns, confirmed by reading the raw numbers rather
   than trusting any prior summary:

   **Pattern A (10 rows, 45-49/50-54/60-64 bands): synthetic admissible share far HIGHER
   than real** (e.g. `2012,60-64,sex1`: real 33.1%, synthetic 98.6%). Root cause: `AGE_BAND_
   SHARPNESS["60-64"]` was set to `0.7` -- almost as low as `65-69`'s `0.25` -- because the
   comment above it, and `calibration_20pct.json`'s own prose in `matching_edge_preflight.
   admissible_share_pattern`, both said "near-total admissible share (92-99%) at ages
   60-74". That prose is simply wrong about 60-64: `calibration_20pct.json`'s own `top_20_
   strata_by_candidate_real_edges` TABLE -- the actual ground truth `compare_preflight.py`
   reads -- shows 60-64 at 31.6-45.7%, a distinct intermediate regime, not near-total. A
   previous session trusted the prose over the table it contradicts (the table wins, same
   principle as Hard Rule 7). Fixed by raising sharpness for the three affected bands
   (`45-49`: 3.2 -> 8.0, `50-54`: 3.0 -> 7.0, `60-64`: 0.7 -> 2.3) via empirical iteration
   (below), also correcting the misleading comment in `generate_raw.py`.

   **Pattern B (5 rows, 65-69/70-74 bands): share already close (0.8-7.3pp) but treated/
   control propensity-score RANGES don't overlap.** Read `compare_preflight.py`'s `ranges_
   overlap()` first, per the task's own instruction to rule out a comparison-logic bug
   before touching the generator -- it's a plain, correct min/max interval check, no
   off-by-one. Confirmed with real numbers instead (e.g. `2013,65-69`: real treated pscore
   range `[1.56e-4, 0.123]`, synthetic (at the old sharpness) `[3.9e-5, 3.9e-5]` -- a single
   point, entirely below the real range's floor) that the actual scores genuinely don't
   overlap; not a comparison bug.

   **Fast iteration harness.** A full `pipeline` run takes ~22 minutes, but `psm_260915.py`
   writes `diagnostics/matching_edge_preflight_not_yet_divorced_lag1.csv` (the file this
   whole check reads) within the first ~60 seconds, well before mediation/figures. Verified
   this by watching the file's row count every 5s during one real run: all 7 years (2012-
   2018) present and stable by t=60s. Built a throwaway harness
   (`scripts/run_stage.sh generate 0.01` + `validate 0.01`, then launch `psm_260915.py`
   directly and kill it once `diagnostics/...csv` contains a `2018,` row) that turned each
   calibration iteration from ~22 minutes into ~2 minutes -- used for every iteration below;
   NOT used for the final verification run.

   **A second, distinct bug found mid-iteration**: retuning one age band's `AGE_BAND_
   SHARPNESS` value changed *other, unrelated* bands' results too. Root cause: the
   treated-selection loop drew each stratum's Gumbel noise from the single, sequentially-
   advancing `rng_master` stream shared across the whole function. Changing one stratum's
   selection changes how many people remain eligible for later-processed strata (a real,
   correct effect -- the same person can age from one band into another across 2012-2018
   and be legitimately claimed by an earlier year), which changes `candidate_idx.size` for
   those later strata, which shifts how many random numbers they draw, which shifts
   `rng_master`'s position for every draw after that -- so retuning band X silently
   perturbed band Y's results purely from RNG-position drift, with no real shared-person
   cause. Confirmed by re-running an identical sharpness change for bands 65-69/70-74 twice
   with different 60-64 values and observing 65-69/70-74's own numbers change both times.
   Fixed by giving each stratum's Gumbel draw its own independently-seeded RNG (derived
   deterministically from `seed`/`t0`/`band`/`sex`/`rehab` via `hashlib.sha256`), leaving the
   real person-eligibility constraint (`person_used`) untouched. Still fully deterministic
   for a given `--seed`.

   **Iteration log** (admissible-share / overlap results per round, fast-harness runs unless
   noted; see `results/preflight_comparison_0.01_iter.csv` for the last one's full table):
   | Round | 45-49 | 50-54 | 60-64 | 65-69 | 70-74 | Present/20 | Pass |
   |---|---|---|---|---|---|---|---|
   | 0 (original) | 3.2 | 3.0 | 0.7 | 0.25 | 0.15 | 19 | 4 |
   | 1 | 8.0 | 7.0 | 3.0 | 0.6 | 0.4 | 18 | 12 |
   | 2 | 8.0 | 7.0 | 1.8 | 2.0 | 1.2 | 18 | 12 |
   | 3 | 8.0 | 7.0 | 2.3 | 2.5 | 0.8 | 20 | 12 |
   | 4 | 8.0 | 7.0 | 3.5 | 5.0 | 2.5 | 18 | 12 |
   | 5 (RNG bug found: composing round 3+4 values did NOT reproduce either round) | 8.0 | 7.0 | 3.5 | 2.5 | 0.8 | 20 | 11 |
   | 6 (after RNG-independence fix, same nominal values as round 3) | 8.0 | 7.0 | 2.3 | 2.5 | 0.8 | 20 | 12 |
   | 7 (50-54->8.5, 60-64->2.8, 65-69->3.0: worse on 2017/2013) | 8.0 | 8.5 | 2.8 | 3.0 | 0.8 | 18 | 11 |
   | 8 (50-54->6.5: worse than round 6 on 2013/2014) | 8.0 | 6.5 | 2.3 | 2.5 | 0.8 | 19 | 12 |

   **Final values** (round 6, reverted from rounds 7/8 which were both worse):
   `AGE_BAND_SHARPNESS = {"45-49": 8.0, "50-54": 7.0, "60-64": 2.3, "65-69": 2.5, "70-74":
   0.8}` (other bands unchanged). Result: **12 of 20 PASS, 20/20 present** -- from the
   original 4/19 present-and-passing.

   **The 8 remaining fails, with real per-stratum `n_treated_in_stratum` counts** (from the
   synthetic run's own diagnostics CSV):
   - `2017,65-69` (nt=1), `2016,65-69` (nt=1), `2015,65-69` (nt=1), `2014,70-74` (nt=1):
     each stratum's *entire* treated population at 0.01 scale is a single person. Whether
     that one person's propensity score lands inside or outside the real range's floor is
     close to a coin flip that no per-band scalar can fully control -- pushing sharpness
     higher lowers the *probability* of landing below the real floor but cannot guarantee
     it for one specific draw, and pushing it too far (tried `65-69: 5.0` and `3.0` in
     rounds 4/7) instead collapses `2017`'s *share* to near-zero by pulling that one person
     so far into the tail that they stop overlapping the CONTROL pool at all. This is an
     inherent small-N limit of testing a stratum whose real `n_treated` (~130-340 people,
     see `export_20260911/20pct/260909/matching_edge_preflight_not_yet_divorced_lag1.csv`)
     rounds to 1 person at 1% scale, not a miscalibration.
   - `2012,60-64,sex2` (nt=3), `2014,60-64` (nt=5), `2015,60-64` (nt=4): same small-N effect,
     one order of magnitude less extreme (3-5 people, not 1) -- still few enough that which
     *specific* people get selected dominates the resulting share far more than the
     sharpness parameter does; the CSV's own `2012,60-64,sex1` (nt=4, PASS at 6.7pp) and
     `2013,60-64` (nt=6, PASS at 11.1pp) show the same sharpness can land inside tolerance
     for a same-sized stratum -- it is genuinely a per-draw coin flip at this n, not a
     one-directional bias.
   - `2014,50-54` (nt=14): the one fail that is NOT small-N (14 is a reasonable sample).
     Root cause, confirmed by checking `real_rows` processing order in the real CSV:
     `50-54,sex1,rehab0` is claimed from the SAME overlapping birth-year pool across all 7
     years (2012's 50-54 band = birth years 1958-1962; 2014's = 1960-1964; a 60% overlap),
     processed in file order 2012 (order_idx 11) -> 2013 (54) -> **2014 (99)** -> 2015 ->
     2016 -> 2017 -> 2018. By the time 2014 is processed, 2012 and 2013 have already claimed
     ~20 and ~19 people (at 0.01 scale) from that same overlapping pool, preferentially
     taking the most extreme-z candidates first (the selection is z-weighted). 2014 is left
     with a pool skewed toward whatever's left of the overlap years plus the still-fresh
     1963-1964 cohort, weakening the *effective* separation for 2014 specifically even
     though its nominal sharpness is identical to 2012/2013's. Tried compensating by moving
     `50-54` to both `6.5` and `8.5` (rounds 7/8): both made 2014 *worse* (26.9%, 28.6% vs
     round 6's 22.9%) while also breaking 2012 or 2013, confirming this is a year-ordering/
     pool-depletion effect intrinsic to the quota-based-without-replacement design across
     years sharing one band, not a wrong scalar value -- fixing it properly would need a
     per-(band,year) sharpness schedule that compensates for how many years of that band
     have already been claimed, which is a larger design change than this recalibration
     task's scope.

   **Why this is acceptable to ship rather than iterate further**: every one of the 8
   remaining fails has a specific, checked, non-hand-wavy explanation above (7 are literally
   n=1-5 draws; the 8th is a named, verified mechanism, not a mystery). Continued iteration
   demonstrably does not help and can make things worse (rounds 4, 7, 8 each traded one
   stratum's improvement for another's regression at unrelated strata). The important
   structural finding -- that this generator's covariates can, when correctly tuned,
   reproduce the real data's actual admissible-share PATTERN (sparse at 45-54, intermediate
   at 60-64, near-total at 65-74) rather than bunching everything near-total (the Gate 2
   synthetic-data failure mode this whole check exists to catch) -- is demonstrated: 12/20
   strata now match within tolerance, up from 4/19, and the remaining gaps are small-sample
   artifacts of testing a age-specific quota of 1-14 people at a 1% scale, not evidence the
   underlying mechanism is broken. At larger scales (0.1, 1.0) the same `n_treated`
   quantities grow 10x/100x, which should shrink this quantization noise substantially (a
   nt=1 cell at 1% scale is a nt=10 cell at 10% scale) -- **this should be re-checked with
   `compare_preflight.py` once a larger scale is actually run**, per the original build
   prompt's own scale ladder; it is not re-verified here since 0.01 is as far as this
   session's local testing goes.

8. **The recalibrated sharpness broke `bash scripts/run_stage.sh all 0.001` -- a real
   regression, caught by re-running the mandatory regression check rather than assuming
   the 0.01 fix was safe.** First failure: `RuntimeError: All sklearn logistic fitting
   routes failed: This solver needs samples of at least 2 classes in the data, but the data
   contains only one class: 0` inside `fit_discrete_time_model` for the `msk_dropout_
   sensitivity` analysis's `msk_event` outcome (`_unpenalized_logistic_regression`,
   `psm_260915.py:5249`) -- confirmed by reading the actual pair-censored followup parquet
   (574 rows, `msk_event` literally all zero). Root cause, isolated by bisecting which
   changed band was responsible (reproducible in ~15-30s per test since this crash happens
   right after matching, long before the 17-minute full run): raising `50-54`'s sharpness
   from 3.0 to 7.0 changed exactly which ~64 people get selected as treated across all
   bands at this 0.001-scale quota, and that specific new set happened to have zero MSK
   events in this narrow follow-up window (MSK-event timing is drawn independently of `z`/
   sharpness -- rehab-year assignment and rehab-code choice don't depend on either -- so
   this is a real small-sample composition risk, not a bias sharpness introduces on
   purpose). Lowering `50-54` to 6.0 cleared this specific crash (confirmed with a fast,
   ~90-second partial run past the crash point) while leaving 0.01's pass count effectively
   unchanged (still ~12/19-20, just a different specific stratum trades pass for fail --
   consistent with the already-documented year-ordering pool-depletion mechanism).

   A full, un-killed `bash scripts/run_stage.sh all 0.001` with that fix still failed --
   same error class, this time in `_run_secondary_specification_from_panel`
   (`psm_260915.py:7872`, one of the OTHER two specs' outcome models, not the one that
   crashed before). This is not a second isolated bug to hunt down the same way; it is the
   expected shape of the underlying problem: `psm_260915.py` fits many discrete-time models
   (per spec x per outcome x per sensitivity variant) at 0.001 scale's ~64-90 total treated
   people, and *any* change to the exact random draw sequence has a real chance of hitting
   *one of them* with a degenerate all-one-class outcome, purely from small-sample
   composition -- fixing one specific crash site by nudging one parameter does not bound
   how many more exist, and chasing each one individually is not a productive use of
   further iteration.

   **Fixed structurally instead of chasing crash sites**: `compare_preflight.py` and
   `LOCAL_TEST_REPORT.md` (0.001 section) already documented 0.001 scale as "not meaningful"
   for this calibration check (only 6/20 real strata have any synthetic counterpart at all,
   below the script's own "at least half" threshold) -- there was never anything to gain
   from applying the sharper, 0.01-calibrated values at 0.001 scale, only a real,
   demonstrated robustness cost. Made `AGE_BAND_SHARPNESS` scale-dependent:
   `DEFAULT_AGE_BAND_SHARPNESS` (the original, gentler values -- proven crash-free at 0.001
   across multiple full runs in this bundle's history) is used below `--fraction 0.01`;
   `CALIBRATED_AGE_BAND_SHARPNESS` (this session's recalibrated values) is used at
   `--fraction >= 0.01`, where the check is actually meaningful and where these values were
   actually verified against real `compare_preflight.py` output. `generation_manifest.json`
   now records whichever dict was actually used (`age_band_sharpness_used`), so this is
   auditable per run, not just asserted.

   Re-ran `bash scripts/run_stage.sh all 0.001` a third time with this structural fix; see
   the timestamped result below (not asserted in advance of actually running it).

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

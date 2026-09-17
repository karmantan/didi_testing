#!/usr/bin/env python3
"""scripts/generate_raw.py --fraction F --seed S --shards N --output DIR

Streams a calibrated synthetic raw dataset to DIR/raw_<i>.parquet (N shards), scaled to
fraction F of the real 20%% sample (211,593,776 raw rows at F=1.0). Every quota traces to
calibration_20pct.json / the bundled export_20260911/20pct/ files (see BUILD_LOG.md).

Two-pass design, deterministic for a given (seed, fraction):
  PASS 1 (in-memory, O(n_people) compact numpy arrays): draws each person's fixed
    attributes (birth year, sex, prior-any-rehab flag, latent economic type z, state,
    occupation) and runs quota-based, z-weighted-without-replacement treated (divorce)
    selection against the REAL matching_edge_preflight_not_yet_divorced_lag1.csv (bundled
    at export_20260911/20pct/260909/), so the synthetic treated/control population lands in
    the same (year, age_band, sex, prior-rehab) strata, at the same relative sizes, as the
    real 20%% data -- this is what lets scripts/compare_preflight.py check score-spread
    calibration after a run.
  PASS 2 (streaming, one person at a time, <1 GB peak): expands each person's fixed
    attributes into full per-year raw rows and writes them straight to the current shard's
    ParquetWriter, flushing every 200,000 rows (checkpoint_row_group_size) as one row group.
    A person's rows never cross a shard boundary.

Resumable: if raw_<i>.parquet already exists and its SHA-256 matches the hash recorded from
a completed prior run of pass 2 for that shard index (tracked in a .partial_manifest.json
next to the shards), that shard is skipped. Pass 1 is cheap and always reruns in full (it is
what makes resuming safe: person attributes are independently seeded per person, so skipping
a shard's row-writing does not perturb any other person's random draws).
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
import time
from datetime import date
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

BUNDLE_ROOT = Path(__file__).resolve().parent.parent
REAL_PREFLIGHT_CSV = BUNDLE_ROOT / "export_20260911" / "20pct" / "260909" / "matching_edge_preflight_not_yet_divorced_lag1.csv"

# ---------------------------------------------------------------------------
# Calibration targets, scaled linearly by --fraction. See calibration_20pct.json for the
# exact source file each of these traces back to.
# ---------------------------------------------------------------------------
REF_RAW_ROWS = 211_593_776
REF_PEOPLE_TOTAL = 17_559_509          # before conflicting-death exclusion
REF_DUPLICATE_KEYS = 10_345_764
REF_EXCESS_DUP_ROWS = 11_297_317
REF_CONFLICTING_DEATH_PEOPLE = 102
REF_GAPPED_PEOPLE = 329_898
REF_GAP_YEARS = 559_195
REF_DEATH_RECORDED_SHARE = 2_514_450 / 17_559_407
REF_DEATH_AFTER_LAST_ROW_SHARE = 1_915_117 / 2_514_450

CHECKPOINT_ROW_GROUP_SIZE = 200_000
PANEL_YEAR_MIN = 2011
PANEL_YEAR_MAX = 2024
YEAR_START = 2012
YEAR_CAP = 2018

AGE_BANDS = ["<20", "20-24", "25-29", "30-34", "35-39", "40-44", "45-49", "50-54",
             "55-59", "60-64", "65-69", "70-74", "75-79", "80-84", "85-89", "90+"]
AGE_BAND_RANGE = {
    "<20": (16, 19), "20-24": (20, 24), "25-29": (25, 29), "30-34": (30, 34),
    "35-39": (35, 39), "40-44": (40, 44), "45-49": (45, 49), "50-54": (50, 54),
    "55-59": (55, 59), "60-64": (60, 64), "65-69": (65, 69), "70-74": (70, 74),
    "75-79": (75, 79), "80-84": (80, 84), "85-89": (85, 89), "90+": (90, 99),
}
# Calibrated (empirically, per BUILD_LOG.md's iteration log) z-selection "sharpness" per age
# band: how strongly a person's latent economic type z influences whether THEY (vs a random
# same-stratum peer) get selected as the treated (divorced) case in a given year.
#
# calibration_20pct.json's own prose ("near-total admissible share... at ages 60-74") is
# imprecise and was the original source of a real bug here (see BUILD_LOG.md): its own
# top_20_strata_by_candidate_real_edges TABLE (the actual ground truth compare_preflight.py
# uses) shows 65-74 near-total (92.7-99.2%) but 60-64 is a distinct, much lower, intermediate
# regime (31.6-45.7%) -- closer to 55-59 than to 65+. 45-54 is sparse (3.2-6.4%). Trust the
# table over the prose when they disagree (same principle as Hard Rule 7).
#
# Sharpness is scale-dependent (see BUILD_LOG.md): at fractions below ~1%, per-stratum
# treated quotas round to 1-14 people, and pulling that tiny a sample harder toward the
# tails of z (to reproduce realistic admissible-share separation) has a real, repeatedly
# observed chance of producing a degenerate single-class outcome variable somewhere in
# psm_260915.py's many per-spec/per-outcome discrete-time model fits (death, MSK, mediation,
# sensitivity variants) -- a RuntimeError crash, not a calibration nuance. Below ~1% scale,
# compare_preflight.py itself already documents the calibration check as "not meaningful"
# (fewer than half the top-20 real strata have any synthetic counterpart at all), so there
# is nothing to gain from the sharper values there and a real, demonstrated robustness cost.
# CALIBRATED_AGE_BAND_SHARPNESS is used at fraction >= 0.01 (where the check IS meaningful
# and this was calibrated against real compare_preflight.py output); DEFAULT_AGE_BAND_
# SHARPNESS (the original, gentler values) is used below that, preserving the small-scale
# smoke test's proven crash-free behavior.
DEFAULT_AGE_BAND_SHARPNESS = {
    "<20": 0.6, "20-24": 1.0, "25-29": 1.4, "30-34": 1.8, "35-39": 2.2, "40-44": 2.8,
    "45-49": 3.2, "50-54": 3.0, "55-59": 1.8, "60-64": 0.7, "65-69": 0.25, "70-74": 0.15,
    "75-79": 0.12, "80-84": 0.1, "85-89": 0.1, "90+": 0.1,
}
CALIBRATED_AGE_BAND_SHARPNESS = {
    **DEFAULT_AGE_BAND_SHARPNESS,
    "45-49": 8.0, "50-54": 6.0, "60-64": 2.3, "65-69": 2.5, "70-74": 0.8,
}
CALIBRATED_SHARPNESS_MIN_FRACTION = 0.01

REHAB_CODE_WEIGHTS = {20: 0.35, 53: 0.15, 56: 0.15, 30: 0.10, 10: 0.25}
INCAPACITY_CATEGORIES = ["1-3", "3-6", "6-12"]

RAW_SCHEMA = pa.schema([
    ("simple_id", pa.int64()), ("ja", pa.int32()), ("gbja", pa.int32()),
    ("rtwf_jjjj", pa.int32()), ("ge", pa.int32()), ("divorcing", pa.int8()),
    ("fmsd", pa.int8()),
    ("marriage_start", pa.date32()), ("marriage_end", pa.date32()), ("court_decision", pa.date32()),
    ("first_marriage_start", pa.date32()), ("first_marriage_end", pa.date32()),
    ("is_first_marriage", pa.int8()),
    ("entgelt", pa.float64()), ("rtzb", pa.float64()), ("byvlgs", pa.float64()), ("bygmgs", pa.float64()),
    ("whot_bland", pa.string()), ("whot_skt", pa.string()), ("ttsc1_kldb1988", pa.int32()),
    ("seg_start_rsd_1", pa.date32()), ("seg_end_rsd_1", pa.date32()),
    ("rehab_start_1", pa.date32()), ("rehab_end_1", pa.date32()),
    ("mcdggr_succeed_1", pa.int32()), ("mcdams_succeed_1", pa.float64()),
    ("seg_start_rsd_2", pa.date32()), ("seg_end_rsd_2", pa.date32()),
    ("rehab_start_2", pa.date32()), ("rehab_end_2", pa.date32()),
    ("mcdggr_succeed_2", pa.int32()), ("mcdams_succeed_2", pa.float64()),
    ("application_date_fail", pa.date32()), ("decision_date_fail", pa.date32()),
    ("application_date_withdrawn", pa.date32()), ("decision_date_withdrawn", pa.date32()),
    ("application_date_forward", pa.date32()), ("decision_date_forward", pa.date32()),
    ("mcaiufzt_succeed_1", pa.string()), ("mcaiufzt_succeed_2", pa.string()),
])
COLUMN_NAMES = [f.name for f in RAW_SCHEMA]


def age_band_of(age: int) -> str:
    if age < 20:
        return "<20"
    if age >= 90:
        return "90+"
    for band, (lo, hi) in AGE_BAND_RANGE.items():
        if band in ("<20", "90+"):
            continue
        if lo <= age <= hi:
            return band
    return "90+"


def load_real_preflight_rows() -> list[dict]:
    if not REAL_PREFLIGHT_CSV.exists():
        print(f"ERROR: real preflight CSV not found at {REAL_PREFLIGHT_CSV}. "
              "This is bundled under export_20260911/20pct/260909/ -- did the bundle copy step run?", file=sys.stderr)
        raise SystemExit(1)
    with open(REAL_PREFLIGHT_CSV, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    out = []
    for r in rows:
        stratum = json.loads(r["exact_stratum"])
        out.append({
            "t0": int(r["t0"]),
            "age_band": stratum["lag1_age_band"],
            "rehab": stratum["lag1_ever_rehab_to_date"],
            "sex": stratum["lag1_ge_cat"],
            "n_treated": int(r["n_treated_in_stratum"]),
            "n_controls": int(r["n_controls_in_stratum"]),
        })
    return out


def age_band_population_weights(real_rows: list[dict]) -> dict:
    totals = {b: 0 for b in AGE_BANDS}
    for r in real_rows:
        totals[r["age_band"]] += r["n_treated"] + r["n_controls"]
    grand_total = sum(totals.values()) or 1
    return {b: totals[b] / grand_total for b in AGE_BANDS}


def rehab1_share_by_band_sex(real_rows: list[dict]) -> dict:
    """For each (age_band, sex), share of that (band,sex) population expected to already
    have any prior rehab (lag1_ever_rehab_to_date==1) -- used to draw each person's
    prior_rehab_baseline flag so the rehab=0 vs rehab=1 stratum split matches real data."""
    denom = {}
    numer = {}
    for r in real_rows:
        key = (r["age_band"], r["sex"])
        pool = r["n_treated"] + r["n_controls"]
        denom[key] = denom.get(key, 0) + pool
        if r["rehab"] == "1":
            numer[key] = numer.get(key, 0) + pool
    shares = {}
    for key, d in denom.items():
        shares[key] = (numer.get(key, 0) / d) if d else 0.05
    return shares


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fraction", required=True, type=float)
    parser.add_argument("--seed", required=True, type=int)
    parser.add_argument("--shards", required=True, type=int)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    fraction = args.fraction
    seed = args.seed
    n_shards = args.shards
    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    t_start = time.time()
    real_rows = load_real_preflight_rows()
    band_weights = age_band_population_weights(real_rows)
    rehab1_share = rehab1_share_by_band_sex(real_rows)

    n_people = max(1, round(REF_PEOPLE_TOTAL * fraction))
    n_conflicting_death = round(REF_CONFLICTING_DEATH_PEOPLE * fraction)
    n_gapped = round(REF_GAPPED_PEOPLE * fraction)
    n_duplicate_keys_target = round(REF_DUPLICATE_KEYS * fraction)

    print(f"=== generate_raw.py: fraction={fraction} seed={seed} shards={n_shards} ===")
    print(f"Target people: {n_people:,}  (scaled from {REF_PEOPLE_TOTAL:,} real people)")

    # ------------------------------------------------------------------
    # PASS 1: person attributes (compact numpy arrays, O(n_people) memory)
    # ------------------------------------------------------------------
    rng_master = np.random.default_rng(seed)
    band_choices = np.array(AGE_BANDS)
    band_probs = np.array([band_weights[b] for b in AGE_BANDS])
    band_probs = band_probs / band_probs.sum()
    person_band = rng_master.choice(band_choices, size=n_people, p=band_probs)
    person_age_2012 = np.empty(n_people, dtype=np.int16)
    for i, band in enumerate(person_band):
        lo, hi = AGE_BAND_RANGE[band]
        person_age_2012[i] = rng_master.integers(lo, hi + 1)
    person_birth_year = (2012 - person_age_2012.astype(np.int32)).astype(np.int32)
    person_sex = rng_master.integers(1, 3, size=n_people).astype(np.int8)  # 1 or 2
    person_z = rng_master.standard_normal(size=n_people).astype(np.float32)

    person_any_rehab_baseline = np.zeros(n_people, dtype=np.int8)
    for i in range(n_people):
        key = (str(person_band[i]), str(person_sex[i]))
        share = rehab1_share.get(key, 0.05)
        person_any_rehab_baseline[i] = 1 if rng_master.random() < share else 0

    person_state = rng_master.integers(1, 17, size=n_people).astype(np.int8)
    occ_bucket = np.clip(((person_z + 3.0) / 6.0 * 8).astype(np.int32), 0, 7)
    person_occupation = (1000 + occ_bucket * 100 + rng_master.integers(0, 99, size=n_people)).astype(np.int32)

    person_death_flag = rng_master.random(size=n_people) < REF_DEATH_RECORDED_SHARE
    person_death_after_last_row = rng_master.random(size=n_people) < REF_DEATH_AFTER_LAST_ROW_SHARE

    person_gap_flag = np.zeros(n_people, dtype=bool)
    gap_idx = rng_master.choice(n_people, size=min(n_gapped, n_people), replace=False) if n_gapped > 0 else np.array([], dtype=int)
    person_gap_flag[gap_idx] = True

    # remarriage-corruption: a small fraction of eventually-treated people whose divorce row
    # will NOT satisfy marriage_start == first_marriage_start (exercises the real "restrict
    # to marriage spell with marriage_start equal to first_marriage_start" funnel step).
    person_remarriage_corrupt = rng_master.random(size=n_people) < 0.01
    # small injected-exclusion flags, applied only to people actually selected treated below
    person_inject_msk_in_t0 = rng_master.random(size=n_people) < 0.015
    person_inject_no_t0_minus_1 = rng_master.random(size=n_people) < 0.01
    person_inject_dead_at_t0 = rng_master.random(size=n_people) < 0.001

    # --- quota-based, z-weighted-without-replacement treated selection ---
    age_band_sharpness = (
        CALIBRATED_AGE_BAND_SHARPNESS if fraction >= CALIBRATED_SHARPNESS_MIN_FRACTION
        else DEFAULT_AGE_BAND_SHARPNESS
    )
    person_treated_year = np.zeros(n_people, dtype=np.int16)  # 0 = never treated
    person_used = np.zeros(n_people, dtype=bool)
    quota_notes = []
    for real_row in real_rows:
        t0 = real_row["t0"]
        band = real_row["age_band"]
        sex = real_row["sex"]
        rehab = real_row["rehab"]
        target_n = round(real_row["n_treated"] * fraction)
        if target_n <= 0:
            continue
        age_at_t0 = t0 - person_birth_year
        lo, hi = AGE_BAND_RANGE[band]
        if band == "<20":
            band_mask = age_at_t0 < 20
        elif band == "90+":
            band_mask = age_at_t0 >= 90
        else:
            band_mask = (age_at_t0 >= lo) & (age_at_t0 <= hi)
        rehab_mask = (person_any_rehab_baseline == (1 if rehab == "1" else 0))
        sex_mask = (person_sex == int(sex))
        eligible_mask = band_mask & rehab_mask & sex_mask & (~person_used)
        candidate_idx = np.nonzero(eligible_mask)[0]
        if candidate_idx.size == 0:
            continue
        take_n = min(target_n, candidate_idx.size)
        sharpness = age_band_sharpness.get(band, 1.0)
        z_candidates = person_z[candidate_idx]
        # Each stratum draws its Gumbel noise from its OWN independently-seeded RNG (derived
        # from seed/t0/band/sex/rehab), not from the single advancing rng_master stream used
        # elsewhere in this function. Found during AGE_BAND_SHARPNESS calibration (BUILD_LOG.md):
        # with a shared, sequentially-advancing rng_master, changing one stratum's selection
        # (e.g. retuning 60-64's sharpness) changes how many random draws that stratum
        # consumes, which shifts the RNG's position for every stratum processed after it in
        # real_rows' file order -- so retuning band X silently perturbed unrelated band Y's
        # results too, purely from RNG-position drift (not from any real shared-person
        # constraint; genuine overlap, where the same birth cohort ages from one band into
        # another across 2012-2018 and is legitimately claimed by an earlier year's
        # selection, still applies and is unaffected by this change). This still reproduces
        # deterministically for a given seed, but a band's own noise draws are now stable
        # under changes to any *other* band's sharpness.
        stratum_seed_material = f"{seed}|{t0}|{band}|{sex}|{rehab}".encode("utf-8")
        stratum_seed = int(hashlib.sha256(stratum_seed_material).hexdigest()[:8], 16)
        stratum_rng = np.random.default_rng(stratum_seed)
        gumbel_noise = stratum_rng.gumbel(size=candidate_idx.size)
        keys = sharpness * z_candidates + gumbel_noise
        top_positions = np.argpartition(-keys, take_n - 1)[:take_n]
        selected = candidate_idx[top_positions]
        person_treated_year[selected] = t0
        person_used[selected] = True
        if take_n < target_n:
            quota_notes.append(f"t0={t0} band={band} sex={sex} rehab={rehab}: wanted {target_n}, only {take_n} eligible candidates available")

    n_treated_total = int((person_treated_year > 0).sum())
    print(f"Treated (divorce) events assigned: {n_treated_total:,} across years {YEAR_START}-{YEAR_CAP}")
    if quota_notes:
        print(f"NOTE: {len(quota_notes)} (year,stratum) quota cells were short on eligible candidates at this scale (expected at very small fractions):")
        for note in quota_notes[:10]:
            print(f"  - {note}")
        if len(quota_notes) > 10:
            print(f"  ... and {len(quota_notes) - 10} more")

    # ------------------------------------------------------------------
    # PASS 2: expand to per-year rows, streamed to shards
    # ------------------------------------------------------------------
    people_per_shard = -(-n_people // n_shards)
    partial_manifest_path = out_dir / ".partial_manifest.json"
    partial_manifest = json.loads(partial_manifest_path.read_text(encoding="utf-8")) if partial_manifest_path.exists() else {}

    shard_infos = []
    total_rows_written = 0
    divorcing_by_year = {y: 0 for y in range(2012, 2019)}
    n_dup_keys_written = 0
    n_conflicting_death_written = 0
    n_gapped_written = 0

    duplicate_target_indices = set()
    if n_duplicate_keys_target > 0:
        chosen = rng_master.choice(n_people, size=min(n_duplicate_keys_target, n_people), replace=False)
        duplicate_target_indices = set(int(x) for x in chosen)
    conflicting_death_indices = set()
    if n_conflicting_death > 0:
        candidates = np.nonzero(person_death_flag)[0]
        if candidates.size > 0:
            chosen = rng_master.choice(candidates, size=min(n_conflicting_death, candidates.size), replace=False)
            conflicting_death_indices = set(int(x) for x in chosen)

    for shard_idx in range(n_shards):
        shard_name = f"raw_{shard_idx:03d}.parquet"
        shard_path = out_dir / shard_name
        start_person = shard_idx * people_per_shard
        end_person = min(n_people, start_person + people_per_shard)
        if start_person >= end_person and n_people > 0:
            continue

        prior = partial_manifest.get(shard_name)
        if prior and shard_path.exists():
            actual_hash = _sha256(shard_path)
            if actual_hash == prior.get("sha256"):
                print(f"[{shard_idx+1}/{n_shards}] {shard_name}: already complete (hash matches), skipping.")
                shard_infos.append(prior)
                total_rows_written += prior["n_rows"]
                divorcing_by_year_prior = prior.get("divorcing_by_year", {})
                for y_str, c in divorcing_by_year_prior.items():
                    divorcing_by_year[int(y_str)] = divorcing_by_year.get(int(y_str), 0) + c
                n_dup_keys_written += prior.get("n_duplicate_keys", 0)
                n_conflicting_death_written += prior.get("n_conflicting_death", 0)
                n_gapped_written += prior.get("n_gapped_people", 0)
                continue

        t_shard_start = time.time()
        writer = pq.ParquetWriter(shard_path, RAW_SCHEMA)
        buffers = {name: [] for name in COLUMN_NAMES}
        shard_rows = 0
        shard_divorcing_by_year = {y: 0 for y in range(2012, 2019)}
        shard_dup_keys = 0
        shard_conflicting_death = 0
        shard_gapped_people = 0

        def flush():
            nonlocal buffers
            if not buffers["simple_id"]:
                return
            arrays = []
            for field in RAW_SCHEMA:
                arrays.append(pa.array(buffers[field.name], type=field.type))
            table = pa.Table.from_arrays(arrays, schema=RAW_SCHEMA)
            writer.write_table(table, row_group_size=len(buffers["simple_id"]))
            for name in COLUMN_NAMES:
                buffers[name] = []

        for person_idx in range(start_person, end_person):
            person_seed = [seed, int(person_idx)]
            prng = np.random.default_rng(person_seed)
            rows, gap_applied = _generate_person_rows(
                person_idx=person_idx,
                birth_year=int(person_birth_year[person_idx]),
                sex=int(person_sex[person_idx]),
                z=float(person_z[person_idx]),
                any_rehab_baseline=bool(person_any_rehab_baseline[person_idx]),
                state=int(person_state[person_idx]),
                occupation=int(person_occupation[person_idx]),
                treated_year=int(person_treated_year[person_idx]) or None,
                death_flag=bool(person_death_flag[person_idx]),
                death_after_last_row=bool(person_death_after_last_row[person_idx]),
                gap_flag=bool(person_gap_flag[person_idx]),
                remarriage_corrupt=bool(person_remarriage_corrupt[person_idx]),
                inject_msk_in_t0=bool(person_inject_msk_in_t0[person_idx]),
                inject_no_t0_minus_1=bool(person_inject_no_t0_minus_1[person_idx]),
                inject_dead_at_t0=bool(person_inject_dead_at_t0[person_idx]),
                prng=prng,
            )
            if gap_applied:
                shard_gapped_people += 1
            if person_idx in duplicate_target_indices and rows:
                dup_row = dict(rows[prng.integers(0, len(rows))])
                # least-missing-row resolution rule: make the duplicate LESS complete so the
                # real resolution rule ("keep the row with fewest nulls") has a well-defined
                # unique winner, matching the real data's own tie-break behaviour.
                dup_row["byvlgs"] = None
                dup_row["bygmgs"] = None
                rows.append(dup_row)
                shard_dup_keys += 1
            if person_idx in conflicting_death_indices and len(rows) >= 2:
                alt_year = rows[0]["rtwf_jjjj"]
                rows[-1]["rtwf_jjjj"] = (alt_year or 2020) + 1
                shard_conflicting_death += 1

            for row in rows:
                for name in COLUMN_NAMES:
                    buffers[name].append(row[name])
                if row["divorcing"] == 1 and row["ja"] in shard_divorcing_by_year:
                    shard_divorcing_by_year[row["ja"]] += 1
            shard_rows += len(rows)
            if len(buffers["simple_id"]) >= CHECKPOINT_ROW_GROUP_SIZE:
                flush()

        flush()
        writer.close()
        shard_hash = _sha256(shard_path)
        elapsed = time.time() - t_shard_start
        info = {
            "filename": shard_name, "n_rows": shard_rows, "sha256": shard_hash,
            "start_person": start_person, "end_person": end_person,
            "divorcing_by_year": {str(y): c for y, c in shard_divorcing_by_year.items()},
            "n_duplicate_keys": shard_dup_keys, "n_conflicting_death": shard_conflicting_death,
            "n_gapped_people": shard_gapped_people,
        }
        shard_infos.append(info)
        partial_manifest[shard_name] = info
        partial_manifest_path.write_text(json.dumps(partial_manifest, indent=2), encoding="utf-8")
        total_rows_written += shard_rows
        for y, c in shard_divorcing_by_year.items():
            divorcing_by_year[y] += c
        n_dup_keys_written += shard_dup_keys
        n_conflicting_death_written += shard_conflicting_death
        n_gapped_written += shard_gapped_people

        total_elapsed = time.time() - t_start
        avg_per_shard = total_elapsed / (shard_idx + 1)
        remaining = avg_per_shard * (n_shards - shard_idx - 1)
        print(f"[{shard_idx+1}/{n_shards}] {shard_name}: {shard_rows:,} rows in {elapsed:.1f}s "
              f"(total {total_rows_written:,} rows, elapsed {total_elapsed:.1f}s, ETA {remaining:.1f}s)")

    manifest = {
        "fraction": fraction, "seed": seed, "shards": shard_infos, "n_shards": n_shards,
        "target_row_count": total_rows_written,
        "target_people": n_people,
        "target_duplicate_keys": n_dup_keys_written,
        "target_conflicting_death_people": n_conflicting_death_written,
        "target_gapped_people": n_gapped_written,
        "target_treated_by_year": {str(y): int(c) for y, c in divorcing_by_year.items()},
        "n_treated_people_selected": n_treated_total,
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "age_band_sharpness_used": age_band_sharpness,
        "generator": "scripts/generate_raw.py",
    }
    manifest_path = out_dir / "generation_manifest.json"
    with open(manifest_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(manifest, f, indent=2, sort_keys=True)
        f.write("\n")
    if partial_manifest_path.exists():
        partial_manifest_path.unlink()

    total_elapsed = time.time() - t_start
    print(f"\nDone. {total_rows_written:,} raw rows across {len(shard_infos)} shards in {total_elapsed:.1f}s.")
    print(f"Wrote {manifest_path}")
    return 0


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _generate_person_rows(*, person_idx, birth_year, sex, z, any_rehab_baseline, state,
                           occupation, treated_year, death_flag, death_after_last_row,
                           gap_flag, remarriage_corrupt, inject_msk_in_t0,
                           inject_no_t0_minus_1, inject_dead_at_t0, prng) -> list[dict]:
    simple_id = person_idx + 1

    panel_start_year = PANEL_YEAR_MIN
    panel_end_year = PANEL_YEAR_MAX
    death_year = None
    if death_flag:
        earliest_death = max(panel_start_year + 1, birth_year + 20)
        latest_death = PANEL_YEAR_MAX
        if earliest_death <= latest_death:
            death_year = int(prng.integers(earliest_death, latest_death + 1))
            if death_after_last_row:
                panel_end_year = max(panel_start_year, death_year - int(prng.integers(1, 4)))
            else:
                panel_end_year = death_year

    if treated_year and inject_no_t0_minus_1:
        panel_start_year = treated_year
    if treated_year and inject_dead_at_t0:
        death_year = treated_year
        panel_end_year = treated_year

    panel_start_year = max(panel_start_year, min(panel_end_year, birth_year + 16))
    if panel_start_year > panel_end_year:
        panel_start_year = panel_end_year

    gap_year = None
    if gap_flag and panel_end_year - panel_start_year >= 2:
        gap_year = int(prng.integers(panel_start_year + 1, panel_end_year))

    marriage_age = int(prng.integers(20, 35))
    first_marriage_start_year = max(panel_start_year, birth_year + marriage_age)
    first_marriage_start_year = min(first_marriage_start_year, panel_end_year if panel_end_year > panel_start_year else panel_end_year)
    first_marriage_start = date(first_marriage_start_year, 6, 15)
    first_marriage_end = None
    marriage_start_year = first_marriage_start_year
    marriage_start = first_marriage_start

    if remarriage_corrupt and treated_year:
        first_marriage_end_year = min(treated_year - 1, first_marriage_start_year + int(prng.integers(2, 8)))
        first_marriage_end_year = max(first_marriage_end_year, first_marriage_start_year + 1)
        first_marriage_end = date(min(first_marriage_end_year, PANEL_YEAR_MAX), 3, 1)
        marriage_start_year = min(first_marriage_end_year + int(prng.integers(1, 3)), treated_year)
        marriage_start = date(marriage_start_year, 9, 1)

    marriage_end = None
    court_decision = None
    if treated_year:
        marriage_end = date(treated_year, 7, 1)
        court_decision = date(treated_year, 7, 1)
        if not remarriage_corrupt:
            first_marriage_end = marriage_end

    any_rehab_first_year = None
    if any_rehab_baseline:
        any_rehab_first_year = panel_start_year

    extra_rehab_years = set()
    for y in range(panel_start_year, panel_end_year + 1):
        if prng.random() < 0.01:
            extra_rehab_years.add(y)
    if treated_year and inject_msk_in_t0:
        extra_rehab_years.add(treated_year)

    app_event_years = {}
    for y in range(panel_start_year, panel_end_year + 1):
        if prng.random() < 0.02:
            app_event_years[y] = prng.choice(["fail", "withdrawn", "forward"])

    state_code = f"{state:02d}"
    skt_code = f"{int(prng.integers(1, 6)):02d}"

    rows = []
    for year in range(panel_start_year, panel_end_year + 1):
        if year == gap_year:
            continue
        age = year - birth_year
        if age < 0 or age > 125:
            continue

        divorcing = 1 if (treated_year and year == treated_year) else 0
        if year < marriage_start_year:
            fmsd = 1
        elif treated_year and year >= treated_year:
            fmsd = 3
        else:
            fmsd = 2

        is_rehab_year = (year == any_rehab_first_year) or (year in extra_rehab_years)
        rehab_start_1 = rehab_end_1 = seg_start_1 = seg_end_1 = None
        mcdggr_1 = None
        mcdams_1 = None
        incap_1 = None
        if is_rehab_year:
            codes, weights = zip(*REHAB_CODE_WEIGHTS.items())
            mcdggr_1 = int(prng.choice(codes, p=np.array(weights) / sum(weights)))
            start_day = int(prng.integers(1, 28))
            rehab_start_1 = date(year, int(prng.integers(1, 12)), start_day)
            duration = int(prng.integers(14, 120))
            mcdams_1 = float(duration)
            rehab_end_1 = _add_days(rehab_start_1, duration)
            seg_start_1, seg_end_1 = rehab_start_1, rehab_end_1
            if mcdggr_1 in (20, 53, 56):
                incap_1 = str(prng.choice(INCAPACITY_CATEGORIES))

        rehab_start_2 = rehab_end_2 = seg_start_2 = seg_end_2 = None
        mcdggr_2 = None
        mcdams_2 = None
        incap_2 = None
        if is_rehab_year and prng.random() < 0.05:
            codes, weights = zip(*REHAB_CODE_WEIGHTS.items())
            mcdggr_2 = int(prng.choice(codes, p=np.array(weights) / sum(weights)))
            start_day = int(prng.integers(1, 28))
            rehab_start_2 = date(year, int(prng.integers(1, 12)), start_day)
            duration2 = int(prng.integers(14, 120))
            mcdams_2 = float(duration2)
            rehab_end_2 = _add_days(rehab_start_2, duration2)
            seg_start_2, seg_end_2 = rehab_start_2, rehab_end_2
            if mcdggr_2 in (20, 53, 56):
                incap_2 = str(prng.choice(INCAPACITY_CATEGORIES))

        app_fail_date = app_withdrawn_date = app_forward_date = None
        dec_fail_date = dec_withdrawn_date = dec_forward_date = None
        event = app_event_years.get(year)
        if event == "fail":
            app_fail_date = date(year, int(prng.integers(1, 12)), int(prng.integers(1, 28)))
            dec_fail_date = _add_days(app_fail_date, int(prng.integers(10, 90)))
        elif event == "withdrawn":
            app_withdrawn_date = date(year, int(prng.integers(1, 12)), int(prng.integers(1, 28)))
            dec_withdrawn_date = _add_days(app_withdrawn_date, int(prng.integers(10, 90)))
        elif event == "forward":
            app_forward_date = date(year, int(prng.integers(1, 12)), int(prng.integers(1, 28)))
            dec_forward_date = _add_days(app_forward_date, int(prng.integers(10, 90)))

        retirement_age = 63
        entgelt = None
        rtzb = None
        if age < retirement_age:
            missing_p = 0.06
            if prng.random() >= missing_p:
                base = 20000 + 12000 * z + occupation % 100 * 50
                noise = prng.normal(0, 1500)
                entgelt = max(0.0, float(base + noise))
        else:
            pension_p = min(0.95, 0.15 + 0.10 * (age - retirement_age))
            if prng.random() < pension_p:
                rtzb = max(0.0, float(9000 + 3000 * z + prng.normal(0, 800)))
            if age < 67 and prng.random() >= 0.5:
                base = 15000 + 8000 * z
                entgelt = max(0.0, float(base + prng.normal(0, 1200)))

        byvlgs_missing_p = float(np.clip(0.15 - 0.05 * z, 0.03, 0.5))
        byvlgs = None if prng.random() < byvlgs_missing_p else max(0.0, float(200 + 60 * z + prng.normal(0, 20)))
        bygmgs_missing_p = float(np.clip(0.55 - 0.05 * z, 0.2, 0.8))
        bygmgs = None if prng.random() < bygmgs_missing_p else max(0.0, float(40 + 15 * z + prng.normal(0, 10)))

        rows.append({
            "simple_id": simple_id, "ja": year, "gbja": birth_year,
            "rtwf_jjjj": death_year, "ge": sex, "divorcing": divorcing, "fmsd": fmsd,
            "marriage_start": marriage_start if year >= marriage_start_year else None,
            "marriage_end": marriage_end, "court_decision": court_decision,
            "first_marriage_start": first_marriage_start, "first_marriage_end": first_marriage_end,
            "is_first_marriage": 1 if marriage_start == first_marriage_start else 0,
            "entgelt": entgelt, "rtzb": rtzb, "byvlgs": byvlgs, "bygmgs": bygmgs,
            "whot_bland": state_code, "whot_skt": skt_code, "ttsc1_kldb1988": occupation,
            "seg_start_rsd_1": seg_start_1, "seg_end_rsd_1": seg_end_1,
            "rehab_start_1": rehab_start_1, "rehab_end_1": rehab_end_1,
            "mcdggr_succeed_1": mcdggr_1, "mcdams_succeed_1": mcdams_1,
            "seg_start_rsd_2": seg_start_2, "seg_end_rsd_2": seg_end_2,
            "rehab_start_2": rehab_start_2, "rehab_end_2": rehab_end_2,
            "mcdggr_succeed_2": mcdggr_2, "mcdams_succeed_2": mcdams_2,
            "application_date_fail": app_fail_date, "decision_date_fail": dec_fail_date,
            "application_date_withdrawn": app_withdrawn_date, "decision_date_withdrawn": dec_withdrawn_date,
            "application_date_forward": app_forward_date, "decision_date_forward": dec_forward_date,
            "mcaiufzt_succeed_1": incap_1, "mcaiufzt_succeed_2": incap_2,
        })
    return rows, gap_year is not None


def _add_days(d: date, days: int) -> date:
    from datetime import timedelta
    result = d + timedelta(days=days)
    if result.year > PANEL_YEAR_MAX + 1:
        result = date(PANEL_YEAR_MAX + 1, 12, 31)
    return result


if __name__ == "__main__":
    raise SystemExit(main())

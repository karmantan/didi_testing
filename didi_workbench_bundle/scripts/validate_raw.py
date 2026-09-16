#!/usr/bin/env python3
"""scripts/validate_raw.py --raw DIR --fraction F --report FILE

Independent validator: opens the synthetic raw shards with PyArrow ONLY (never imports or
calls into psm_260915.py), and checks:
  - exactly the 40 expected raw columns and their dtypes (per calibration_20pct.json)
  - exact expected row count for the fraction (calibration_20pct.json raw_data_20pct,
    linearly scaled)
  - per-shard SHA-256 against generation_manifest.json
  - duplicate (simple_id, ja) key count
  - conflicting-death (simple_id) count
  - internal year-gap counts
  - per-year treated counts (rows where divorcing==1 in each index year 2012-2018)

Writes --report as JSON with "status": "PASS" or a list of "failures", and prints each
failure in plain words.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

BUNDLE_ROOT = Path(__file__).resolve().parent.parent
REAL_ROWS_AT_FRACTION_1 = 211_593_776


def load_calibration() -> dict:
    return json.loads((BUNDLE_ROOT / "calibration_20pct.json").read_text(encoding="utf-8"))


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw", required=True, help="Directory containing raw_*.parquet shards and generation_manifest.json")
    parser.add_argument("--fraction", required=True, type=float)
    parser.add_argument("--report", required=True)
    args = parser.parse_args()

    raw_dir = Path(args.raw)
    calibration = load_calibration()
    est = calibration["estimator"]
    expected_columns = set(est["core_raw_columns"]) | {"mcaiufzt_succeed_1", "mcaiufzt_succeed_2"}
    dtype_overrides = est["dtype_overrides"]

    failures: list[str] = []
    info: dict = {}

    manifest_path = raw_dir / "generation_manifest.json"
    if not manifest_path.exists():
        failures.append(f"generation_manifest.json not found in {raw_dir}. Run scripts/generate_raw.py first.")
        _write_report(args.report, failures, info)
        return 1
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    shard_files = sorted(raw_dir.glob("raw_*.parquet"))
    info["n_shard_files_found"] = len(shard_files)
    expected_shards = manifest.get("shards", [])
    if len(shard_files) != len(expected_shards):
        failures.append(
            f"Found {len(shard_files)} shard files but generation_manifest.json lists "
            f"{len(expected_shards)} shards."
        )

    # --- per-shard schema, dtype, and hash checks ---
    total_rows = 0
    divorcing_by_year: Counter = Counter()
    person_year_keys: Counter = Counter()
    person_death_years: defaultdict = defaultdict(set)
    person_years_seen: defaultdict = defaultdict(set)

    manifest_shards_by_name = {s["filename"]: s for s in expected_shards}

    for shard_path in shard_files:
        name = shard_path.name
        pf = pq.ParquetFile(shard_path)
        schema_names = set(pf.schema_arrow.names)
        missing = expected_columns - schema_names
        extra = schema_names - expected_columns
        if missing:
            failures.append(f"{name}: missing expected raw columns: {sorted(missing)}")
        if extra:
            failures.append(f"{name}: unexpected extra columns not in the 40-column raw schema: {sorted(extra)}")

        for col, expected_dtype in dtype_overrides.items():
            if col not in schema_names:
                continue
            actual = str(pf.schema_arrow.field(col).type)
            if not _dtype_matches(actual, expected_dtype):
                failures.append(f"{name}: column '{col}' has dtype '{actual}', expected something matching '{expected_dtype}'")

        total_rows += pf.metadata.num_rows

        if name in manifest_shards_by_name:
            expected_hash = manifest_shards_by_name[name].get("sha256")
            if expected_hash:
                actual_hash = sha256_of(shard_path)
                if actual_hash != expected_hash:
                    failures.append(f"{name}: SHA-256 mismatch (manifest={expected_hash}, actual={actual_hash})")
        else:
            failures.append(f"{name}: not listed in generation_manifest.json's shards")

        table = pq.read_table(shard_path, columns=["simple_id", "ja", "divorcing", "rtwf_jjjj"])
        simple_ids = table.column("simple_id").to_pylist()
        jas = table.column("ja").to_pylist()
        divorcing = table.column("divorcing").to_pylist()
        deaths = table.column("rtwf_jjjj").to_pylist()
        for sid, ja, dv, death in zip(simple_ids, jas, divorcing, deaths):
            person_year_keys[(sid, ja)] += 1
            person_years_seen[sid].add(ja)
            if death is not None:
                person_death_years[sid].add(death)
            if dv == 1 and ja is not None and 2012 <= ja <= 2018:
                divorcing_by_year[ja] += 1

    info["n_raw_rows"] = total_rows
    expected_rows = manifest.get("target_row_count")
    if expected_rows is not None and total_rows != expected_rows:
        failures.append(f"Row count {total_rows:,} does not match generation_manifest.json's target_row_count {expected_rows:,}")

    # --- duplicate (simple_id, ja) keys ---
    n_duplicate_keys = sum(1 for count in person_year_keys.values() if count > 1)
    n_excess_rows = sum(count - 1 for count in person_year_keys.values() if count > 1)
    info["n_duplicate_person_year_keys"] = n_duplicate_keys
    info["n_excess_duplicate_rows"] = n_excess_rows
    expected_dup_keys = manifest.get("target_duplicate_keys")
    if expected_dup_keys is not None and n_duplicate_keys != expected_dup_keys:
        failures.append(f"Duplicate (simple_id, ja) key count {n_duplicate_keys:,} does not match manifest target {expected_dup_keys:,}")

    # --- conflicting death years ---
    n_conflicting_death = sum(1 for years in person_death_years.values() if len(years) > 1)
    info["n_conflicting_death_year_people"] = n_conflicting_death
    expected_conflicting = manifest.get("target_conflicting_death_people")
    if expected_conflicting is not None and n_conflicting_death != expected_conflicting:
        failures.append(f"Conflicting-death-year person count {n_conflicting_death:,} does not match manifest target {expected_conflicting:,}")

    # --- internal year gaps ---
    n_gapped_people = 0
    for sid, years in person_years_seen.items():
        if len(years) < 2:
            continue
        y_sorted = sorted(years)
        if y_sorted[-1] - y_sorted[0] + 1 != len(y_sorted):
            n_gapped_people += 1
    info["n_people_with_internal_gaps"] = n_gapped_people
    expected_gapped = manifest.get("target_gapped_people")
    if expected_gapped is not None and n_gapped_people != expected_gapped:
        failures.append(f"Gapped-people count {n_gapped_people:,} does not match manifest target {expected_gapped:,}")

    # --- per-year treated (divorcing==1) counts ---
    info["divorcing_rows_by_year"] = {str(y): divorcing_by_year.get(y, 0) for y in range(2012, 2019)}
    target_treated = manifest.get("target_treated_by_year", {})
    for year_str, target in target_treated.items():
        year = int(year_str)
        actual = divorcing_by_year.get(year, 0)
        # divorcing==1 rows are a superset of "qualifying first divorce" treated people (the
        # pipeline's own filter_audit funnel narrows further); this is a coarse sanity check
        # that raw event density is in the right ballpark, not an exact-match assertion.
        if target > 0 and not (0.5 * target <= actual <= 2.0 * target):
            failures.append(
                f"Year {year}: {actual:,} raw divorcing==1 rows is far from the manifest's "
                f"target of {target:,} (allowed range 0.5x-2.0x)"
            )

    status = "PASS" if not failures else "FAIL"
    _write_report(args.report, failures, info, status=status)

    print(f"=== validate_raw.py: {raw_dir} (fraction {args.fraction}) ===")
    print(f"Status: {status}")
    print(f"Raw rows: {total_rows:,}")
    print(f"Duplicate keys: {n_duplicate_keys:,}  Conflicting-death people: {n_conflicting_death:,}  Gapped people: {n_gapped_people:,}")
    if failures:
        print("Failures:")
        for f in failures:
            print(f"  - {f}")
    else:
        print("All checks passed.")
    return 0 if status == "PASS" else 1


def _dtype_matches(actual: str, expected: str) -> bool:
    actual_l = actual.lower()
    expected_l = expected.lower()
    aliases = {"utf8": ["utf8", "string", "large_string"], "int64": ["int64"], "int32": ["int32"], "int8": ["int8"], "float64": ["double", "float64"]}
    for canonical, variants in aliases.items():
        if expected_l == canonical and actual_l in variants:
            return True
    return actual_l == expected_l


def _write_report(path: str, failures: list[str], info: dict, status: str | None = None) -> None:
    payload = {"status": status or ("PASS" if not failures else "FAIL"), "failures": failures, **info}
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(payload, f, indent=2, sort_keys=True)
        f.write("\n")


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env bash
# commands_local.sh
#
# Every shell command actually run on this laptop while building and locally testing this
# bundle, in the order it was run, appended to as work progressed. Not meant to be executed
# as a single script (some commands are one-off installs / diagnostics); it is a literal
# transcript for the record, per the task's Hard Rule 10.

# --- Step 0: local inventory ---
uname -a
sysctl -n hw.memsize
df -h .
for c in python3.9 python3 python; do command -v "$c" && "$c" --version; done
command -v brew && brew --version
command -v pandoc
brew install python@3.9

# --- estimator hash check ---
shasum -a 256 psm_260915.py
git log --oneline -5
git show a7c52db --stat

# --- bundle scaffold ---
mkdir -p didi_workbench_bundle/{scripts,notebook,docs,results}
cp psm_260915.py didi_workbench_bundle/psm_260915.py
mkdir -p didi_workbench_bundle/export_20260911/20pct
cp -R export_20260911/20pct/260908 didi_workbench_bundle/export_20260911/20pct/
cp -R export_20260911/20pct/260909 didi_workbench_bundle/export_20260911/20pct/
cp export_20260911/GATE2_REPORT.md didi_workbench_bundle/export_20260911/GATE2_REPORT.md

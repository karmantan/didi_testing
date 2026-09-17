#!/usr/bin/env python3
"""Write results/machine.json describing the machine this bundle is running on.

Cgroup-aware: on Posit Workbench (and most shared Linux hosts) a Jupyter session usually
runs inside a container or Slurm/Kubernetes cgroup, and `free -g` / os.sysconf can report
the PHYSICAL HOST's total memory rather than the session's actual allocation. This script
reads the cgroup limit directly and takes the smaller of (cgroup limit, /proc/meminfo
MemAvailable) as the number that matters, and records which one was used and why.

Runs standalone (no third-party imports) so it can be run even before the venv exists, to
sanity-check a session before spending time on `setup_env.sh`.
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import socket
import sys
from pathlib import Path

BUNDLE_ROOT = Path(__file__).resolve().parent.parent


def _load_settings() -> dict:
    settings = {}
    env_path = BUNDLE_ROOT / "bundle_settings.env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            settings[key.strip()] = value.strip()
    return settings


def _data_root() -> Path:
    settings = _load_settings()
    raw = settings.get("DATA_ROOT", "../didi_data")
    return (BUNDLE_ROOT / raw).resolve()


def _read_int(path: Path):
    try:
        text = path.read_text().strip()
    except OSError:
        return None
    if text == "max":
        return None
    try:
        value = int(text)
    except ValueError:
        return None
    # Absurdly large values (near INT64_MAX) mean "effectively unlimited" on some kernels.
    if value >= (1 << 62):
        return None
    return value


def _cgroup_memory_limit_bytes():
    """Return (limit_bytes_or_None, source_description)."""
    v2_max = Path("/sys/fs/cgroup/memory.max")
    v2_high = Path("/sys/fs/cgroup/memory.high")
    if v2_max.exists():
        limit = _read_int(v2_max)
        if limit is not None:
            return limit, "cgroup v2 memory.max"
        high = _read_int(v2_high) if v2_high.exists() else None
        if high is not None:
            return high, "cgroup v2 memory.high (memory.max was 'max'/unlimited)"
        return None, "cgroup v2 present but memory.max and memory.high are both unlimited"
    v1_limit = Path("/sys/fs/cgroup/memory/memory.limit_in_bytes")
    if v1_limit.exists():
        limit = _read_int(v1_limit)
        if limit is not None:
            return limit, "cgroup v1 memory.limit_in_bytes"
        return None, "cgroup v1 present but memory.limit_in_bytes is unlimited"
    return None, "no cgroup memory file found at any known path"


def _proc_meminfo_available_bytes():
    meminfo = Path("/proc/meminfo")
    if not meminfo.exists():
        return None
    for line in meminfo.read_text().splitlines():
        if line.startswith("MemAvailable:"):
            parts = line.split()
            # value is in kB
            return int(parts[1]) * 1024
    return None


def _non_linux_ram_fallback():
    """Best-effort total-RAM figure for non-Linux platforms (this bundle's real memory gate
    logic is cgroup/proc-based and only meaningful on the actual Linux Workbench session;
    this fallback exists purely so scripts/memory_gate.py has *something* to work with
    during local laptop testing on macOS/Windows)."""
    if platform.system() == "Darwin":
        try:
            import subprocess
            out = subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, timeout=5)
            if out.returncode == 0:
                return int(out.stdout.strip()), "macOS sysctl hw.memsize (local-laptop-only fallback, NOT a cgroup-aware figure)"
        except Exception:
            pass
    return None, None


def _cores():
    try:
        return len(os.sched_getaffinity(0))  # type: ignore[attr-defined]
    except AttributeError:
        return os.cpu_count() or 1


def main() -> int:
    BUNDLE_ROOT.joinpath("results").mkdir(parents=True, exist_ok=True)
    data_root = _data_root()
    data_root.mkdir(parents=True, exist_ok=True)

    cgroup_limit, cgroup_source = _cgroup_memory_limit_bytes()
    mem_available = _proc_meminfo_available_bytes()

    candidates = [(v, s) for v, s in [(cgroup_limit, cgroup_source), (mem_available, "/proc/meminfo MemAvailable")] if v]
    if candidates:
        chosen_bytes, chosen_source = min(candidates, key=lambda pair: pair[0])
    else:
        chosen_bytes, chosen_source = _non_linux_ram_fallback()
        if chosen_bytes is None:
            chosen_source = "no memory signal found (not Linux, or unreadable /proc and /sys)"

    available_ram_gib = round(chosen_bytes / (1024 ** 3), 3) if chosen_bytes else None

    disk = shutil.disk_usage(data_root)
    free_disk_gib = round(disk.free / (1024 ** 3), 3)

    machine = {
        "hostname": socket.gethostname(),
        "platform": platform.platform(),
        "python_executable": sys.executable,
        "python_version": platform.python_version(),
        "cores": _cores(),
        "cores_source": "os.sched_getaffinity(0)" if hasattr(os, "sched_getaffinity") else "os.cpu_count()",
        "cgroup_memory_limit_bytes": cgroup_limit,
        "cgroup_memory_limit_source": cgroup_source,
        "proc_meminfo_available_bytes": mem_available,
        "available_ram_gib": available_ram_gib,
        "available_ram_source": chosen_source,
        "data_root": str(data_root),
        "free_disk_gib_at_data_root": free_disk_gib,
    }

    out_path = BUNDLE_ROOT / "results" / "machine.json"
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(machine, f, indent=2, sort_keys=True)
        f.write("\n")

    print("=== Machine check ===")
    print(f"Host: {machine['hostname']}  ({machine['platform']})")
    print(f"Cores available to this session: {machine['cores']} ({machine['cores_source']})")
    if available_ram_gib is not None:
        print(f"Usable RAM for this session: {available_ram_gib} GiB  (source: {chosen_source})")
        if cgroup_limit and mem_available and cgroup_limit != chosen_bytes:
            print(
                f"  Note: cgroup limit ({round(cgroup_limit / (1024**3), 3)} GiB) and "
                f"/proc/meminfo MemAvailable ({round(mem_available / (1024**3), 3)} GiB) "
                "disagree; the smaller one was used, since either can be the true ceiling."
            )
    else:
        print(
            "WARNING: could not determine usable RAM from either a cgroup limit or "
            "/proc/meminfo. This is expected if you are running this on a non-Linux "
            "machine (e.g. testing on a laptop); on the actual Workbench Linux session "
            "this must resolve to a real number before trusting memory_gate.py."
        )
    print(f"Free disk at DATA_ROOT ({data_root}): {free_disk_gib} GiB")
    print(
        "If 'Usable RAM for this session' is far below the memory profile you selected "
        "when starting this Workbench session, that means the cgroup is capping you below "
        "what you expected -- restart the session with the largest memory profile you are "
        "allowed before proceeding."
    )
    print(f"Wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

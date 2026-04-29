#!/usr/bin/env python3
"""
Cleanup script for autoresearch runs.

Removes:
- All iter_* directories in .autoresearch/artifacts/
- All runs-autoresearch experiment directories
- All stream_* directories in runs/autoresearch/ (stream-specific model, config, artifacts)
- Clears results_memory.json content (keeps JSON structure)
- Clears research_log.md content

Leaves:
- JSON files structure intact
- brainstorm/ directory untouched
- Other .autoresearch files untouched
"""

import json
import os
import shutil
from pathlib import Path

# Find project root and .autoresearch directory
SCRIPT_DIR = Path(__file__).parent
# Handle both locations: tests/ and .autoresearch/tests/
if SCRIPT_DIR.name == "tests":
    AUTORESEARCH_DIR = SCRIPT_DIR.parent
else:
    AUTORESEARCH_DIR = SCRIPT_DIR / ".." / ".." / ".autoresearch"

AUTORESEARCH_DIR = AUTORESEARCH_DIR.resolve()
PROJECT_ROOT = AUTORESEARCH_DIR.parent
ARTIFACTS_DIR = AUTORESEARCH_DIR / "artifacts"
RESULTS_MEMORY_FILE = AUTORESEARCH_DIR / "results_memory.json"
RESEARCH_LOG_FILE = AUTORESEARCH_DIR / "research_log.md"
RUNS_DIR = PROJECT_ROOT / "runs-autoresearch"
STREAMS_DIR = PROJECT_ROOT / "runs" / "autoresearch"


def cleanup_artifacts():
    """Remove all iter_* directories in artifacts."""
    if not ARTIFACTS_DIR.exists():
        print(f"Artifacts directory not found: {ARTIFACTS_DIR}")
        return

    removed_count = 0
    for item in ARTIFACTS_DIR.iterdir():
        if item.is_dir() and item.name.startswith("iter_"):
            shutil.rmtree(item)
            removed_count += 1
            print(f"Removed artifact: {item.name}")

    print(f"Removed {removed_count} artifact directories")


def cleanup_runs():
    """Remove all iter_* directories in runs-autoresearch (recursively), keep the directory."""
    if not RUNS_DIR.exists():
        print(f"Runs directory not found: {RUNS_DIR}")
        return

    removed_count = 0
    # Find all iter_* directories recursively
    for iter_dir in RUNS_DIR.rglob("iter_*"):
        if iter_dir.is_dir():
            shutil.rmtree(iter_dir)
            removed_count += 1
            print(f"Removed run: {iter_dir.relative_to(RUNS_DIR)}")

    print(f"Removed {removed_count} run directories (kept {RUNS_DIR.name}/)")


def cleanup_streams():
    """Remove all stream_* directories in runs/autoresearch/."""
    if not STREAMS_DIR.exists():
        print(f"Streams directory not found: {STREAMS_DIR}")
        return

    removed_count = 0
    for stream_dir in STREAMS_DIR.iterdir():
        if stream_dir.is_dir() and stream_dir.name.startswith("stream_"):
            shutil.rmtree(stream_dir)
            removed_count += 1
            print(f"Removed stream: {stream_dir.name}")

    print(f"Removed {removed_count} stream directories (kept {STREAMS_DIR.name}/)")


def cleanup_results_memory():
    """Clear only experiments field in results_memory.json, keep all else."""
    if not RESULTS_MEMORY_FILE.exists():
        print(f"Results memory file not found: {RESULTS_MEMORY_FILE}")
        return

    with open(RESULTS_MEMORY_FILE, "r") as f:
        data = json.load(f)

    data["experiments"] = []

    with open(RESULTS_MEMORY_FILE, "w") as f:
        json.dump(data, f, indent=2)

    print(f"Cleared experiments field: {RESULTS_MEMORY_FILE}")


def cleanup_research_log():
    """Clear research_log.md content."""
    if not RESEARCH_LOG_FILE.exists():
        print(f"Research log file not found: {RESEARCH_LOG_FILE}")
        return

    with open(RESEARCH_LOG_FILE, "w") as f:
        f.write("")

    print(f"Cleared: {RESEARCH_LOG_FILE}")


def main():
    print("=" * 60)
    print("Starting autoresearch cleanup...")
    print("=" * 60)
    print()

    print("[1/5] Cleaning artifacts...")
    cleanup_artifacts()
    print()

    print("[2/5] Cleaning runs...")
    cleanup_runs()
    print()

    print("[3/5] Cleaning streams...")
    cleanup_streams()
    print()

    print("[4/5] Clearing results memory...")
    cleanup_results_memory()
    print()

    print("[5/5] Clearing research log...")
    cleanup_research_log()
    print()

    print("=" * 60)
    print("Cleanup complete!")
    print("=" * 60)


if __name__ == "__main__":
    main()

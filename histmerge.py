#!/usr/bin/env python3
"""
Merge-sort zsh history snapshots and emit the union.

Discovery
- Finds files via glob: ".zsh_history.*" in CWD and HOME, then filters to
  numeric snapshots matching r"^\.zsh_history\.\d+$". Includes the live
  ".zsh_history" if present. Explicit CLI paths override discovery.

Behavior
- Reads files in chronological order (by epoch in filename; live file by mtime).
- Deduplicates by exact line text across all files (newline stripped).
- Parses EXTENDED_HISTORY lines and sorts the union by timestamp (stable by
  arrival order for equal timestamps).
- Writes the merged union lines to stdout only.
- Prints progress and per-file stats to stderr (raw, unique_in_file,
  newly_contributed, cumulative_union), plus a final union summary. This lets
  you redirect stdout/stderr independently.

Assumptions
- Each line is a single entry (no multiline entries) and follows EXTENDED_HISTORY
  format: ": <epoch>:<duration>;command". Non-matching lines are skipped with a
  note to stderr.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Set, Tuple


DEFAULT_FILES: List[str] = []


SNAP_RE = re.compile(r"^\.zsh_history\.(\d+)$")
EXT_LINE_RE = re.compile(r"^:\s*(\d+)\:(\d+)\;.*")


@dataclass
class FileEntry:
    name: str
    path: Path
    sort_key: Tuple[int, str]  # (epoch-ish, tie-breaker name)


def detect_sort_key(p: Path) -> Tuple[int, str]:
    """Return a numeric key representing chronological order.

    - If name is .zsh_history.<epoch>, use that epoch.
    - If name is .zsh_history (live), use mtime.
    - Else, fallback to mtime or 0.
    """
    m = SNAP_RE.match(p.name)
    if m:
        try:
            return (int(m.group(1)), p.name)
        except ValueError:
            pass
    try:
        st = p.stat()
        mt = int(st.st_mtime)
    except FileNotFoundError:
        mt = 0
    except OSError:
        mt = 0
    return (mt, p.name)


def iter_nonempty_lines(path: Path) -> Iterable[str]:
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.rstrip("\n")
            if line:
                yield line


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description="Merge-sort zsh history snapshots; emit union to stdout; stats to stderr")
    ap.add_argument("files", nargs="*", help="Files to include (overrides glob discovery)")
    args = ap.parse_args(argv)

    home = Path.home()

    if args.files:
        raw_paths = args.files
    else:
        # Discover via glob in CWD and HOME
        from glob import glob as _glob
        cwd_matches = _glob(str(Path.cwd() / ".zsh_history.*"))
        home_matches = _glob(str(home / ".zsh_history.*"))
        candidates = set(cwd_matches) | set(home_matches)
        # Filter to numeric snapshots only
        filtered = [p for p in candidates if SNAP_RE.match(Path(p).name)]
        # Also include live file if present
        live_cwd = Path.cwd() / ".zsh_history"
        live_home = home / ".zsh_history"
        if live_cwd.exists():
            filtered.append(str(live_cwd))
        elif live_home.exists():
            filtered.append(str(live_home))
        raw_paths = sorted(filtered)

    paths: List[Path] = [Path(os.path.expanduser(p)) for p in raw_paths]

    entries: List[FileEntry] = [FileEntry(p.name, p, detect_sort_key(p)) for p in paths]
    # Sort chronologically; stable by name for ties
    entries.sort(key=lambda e: e.sort_key)

    union_seen: Set[str] = set()
    union_records: List[Tuple[int, int, str]] = []  # (timestamp, seq, line)
    seq = 0
    total_raw = 0
    print("Processing order (chronological):", file=sys.stderr)
    for e in entries:
        print(f"- {e.name}", file=sys.stderr)
    print(file=sys.stderr)

    print("Per-file stats:", file=sys.stderr)
    for e in entries:
        if not e.path.exists():
            print(f"{e.name}: MISSING (skipped)", file=sys.stderr)
            continue
        raw_lines = list(iter_nonempty_lines(e.path))
        raw_count = len(raw_lines)
        total_raw += raw_count
        unique_in_file = len(set(raw_lines))

        new_count = 0
        for line in raw_lines:
            if line in union_seen:
                continue
            m = EXT_LINE_RE.match(line)
            if not m:
                print(f"{e.name}: skipped non-extended-history line: {line}", file=sys.stderr)
                continue
            try:
                ts = int(m.group(1))
            except Exception:
                print(f"{e.name}: bad timestamp in line: {line}", file=sys.stderr)
                continue
            union_seen.add(line)
            union_records.append((ts, seq, line))
            seq += 1
            new_count += 1

        print(
            f"{e.name}: raw={raw_count}, unique_in_file={unique_in_file}, "
            f"newly_contributed={new_count}, cumulative_union={len(union_seen)}",
            file=sys.stderr,
        )

    print(file=sys.stderr)
    print("Union summary:", file=sys.stderr)
    files_processed = sum(1 for e in entries if e.path.exists())
    total_unique = len(union_seen)
    print(f"files_processed={files_processed}", file=sys.stderr)
    print(f"total_raw_lines={total_raw}", file=sys.stderr)
    print(f"total_unique_lines={total_unique}", file=sys.stderr)
    if total_raw:
        removed = total_raw - total_unique
        pct = (total_unique / total_raw) * 100.0
        print(f"duplicates_removed={removed}", file=sys.stderr)
        print(f"unique_ratio={pct:.2f}%", file=sys.stderr)

    # Emit merged union sorted by timestamp (stable by arrival order)
    union_records.sort(key=lambda t: (t[0], t[1]))
    out = sys.stdout
    try:
        for _, __, line in union_records:
            out.write(line + "\n")
        out.flush()
    except BrokenPipeError:
        # Downstream consumer closed early (e.g., piped to `head`). Exit cleanly.
        try:
            out.flush()
        except Exception:
            pass
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

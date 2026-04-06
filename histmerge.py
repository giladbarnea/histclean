#!/usr/bin/env uv run
# /// script
# dependencies = [
#     "textual",
#     "rich",
#     "pygments"
# ]
# ///
"""
Merge-sort zsh history snapshots and emit the union.

Discovery
- Uses histclean's shared discovery, which includes:
  - numeric ".zsh_history.*" snapshots in CWD and HOME
  - numeric files in "~/.zsh_history_backups/"
  - the live ".zsh_history" if present
- Explicit CLI paths override discovery.

Safety
- Checks whether the selected history files are already clean before merging.
- If any selected file is dirty, prompts whether to continue anyway, run
  histclean first, or quit.
- If the selected files are clean, prints a success message and proceeds.

Behavior
- Reads files in chronological order from the shared discovery/sort logic.
- Deduplicates by exact line text across all files (newline stripped).
- Parses EXTENDED_HISTORY lines and sorts the union by timestamp (stable by
  arrival order for equal timestamps).
- Writes the merged union lines to stdout only.
- Prints progress and per-file stats to stderr (raw, unique_in_file,
  newly_contributed, cumulative_union), plus a final union summary. This lets
  you redirect stdout/stderr independently.

Assumptions
- Each line is a single entry and follows EXTENDED_HISTORY format:
  ": <epoch>:<duration>;command". If the histories are dirty, the script warns
  before merging because multiline entries would otherwise be truncated.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Iterable

from history_files import discover_history_files
from histclean import HistoryCheckResult
from histclean import clean as clean_histories
from histclean import console, inspect_history_files


EXT_LINE_RE = re.compile(r"^:\s*(\d+)\:(\d+)\;.*")


def iter_nonempty_lines(path: Path) -> Iterable[str]:
    with path.open("r", encoding="utf-8", errors="replace") as file_handle:
        for line in file_handle:
            line = line.rstrip("\n")
            if line:
                yield line


def _print_dirty_results(results: list[HistoryCheckResult]) -> None:
    console.print("[warning]Selected history files are not clean.[/warning]")
    for result in results:
        if result.error:
            console.print(f"[error]- {result.path}: {result.error}[/error]")
            continue
        console.print(
            f"[warning]- {result.path}: {result.flagged_count} pending change(s)[/warning]"
        )


def _prompt_dirty_action() -> str:
    prompt = "Continue anyway, run histclean first, or quit? [c/r/q]: "
    while True:
        print(prompt, file=sys.stderr, end="", flush=True)
        choice = sys.stdin.readline()
        if not choice:
            return "q"
        normalized = choice.strip().lower()
        if normalized in {"c", "r", "q"}:
            return normalized
        print("Please type c, r, or q.", file=sys.stderr)


def ensure_histories_are_clean(paths: list[Path]) -> bool:
    existing_paths = [path for path in paths if path.exists()]
    if not existing_paths:
        console.print("[error]No existing history files were selected.[/error]")
        return False

    while True:
        dirty_results = [
            result for result in inspect_history_files(existing_paths) if not result.is_clean
        ]
        if not dirty_results:
            console.print(
                "[success]Selected history files are clean and can proceed merging.[/success]"
            )
            return True

        _print_dirty_results(dirty_results)
        if not sys.stdin.isatty():
            console.print(
                "[error]Cannot prompt because stdin is not a TTY. Run histclean first or re-run interactively.[/error]"
            )
            return False

        choice = _prompt_dirty_action()
        if choice == "c":
            return True
        if choice == "q":
            return False
        clean_histories([result.path for result in dirty_results])


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Merge-sort zsh history snapshots; emit union to stdout; stats to stderr"
    )
    parser.add_argument("files", nargs="*", help="Files to include (overrides default discovery)")
    args = parser.parse_args(argv)

    paths = discover_history_files(args.files)
    if not paths:
        console.print("[error]No history files found.[/error]")
        return 1
    if not ensure_histories_are_clean(paths):
        return 1

    union_seen: set[str] = set()
    union_records: list[tuple[int, int, str]] = []
    seq = 0
    total_raw = 0

    print("Processing order (chronological):", file=sys.stderr)
    for path in paths:
        print(f"- {path.name}", file=sys.stderr)
    print(file=sys.stderr)

    print("Per-file stats:", file=sys.stderr)
    for path in paths:
        if not path.exists():
            print(f"{path.name}: MISSING (skipped)", file=sys.stderr)
            continue

        raw_lines = list(iter_nonempty_lines(path))
        raw_count = len(raw_lines)
        total_raw += raw_count
        unique_in_file = len(set(raw_lines))

        new_count = 0
        for line in raw_lines:
            if line in union_seen:
                continue
            match = EXT_LINE_RE.match(line)
            if not match:
                print(f"{path.name}: skipped non-extended-history line: {line}", file=sys.stderr)
                continue
            try:
                timestamp = int(match.group(1))
            except ValueError:
                print(f"{path.name}: bad timestamp in line: {line}", file=sys.stderr)
                continue

            union_seen.add(line)
            union_records.append((timestamp, seq, line))
            seq += 1
            new_count += 1

        print(
            f"{path.name}: raw={raw_count}, unique_in_file={unique_in_file}, "
            f"newly_contributed={new_count}, cumulative_union={len(union_seen)}",
            file=sys.stderr,
        )

    print(file=sys.stderr)
    print("Union summary:", file=sys.stderr)
    files_processed = sum(1 for path in paths if path.exists())
    total_unique = len(union_seen)
    print(f"files_processed={files_processed}", file=sys.stderr)
    print(f"total_raw_lines={total_raw}", file=sys.stderr)
    print(f"total_unique_lines={total_unique}", file=sys.stderr)
    if total_raw:
        removed = total_raw - total_unique
        pct = (total_unique / total_raw) * 100.0
        print(f"duplicates_removed={removed}", file=sys.stderr)
        print(f"unique_ratio={pct:.2f}%", file=sys.stderr)

    union_records.sort(key=lambda record: (record[0], record[1]))
    try:
        for _, __, line in union_records:
            sys.stdout.write(line + "\n")
        sys.stdout.flush()
    except BrokenPipeError:
        try:
            sys.stdout.flush()
        except Exception:
            pass
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

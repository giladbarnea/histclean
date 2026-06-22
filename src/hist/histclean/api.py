from __future__ import annotations

import argparse
import sys
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path

from rich.rule import Rule

from ..history_files import discover_history_files
from .analysis import analyze_history_lines, calculate_indices_to_remove
from .core import HistoryCheckResult
from .ui import HistoryCleanApp, _console_print


def read_history_file(file_path: Path) -> list[str] | None:
    """Read a history file and return its lines."""
    try:
        return file_path.read_text(errors="ignore").splitlines()
    except FileNotFoundError:
        _console_print(
            f"[error]Error: History file not found at '{file_path}'[/error]\n"
        )
        return None
    except OSError as error:
        _console_print(f"[error]Error reading file '{file_path}': {error}[/error]\n")
        return None


def backup_and_write_history(
    history_path: Path, cleaned_lines: list[str], original_lines: list[str]
) -> None:
    """Save a backup and write the cleaned history file."""
    timestamp = datetime.now().astimezone().strftime("%Y-%m-%d_%H-%M-%S_%f")
    backup_filename = history_path.parent / f".zsh_hist.clean.{timestamp}"
    try:
        with backup_filename.open("w", encoding="utf-8") as file_handle:
            file_handle.write("\n".join(original_lines) + "\n")
        _console_print(f"Backup saved to [info]{backup_filename}[/info]\n")
    except OSError as error:
        _console_print(
            f"[error]Error writing to backup file {backup_filename}: {error!r}[/error]\n"
        )

    try:
        with history_path.open("w", encoding="utf-8") as file_handle:
            file_handle.write("\n".join(cleaned_lines) + "\n")
        _console_print(f"Cleaned history saved to [success]{history_path}[/success]\n")
    except OSError as error:
        _console_print(
            f"[error]Error writing to history file {history_path}: {error!r}[/error]\n"
        )
        sys.exit(1)


def inspect_history_file(history_path: Path) -> HistoryCheckResult:
    original_lines = read_history_file(history_path)
    if original_lines is None:
        return HistoryCheckResult(
            path=history_path,
            is_clean=False,
            error=f"Could not read '{history_path}'",
        )

    analysis = analyze_history_lines(original_lines)
    return HistoryCheckResult(
        path=history_path,
        is_clean=analysis.is_clean,
        flagged_count=len(analysis.flagged_entries),
    )


def inspect_history_files(paths: Iterable[Path]) -> list[HistoryCheckResult]:
    return [inspect_history_file(path) for path in paths]


def check(paths: Iterable[Path] | None = None, *, verbose: bool = True) -> bool:
    """Return True only when every selected history file is already clean."""
    history_paths = list(paths) if paths is not None else discover_history_files()
    if not history_paths:
        if verbose:
            _console_print("[error]No history files found.[/error]")
        return False

    results = inspect_history_files(history_paths)
    all_clean = True
    for result in results:
        if result.error:
            all_clean = False
            if verbose:
                _console_print(f"[error]{result.error}[/error]")
            continue
        if result.is_clean:
            if verbose:
                _console_print(f"[success]{result.path} is clean.[/success]")
            continue
        all_clean = False
        if verbose:
            _console_print(
                f"[warning]{result.path} is not clean ({result.flagged_count} pending change(s)).[/warning]"
            )

    if verbose:
        if all_clean:
            _console_print("[success]All selected history files are clean.[/success]")
        else:
            _console_print(
                "[warning]One or more selected history files are not clean.[/warning]"
            )

    return all_clean


def clean_history_file(history_file_path: Path) -> bool:
    """Clean one history file and return True only if it is clean afterward."""
    original_lines = read_history_file(history_file_path)
    if original_lines is None:
        return False
    if not [line for line in original_lines if line.strip()]:
        _console_print(
            "[warning]History file is empty, or made of only empty lines. Nothing to clean.[/warning]"
        )
        return True

    analysis = analyze_history_lines(original_lines)
    if analysis.is_clean:
        _console_print(
            "[success]No entries needed cleaning. History file unchanged.[/success]"
        )
        return True

    app = HistoryCleanApp(analysis.flagged_entries)
    approved_flags = app.run() or []

    if not approved_flags:
        _console_print("[warning]No changes applied. History file unchanged.[/warning]")
        return False

    indices_to_remove = calculate_indices_to_remove(
        approved_flags,
        analysis.all_entries,
    )
    final_cleaned_entries = [
        entry
        for index, entry in enumerate(analysis.all_entries)
        if index not in indices_to_remove
    ]

    if len(analysis.all_entries) == len(final_cleaned_entries):
        _console_print(
            "\n[warning]Approval given, but no entries were ultimately removed. History file unchanged.[/warning]"
        )
        return False

    cleaned_lines = [line for entry in final_cleaned_entries for line in entry]
    backup_and_write_history(history_file_path, cleaned_lines, original_lines)

    all_entries_flat = [
        line.encode("utf-8", errors="ignore")
        for entry in analysis.all_entries
        for line in entry
    ]
    final_cleaned_entries_flat = [
        line.encode("utf-8", errors="ignore")
        for entry in final_cleaned_entries
        for line in entry
    ]
    raw_lines_removed = len(all_entries_flat) - len(final_cleaned_entries_flat)
    raw_lines_removed_formatted = (
        f"{raw_lines_removed / len(all_entries_flat) * 100:.2f}%"
    )

    all_entries_bytes = memoryview(b"\n".join(all_entries_flat)).nbytes
    final_cleaned_entries_bytes = memoryview(
        b"\n".join(final_cleaned_entries_flat)
    ).nbytes
    total_bytes_removed = all_entries_bytes - final_cleaned_entries_bytes
    total_bytes_removed_formatted = (
        f"{total_bytes_removed / all_entries_bytes * 100:.2f}%"
    )

    removed_count = len(analysis.all_entries) - len(final_cleaned_entries)
    removed_percentage_formatted = (
        f"{removed_count / len(analysis.all_entries) * 100:.2f}%"
    )
    _console_print(
        f"[success]Cleaned history: removed {removed_count} entries ({removed_percentage_formatted}), {raw_lines_removed} lines ({raw_lines_removed_formatted}), {total_bytes_removed} bytes ({total_bytes_removed_formatted}).[/success]"
    )

    post_clean_analysis = analyze_history_lines(cleaned_lines)
    if post_clean_analysis.is_clean:
        return True

    _console_print(
        "[warning]History still needs cleaning after this pass. Run histclean again or review the remaining flags.[/warning]"
    )
    return False


def clean(paths: Iterable[Path] | None = None) -> bool:
    """Clean all selected history files and return True only if all are clean afterward."""
    history_paths = list(paths) if paths is not None else discover_history_files()
    if not history_paths:
        _console_print("[error]No history files found.[/error]")
        return False

    all_clean = True
    multiple_files = len(history_paths) > 1
    for index, history_path in enumerate(history_paths, start=1):
        if multiple_files:
            _console_print()
            _console_print(
                Rule(
                    f"[bold]History File {index}/{len(history_paths)}: {history_path}[/bold]",
                    style="rule",
                )
            )
        elif index == 1:
            _console_print(Rule(f"[bold]{history_path}[/bold]", style="rule"))

        if not clean_history_file(history_path):
            all_clean = False

    return all_clean


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Clean zsh history files.")
    parser.add_argument(
        "files",
        nargs="*",
        help="Files to inspect or clean. Defaults to discovered history files.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check whether the selected history files are already clean.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Orchestrate history checking and cleaning."""
    args = build_arg_parser().parse_args(sys.argv[1:] if argv is None else argv)
    history_paths = discover_history_files(args.files)
    if args.check:
        return 0 if check(history_paths) else 1
    return 0 if clean(history_paths) else 1

"""
histcompare.py - Visualizer for ZSH history file coverage and gaps.

Analyzes multiple ZSH history files (extended_history format) to visualize their temporal
coverage, overlaps, and gaps.

Key Concepts
------------
1. Sequences & Gaps:
   Unlike simple start/end range checks, this tool fully scans each file to identify
   continuous "sequences" of history. A gap of > 1 day between entries breaks the sequence.
   This reveals significantly more detail, such as "hollow" backup files that span years
   but only contain a few distinct sessions.

2. Time Alignment:
   The tool identifies exact timestamp matches across files (start/end of sequences),
   helping to visualize when backups were taken relative to each other.

3. Visualization Modes:
   - Terminal: Rich-formatted summary table and ASCII timeline (stderr).
   - HTML: Interactive, scrollable web-based timeline with:
     * Discontinuous bars representing actual data sequences.
     * Two-way highlighting: Hovering a file highlights aligned timestamps in other files.
     * Sticky labels and horizontal scrolling for long histories.
     * Click-to-open integration with Cursor/VSCode.

Discovery
---------
By default, uses the same discovery as histmerge/histclean:
  - numeric ".zsh_history.*" snapshots in CWD and HOME
  - numeric files in HOME/.zsh_history_backups/
  - the live ".zsh_history" if present

`.zsh_hist.clean.*` files are only included when passed explicitly on the CLI.

Explicit CLI paths override automatic discovery.

Usage
-----
    uv run histcompare --html timeline.html

Format
------
Expects ZSH EXTENDED_HISTORY format: ": <epoch>:<duration>;command"
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ..histclean import inspect_history_files
from .analysis import analyze_all, discover_files
from .html import output_html
from .terminal import console, output_terminal


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compare time ranges across zsh history backups",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "files",
        nargs="*",
        help="Specific files to analyze (overrides auto-discovery)",
    )
    parser.add_argument(
        "--html",
        metavar="FILE",
        type=Path,
        help="Generate HTML visualization to FILE",
    )
    parser.add_argument(
        "--no-terminal",
        action="store_true",
        help="Suppress terminal output (useful with --html)",
    )
    args = parser.parse_args(argv)

    if args.files:
        paths = [Path(file_path).expanduser().resolve() for file_path in args.files]
    else:
        paths = discover_files()
        if not paths:
            console.print("[red]No history files found[/red]")
            return 1
        console.print(
            f"[dim]Discovered {len(paths)} history files using histmerge-compatible defaults[/dim]"
        )

    result = analyze_all(paths)
    result.dirty_file_count = sum(
        1 for check_result in inspect_history_files(paths) if not check_result.is_clean
    )

    if not args.no_terminal:
        output_terminal(result)

    if args.html:
        output_html(result, args.html)

    return 0


if __name__ == "__main__":
    sys.exit(main())

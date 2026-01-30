#!/usr/bin/env uv run
# /// script
# requires-python = ">=3.11"
# dependencies = ["rich"]
# ///
"""
histcompare.py - Compare time ranges across zsh history backups.

Analyzes multiple zsh history files to visualize their temporal coverage and
overlaps. Useful for understanding backup coverage before recovery operations.

Discovery
---------
By default, discovers history files from:
  - CWD: .zsh_history, .zsh_history.*, .zsh_hist.clean.*
  - HOME: same patterns
  - HOME/.zsh_history_backups/: numeric timestamp-named files

Explicit CLI paths override automatic discovery.

Output Modes
------------
  --terminal (default): Rich-formatted table and ASCII timeline to stderr
  --html FILE:          Generate interactive HTML visualization

Each file is analyzed by reading only its first and last lines to extract
the timestamp range, making this efficient even for very large files.

Format
------
Expects EXTENDED_HISTORY format: ": <epoch>:<duration>;command"
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

# ============================================================================
# CONSTANTS & PATTERNS
# ============================================================================

EXT_LINE_RE = re.compile(r"^:\s*(\d+):\d+;")
SNAP_RE = re.compile(r"^\.zsh_history\.(?:shrinkbackup\.)?(\d+)$")
CLEAN_RE = re.compile(r"^\.zsh_hist\.clean\.\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}$")

console = Console(stderr=True)


# ============================================================================
# DATA STRUCTURES
# ============================================================================


@dataclass
class HistoryFile:
    """Represents a history file with its metadata and time range."""

    path: Path
    name: str
    start_ts: int | None = None
    end_ts: int | None = None
    lines: int = 0
    error: str | None = None

    @property
    def start_date(self) -> datetime | None:
        return datetime.fromtimestamp(self.start_ts) if self.start_ts else None

    @property
    def end_date(self) -> datetime | None:
        return datetime.fromtimestamp(self.end_ts) if self.end_ts else None

    @property
    def duration_days(self) -> int | None:
        if self.start_ts and self.end_ts:
            return max(1, (self.end_ts - self.start_ts) // 86400)
        return None

    @property
    def category(self) -> str:
        """Categorize the file for grouping/coloring."""
        if self.name == ".zsh_history":
            return "main"
        if self.path.parent.name == ".zsh_history_backups":
            return "timestamped"
        if self.name.startswith(".zsh_hist.clean."):
            return "clean"
        if self.name.startswith(".zsh_history."):
            return "snapshot"
        return "other"


@dataclass
class AnalysisResult:
    """Aggregated analysis of all history files."""

    files: list[HistoryFile] = field(default_factory=list)

    @property
    def min_ts(self) -> int | None:
        valid = [f.start_ts for f in self.files if f.start_ts]
        return min(valid) if valid else None

    @property
    def max_ts(self) -> int | None:
        valid = [f.end_ts for f in self.files if f.end_ts]
        return max(valid) if valid else None

    @property
    def time_range(self) -> int | None:
        if self.min_ts and self.max_ts:
            return self.max_ts - self.min_ts
        return None


# ============================================================================
# FILE DISCOVERY
# ============================================================================


def discover_files() -> list[Path]:
    """Find all history-related files in standard locations."""
    found: set[Path] = set()
    home = Path.home()
    cwd = Path.cwd()

    search_dirs = {home, cwd}

    for d in search_dirs:
        # Main history file
        main = d / ".zsh_history"
        if main.exists() and main.is_file():
            found.add(main.resolve())

        # Glob patterns for backups
        for pattern in [".zsh_history.*", ".zsh_hist.clean.*"]:
            for p in d.glob(pattern):
                if p.is_file():
                    found.add(p.resolve())

    # Check .zsh_history_backups directory
    backups_dir = home / ".zsh_history_backups"
    if backups_dir.is_dir():
        for p in backups_dir.iterdir():
            if p.is_file() and p.name.isdigit():
                found.add(p.resolve())

    return sorted(found, key=lambda p: (p.parent.name, p.name))


# ============================================================================
# ANALYSIS
# ============================================================================


def extract_timestamp(line: str) -> int | None:
    """Extract epoch timestamp from an EXTENDED_HISTORY line."""
    m = EXT_LINE_RE.match(line)
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            pass
    return None


def read_first_line(path: Path) -> str | None:
    """Read only the first line of a file."""
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            return f.readline().rstrip("\n")
    except OSError:
        return None


def read_last_line(path: Path) -> str | None:
    """Read only the last line of a file efficiently."""
    try:
        with path.open("rb") as f:
            # Seek to end
            f.seek(0, 2)
            size = f.tell()
            if size == 0:
                return None

            # Read backwards to find last newline
            pos = size - 1
            while pos > 0:
                f.seek(pos)
                char = f.read(1)
                if char == b"\n" and pos < size - 1:
                    break
                pos -= 1

            # Read from there to end
            if pos > 0:
                f.seek(pos + 1)
            else:
                f.seek(0)

            return f.read().decode("utf-8", errors="replace").rstrip("\n")
    except OSError:
        return None


def count_lines(path: Path) -> int:
    """Count lines in file efficiently."""
    try:
        with path.open("rb") as f:
            return sum(1 for _ in f)
    except OSError:
        return 0


def analyze_file(path: Path) -> HistoryFile:
    """Analyze a single history file."""
    hf = HistoryFile(path=path, name=path.name)

    if not path.exists():
        hf.error = "File not found"
        return hf

    first = read_first_line(path)
    last = read_last_line(path)

    if first:
        hf.start_ts = extract_timestamp(first)
    if last:
        hf.end_ts = extract_timestamp(last)

    hf.lines = count_lines(path)

    if not hf.start_ts and not hf.end_ts:
        hf.error = "No valid timestamps found"

    return hf


def analyze_all(paths: Iterable[Path]) -> AnalysisResult:
    """Analyze all given history files."""
    result = AnalysisResult()
    for p in paths:
        result.files.append(analyze_file(p))
    # Sort by start timestamp (files without timestamps go last)
    result.files.sort(key=lambda f: (f.start_ts or float("inf"), f.name))
    return result


# ============================================================================
# TERMINAL OUTPUT
# ============================================================================


def format_ts(ts: int | None) -> str:
    """Format timestamp as readable date."""
    if ts is None:
        return "—"
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")


def format_date_short(ts: int | None) -> str:
    """Format timestamp as short date."""
    if ts is None:
        return "—"
    return datetime.fromtimestamp(ts).strftime("%b %d")


def category_color(cat: str) -> str:
    """Return Rich color for category."""
    return {
        "main": "bold magenta",
        "timestamped": "bold yellow",
        "clean": "cyan",
        "snapshot": "green",
        "other": "white",
    }.get(cat, "white")


def render_table(result: AnalysisResult) -> Table:
    """Render analysis as a Rich table."""
    table = Table(
        title="History File Time Ranges",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold",
    )

    table.add_column("File", style="dim", max_width=45)
    table.add_column("Start", justify="right")
    table.add_column("End", justify="right")
    table.add_column("Days", justify="right")
    table.add_column("Lines", justify="right")

    for hf in result.files:
        color = category_color(hf.category)
        name = Text(hf.name, style=color)

        if hf.error:
            table.add_row(name, Text(hf.error, style="red"), "—", "—", "—")
        else:
            table.add_row(
                name,
                format_ts(hf.start_ts),
                format_ts(hf.end_ts),
                str(hf.duration_days or "—"),
                f"{hf.lines:,}",
            )

    return table


def render_ascii_timeline(result: AnalysisResult, width: int = 60) -> Panel:
    """Render an ASCII timeline visualization."""
    if not result.time_range:
        return Panel("No valid time range to display", title="Timeline")

    min_ts = result.min_ts
    time_range = result.time_range

    lines = []
    for hf in result.files:
        if hf.start_ts is None or hf.end_ts is None:
            continue

        # Calculate positions
        start_pos = int(((hf.start_ts - min_ts) / time_range) * width)
        end_pos = int(((hf.end_ts - min_ts) / time_range) * width)
        bar_width = max(1, end_pos - start_pos)

        # Build the bar
        color = category_color(hf.category)
        prefix = " " * start_pos
        bar = "█" * bar_width

        # Truncate name for display
        name = hf.name[:35].ljust(35)

        line = Text()
        line.append(f"{name} ", style="dim")
        line.append(prefix)
        line.append(bar, style=color)
        lines.append(line)

    # Add date axis
    axis_dates = []
    for i in range(5):
        ts = min_ts + (time_range * i // 4)
        axis_dates.append(format_date_short(ts))

    axis = Text()
    axis.append(" " * 36)  # Align with bars
    spacing = width // 4
    for i, d in enumerate(axis_dates):
        if i == 0:
            axis.append(d, style="dim")
        else:
            pad = spacing - len(axis_dates[i - 1])
            axis.append(" " * pad + d, style="dim")

    lines.append(Text(""))
    lines.append(axis)

    return Panel(
        "\n".join(str(line) for line in lines),
        title="Timeline (oldest → newest)",
        border_style="dim",
    )


def render_summary(result: AnalysisResult) -> Panel:
    """Render summary panel with key findings."""
    # Find main history
    main = next((f for f in result.files if f.category == "main"), None)

    # Find largest backup
    backups = [f for f in result.files if f.category != "main" and f.lines > 0]
    largest = max(backups, key=lambda f: f.lines) if backups else None

    # Find earliest backup start
    earliest = min(
        (f for f in result.files if f.start_ts),
        key=lambda f: f.start_ts,
        default=None,
    )

    lines = []

    if main and earliest and main.start_ts and earliest.start_ts:
        gap_days = (main.start_ts - earliest.start_ts) // 86400
        if gap_days > 0:
            lines.append(
                Text.assemble(
                    ("⚠️  ", "yellow"),
                    ("Missing history: ", "bold red"),
                    (f"{gap_days} days ", "bold"),
                    (f"({format_date_short(earliest.start_ts)} → {format_date_short(main.start_ts)})", "dim"),
                )
            )

    if largest:
        lines.append(
            Text.assemble(
                ("📦 ", ""),
                ("Largest backup: ", "bold"),
                (f"{largest.name} ", "cyan"),
                (f"({largest.lines:,} lines)", "dim"),
            )
        )

    lines.append(
        Text.assemble(
            ("📊 ", ""),
            ("Total files: ", "bold"),
            (f"{len(result.files)}", ""),
        )
    )

    if result.min_ts and result.max_ts:
        total_days = (result.max_ts - result.min_ts) // 86400
        lines.append(
            Text.assemble(
                ("📅 ", ""),
                ("Coverage: ", "bold"),
                (f"{total_days} days ", ""),
                (f"({format_date_short(result.min_ts)} → {format_date_short(result.max_ts)})", "dim"),
            )
        )

    return Panel(
        "\n".join(str(line) for line in lines),
        title="Summary",
        border_style="green",
    )


def output_terminal(result: AnalysisResult) -> None:
    """Output analysis to terminal with Rich formatting."""
    console.print()
    console.print(render_summary(result))
    console.print()
    console.print(render_table(result))
    console.print()
    console.print(render_ascii_timeline(result))
    console.print()


# ============================================================================
# HTML OUTPUT
# ============================================================================


def generate_html(result: AnalysisResult) -> str:
    """Generate interactive HTML visualization."""
    # Prepare data for JavaScript
    js_data = []
    for hf in result.files:
        if hf.start_ts and hf.end_ts:
            js_data.append(
                f'{{ name: "{hf.name}", path: "{hf.path.resolve()}", start: {hf.start_ts}, end: {hf.end_ts}, '
                f'lines: {hf.lines}, type: "{hf.category}" }}'
            )

    data_js = ",\n            ".join(js_data)

    # Find main history gap info
    main = next((f for f in result.files if f.category == "main"), None)
    earliest = min(
        (f for f in result.files if f.start_ts),
        key=lambda f: f.start_ts,
        default=None,
    )

    gap_html = ""
    if main and earliest and main.start_ts and earliest.start_ts:
        gap_days = (main.start_ts - earliest.start_ts) // 86400
        if gap_days > 0:
            gap_html = f"""
            <p><strong>Main .zsh_history is missing {gap_days} days of history</strong> ({format_date_short(earliest.start_ts)} - {format_date_short(main.start_ts)})</p>
            """

    # Find best recovery candidates
    backups = [f for f in result.files if f.category != "main" and f.lines > 0]
    largest = max(backups, key=lambda f: f.lines) if backups else None

    recovery_html = ""
    if largest:
        recovery_html = f"""
            <p><strong>Best recovery source:</strong> <code>{largest.name}</code> ({largest.lines:,} lines)</p>
        """

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ZSH History Timeline Analysis</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Roboto', sans-serif;
            background: #1a1a1a;
            color: #e0e0e0;
            padding: 20px;
        }}
        .container {{ max-width: 1400px; margin: 0 auto; }}
        h1 {{ font-size: 28px; margin-bottom: 10px; color: #fff; }}
        .summary {{
            background: #2a2a2a;
            padding: 20px;
            border-radius: 8px;
            margin-bottom: 30px;
            border-left: 4px solid #f44336;
        }}
        .summary h2 {{ font-size: 18px; margin-bottom: 10px; color: #f44336; }}
        .summary p {{ margin: 8px 0; line-height: 1.6; }}
        .chart-container {{
            background: #2a2a2a;
            border-radius: 8px;
            padding: 30px;
            overflow-x: auto;
        }}
        .timeline {{ position: relative; min-width: 1200px; }}
        .timeline-row {{
            display: flex;
            align-items: center;
            margin-bottom: 8px;
            min-height: 40px;
        }}
        .file-label {{
            width: 350px;
            font-size: 12px;
            font-family: 'Monaco', 'Menlo', monospace;
            padding-right: 20px;
            flex-shrink: 0;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }}
        .timeline-track {{
            position: relative;
            flex: 1;
            height: 32px;
            background: #1a1a1a;
            border-radius: 4px;
        }}
        .timeline-bar {{
            position: absolute;
            height: 100%;
            border-radius: 4px;
            cursor: pointer;
            transition: all 0.2s;
            display: flex;
            align-items: center;
            padding: 0 8px;
            font-size: 11px;
            font-weight: 500;
            overflow: hidden;
        }}
        .timeline-bar:hover {{
            filter: brightness(1.3);
            z-index: 10;
            transform: scaleY(1.15);
        }}
        .overlay-container {{
            position: absolute;
            top: 0;
            bottom: 0;
            left: 350px;
            right: 0;
            pointer-events: none;
            z-index: 20;
        }}
        .timeline-marker {{
            position: absolute;
            top: 0;
            bottom: 0;
            width: 1px;
            background: rgba(255, 255, 255, 0.1);
            transform: translateX(-50%);
            pointer-events: auto;
            transition: width 0.1s, background 0.1s;
        }}
        .timeline-marker.aligned {{
            background: rgba(0, 255, 0, 0.5);
            width: 1px;
            z-index: 30;
        }}
        .timeline-marker:hover,
        .timeline-marker.active {{
            background: #fff;
            width: 2px;
            z-index: 40;
            box-shadow: 0 0 4px rgba(255,255,255,0.5);
        }}
        .timeline-bar.related {{
            box-shadow: 0 0 15px 3px rgba(255, 255, 255, 0.6);
            filter: brightness(1.4);
            transform: scaleY(1.15);
            border: 1px solid rgba(255, 255, 255, 0.9);
            z-index: 15;
        }}
        .cat-main {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            border: 2px solid #8b9aff;
        }}
        .cat-timestamped {{
            background: linear-gradient(135deg, #ff9a56 0%, #ffcd39 100%);
            border: 2px solid #ffa726;
        }}
        .cat-clean {{
            background: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%);
        }}
        .cat-snapshot {{
            background: linear-gradient(135deg, #43e97b 0%, #38f9d7 100%);
        }}
        .cat-other {{
            background: linear-gradient(135deg, #fa709a 0%, #fee140 100%);
        }}
        .date-axis {{
            display: flex;
            margin-left: 370px;
            margin-top: 10px;
            border-top: 2px solid #444;
            padding-top: 10px;
            position: relative;
        }}
        .date-marker {{
            position: absolute;
            font-size: 11px;
            color: #999;
            white-space: nowrap;
            transform: translateX(-50%);
        }}
        .tooltip {{
            position: fixed;
            background: #333;
            color: #fff;
            padding: 12px 16px;
            border-radius: 6px;
            font-size: 12px;
            font-size: 12px;
            pointer-events: auto;
            z-index: 1000;
            display: none;
            box-shadow: 0 4px 12px rgba(0,0,0,0.5);
            border: 1px solid #555;
            max-width: 400px;
        }}
        .tooltip-visible {{ display: block; }}
        .legend {{
            margin-top: 20px;
            display: flex;
            gap: 20px;
            flex-wrap: wrap;
        }}
        .legend-item {{
            display: flex;
            align-items: center;
            gap: 8px;
            font-size: 12px;
        }}
        .legend-color {{
            width: 24px;
            height: 16px;
            border-radius: 3px;
        }}
        .stats {{
            margin-top: 15px;
            padding-top: 15px;
            border-top: 1px solid #444;
            font-size: 13px;
            color: #aaa;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>🕐 ZSH History Timeline</h1>

        <div class="summary">
            <h2>Analysis Results</h2>
            {gap_html}
            {recovery_html}
            <div class="stats">
                <p>Total files analyzed: {len(result.files)}</p>
            </div>
        </div>

        <div class="chart-container">
            <div class="timeline" id="timeline"></div>
            <div class="date-axis" id="dateAxis"></div>

            <div class="legend">
                <div class="legend-item">
                    <div class="legend-color cat-main"></div>
                    <span>Main .zsh_history</span>
                </div>
                <div class="legend-item">
                    <div class="legend-color cat-timestamped"></div>
                    <span>.zsh_history_backups/</span>
                </div>
                <div class="legend-item">
                    <div class="legend-color cat-clean"></div>
                    <span>.zsh_hist.clean.*</span>
                </div>
                <div class="legend-item">
                    <div class="legend-color cat-snapshot"></div>
                    <span>.zsh_history.* snapshots</span>
                </div>
            </div>
        </div>
    </div>

    <div class="tooltip" id="tooltip"></div>

    <script>
        const data = [
            {data_js}
        ];

        const minTime = Math.min(...data.map(d => d.start));
        const maxTime = Math.max(...data.map(d => d.end));
        const timeRange = maxTime - minTime;

        function formatDate(timestamp) {{
            const date = new Date(timestamp * 1000);
            return date.toLocaleDateString('en-US', {{ month: 'short', day: 'numeric', year: 'numeric' }});
        }}

        function formatDateTime(timestamp) {{
            const date = new Date(timestamp * 1000);
            return date.toLocaleString('en-US', {{
                month: 'short',
                day: 'numeric',
                year: 'numeric',
                hour: '2-digit',
                minute: '2-digit'
            }});
        }}

        function calculatePosition(timestamp) {{
            return ((timestamp - minTime) / timeRange) * 100;
        }}

        const timeline = document.getElementById('timeline');
        const tooltip = document.getElementById('tooltip');
        let hideTimeout;

        tooltip.addEventListener('mouseenter', () => {{
            if (hideTimeout) clearTimeout(hideTimeout);
        }});

        tooltip.addEventListener('mouseleave', () => {{
            tooltip.classList.remove('tooltip-visible');
        }});

        tooltip.addEventListener('mouseleave', () => {{
            tooltip.classList.remove('tooltip-visible');
        }});

        // Create overlay for global markers
        const overlay = document.createElement('div');
        overlay.className = 'overlay-container';
        timeline.appendChild(overlay);

        // Build alignment map for start/end points
        const points = {{}};
        data.forEach(d => {{
            if (!points[d.start]) points[d.start] = [];
            points[d.start].push({{name: d.name, type: '[start]'}});
            
            if (!points[d.end]) points[d.end] = [];
            points[d.end].push({{name: d.name, type: '[end]'}});
        }});

        const sortedData = [...data].sort((a, b) => {{
            if (a.type === 'main') return -1;
            if (b.type === 'main') return 1;
            if (a.type === 'timestamped' && b.type !== 'timestamped') return -1;
            if (b.type === 'timestamped' && a.type !== 'timestamped') return 1;
            return a.start - b.start;
        }});

        sortedData.forEach(item => {{
            const row = document.createElement('div');
            row.className = 'timeline-row';

            const label = document.createElement('div');
            label.className = 'file-label';
            label.textContent = item.name;
            label.title = item.name;

            const track = document.createElement('div');
            track.className = 'timeline-track';

            const bar = document.createElement('div');
            bar.className = `timeline-bar cat-${{item.type}}`;

            const left = calculatePosition(item.start);
            const width = calculatePosition(item.end) - left;

            bar.style.left = `${{left}}%`;
            bar.style.width = `${{width}}%`;
            bar.dataset.start = item.start;
            bar.dataset.end = item.end;

            const durationDays = Math.round((item.end - item.start) / 86400);
            bar.textContent = `${{durationDays}}d`;

            // Click to open in Cursor
            bar.addEventListener('click', (e) => {{
                // Use cursor://file/absolute/path
                window.location.href = `cursor://file${{item.path}}`;
            }});

            // Bar tooltip
            bar.addEventListener('mouseenter', (e) => {{
                if (hideTimeout) clearTimeout(hideTimeout);
                
                // Highlight related bars
                const allBars = document.querySelectorAll('.timeline-bar');
                allBars.forEach(b => {{
                    if (b === bar) return;
                    const bStart = parseInt(b.dataset.start);
                    const bEnd = parseInt(b.dataset.end);
                    if (bStart === item.start || bStart === item.end || bEnd === item.start || bEnd === item.end) {{
                        b.classList.add('related');
                    }}
                }});

                // Highlight related markers
                [item.start, item.end].forEach(ts => {{
                    const marker = document.querySelector(`.timeline-marker[data-ts="${{ts}}"]`);
                    if (marker && marker.classList.contains('aligned')) {{
                        marker.classList.add('active');
                    }}
                }});

                const rect = bar.getBoundingClientRect();
                tooltip.innerHTML = `
                    <strong>${{item.name}}</strong><br>
                    <span style="font-family: monospace; font-size: 10px; color: #aaa">${{item.path}}</span><br>
                    Start: ${{formatDateTime(item.start)}}<br>
                    End: ${{formatDateTime(item.end)}}<br>
                    Duration: ${{durationDays}} days<br>
                    Lines: ${{item.lines.toLocaleString()}}
                `;
                tooltip.style.left = `${{rect.left}}px`;
                tooltip.style.top = `${{rect.top - tooltip.offsetHeight - 10}}px`;
                tooltip.classList.add('tooltip-visible');
            }});

            bar.addEventListener('mouseleave', () => {{
                // Remove highlight from related bars
                document.querySelectorAll('.timeline-bar.related').forEach(b => {{
                    b.classList.remove('related');
                }});
                
                // Remove highlight from markers
                document.querySelectorAll('.timeline-marker.active').forEach(m => {{
                    m.classList.remove('active');
                }});

                hideTimeout = setTimeout(() => {{
                    tooltip.classList.remove('tooltip-visible');
                }}, 300);
            }});

            track.appendChild(bar);

            track.appendChild(bar);
            row.appendChild(label);
            row.appendChild(track);
            timeline.appendChild(row);
        }});

        // Generate global vertical markers
        Object.keys(points).forEach(ts => {{
            const marker = document.createElement('div');
            const isAligned = points[ts].length > 1;
            
            // Only show aligned markers or specific ones if too many? 
            // User requested "each beginning/end of a block had a 1px-wide vertical line"
            // We'll render all, but aligned ones get special class
            
            marker.className = `timeline-marker ${{isAligned ? 'aligned' : ''}}`;
            marker.style.left = `${{calculatePosition(ts)}}%`;
            marker.dataset.ts = ts;
            
            marker.addEventListener('mouseenter', (e) => {{
                e.preventDefault();
                e.stopPropagation();
                if (hideTimeout) clearTimeout(hideTimeout);
                
                // Highlight related bars
                const allBars = document.querySelectorAll('.timeline-bar');
                allBars.forEach(b => {{
                    const bStart = b.dataset.start;
                    const bEnd = b.dataset.end;
                    if (bStart == ts || bEnd == ts) {{
                        b.classList.add('related');
                    }}
                }});

                const rect = marker.getBoundingClientRect();
                
                // Build tooltip content
                const shared = points[ts];
                let html = shared.map(s => `${{s.name}} ${{s.type}}`).join('<br>');
                html += `<br><br><span style="color: #aaa">${{formatDateTime(ts)}}</span>`;
                
                tooltip.innerHTML = html;
                tooltip.style.left = `${{rect.left + 10}}px`;
                tooltip.style.top = `${{rect.top - 10}}px`; // Slightly offset
                tooltip.classList.add('tooltip-visible');
            }});

            marker.addEventListener('mouseleave', () => {{
                // Remove highlight from related bars
                document.querySelectorAll('.timeline-bar.related').forEach(b => {{
                    b.classList.remove('related');
                }});

                hideTimeout = setTimeout(() => {{
                    tooltip.classList.remove('tooltip-visible');
                }}, 300);
            }});

            overlay.appendChild(marker);
        }});

        const dateAxis = document.getElementById('dateAxis');
        const numMarkers = 10;
        for (let i = 0; i <= numMarkers; i++) {{
            const timestamp = minTime + (timeRange / numMarkers) * i;
            const marker = document.createElement('div');
            marker.className = 'date-marker';
            marker.textContent = formatDate(timestamp);
            marker.style.left = `${{(i / numMarkers) * 100}}%`;
            dateAxis.appendChild(marker);
        }}
    </script>
</body>
</html>"""


def output_html(result: AnalysisResult, path: Path) -> None:
    """Write HTML visualization to file."""
    html = generate_html(result)
    path.write_text(html, encoding="utf-8")
    console.print(f"[green]✓[/green] HTML written to {path}")


# ============================================================================
# MAIN
# ============================================================================


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Compare time ranges across zsh history backups",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument(
        "files",
        nargs="*",
        help="Specific files to analyze (overrides auto-discovery)",
    )
    ap.add_argument(
        "--html",
        metavar="FILE",
        type=Path,
        help="Generate HTML visualization to FILE",
    )
    ap.add_argument(
        "--no-terminal",
        action="store_true",
        help="Suppress terminal output (useful with --html)",
    )
    args = ap.parse_args(argv)

    # Discover or use provided files
    if args.files:
        paths = [Path(f).expanduser().resolve() for f in args.files]
    else:
        paths = discover_files()
        if not paths:
            console.print("[red]No history files found[/red]")
            return 1
        console.print(f"[dim]Discovered {len(paths)} history files[/dim]")

    # Analyze
    result = analyze_all(paths)

    # Output
    if not args.no_terminal:
        output_terminal(result)

    if args.html:
        output_html(result, args.html)

    return 0


if __name__ == "__main__":
    sys.exit(main())

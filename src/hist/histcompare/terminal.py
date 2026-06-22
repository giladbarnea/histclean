from __future__ import annotations

from datetime import datetime

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .analysis import AnalysisResult

console = Console(stderr=True)


def format_ts(timestamp: int | None) -> str:
    """Format a timestamp as a readable date."""
    if timestamp is None:
        return "—"
    return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M")


def format_date_short(timestamp: int | None) -> str:
    """Format a timestamp as a short date."""
    if timestamp is None:
        return "—"
    return datetime.fromtimestamp(timestamp).strftime("%b %d")


def category_color(category: str) -> str:
    """Return the Rich color for a file category."""
    return {
        "main": "bold magenta",
        "timestamped": "bold yellow",
        "clean": "cyan",
        "snapshot": "green",
        "other": "white",
    }.get(category, "white")


def render_table(result: AnalysisResult) -> Table:
    """Render the analysis as a Rich table."""
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

    for history_file in result.files:
        color = category_color(history_file.category)
        name = Text(history_file.name, style=color)

        if history_file.error:
            table.add_row(name, Text(history_file.error, style="red"), "—", "—", "—")
            continue

        table.add_row(
            name,
            format_ts(history_file.start_ts),
            format_ts(history_file.end_ts),
            str(history_file.duration_days or "—"),
            f"{history_file.lines:,}",
        )

    return table


def render_ascii_timeline(result: AnalysisResult, width: int = 60) -> Panel:
    """Render an ASCII timeline visualization."""
    if not result.time_range:
        return Panel("No valid time range to display", title="Timeline")

    min_timestamp = result.min_ts
    time_range = result.time_range
    lines: list[Text] = []

    for history_file in result.files:
        if not history_file.sequences:
            continue

        color = category_color(history_file.category)
        chart_characters = [" "] * width

        for sequence in history_file.sequences:
            start_position = int(((sequence.start_ts - min_timestamp) / time_range) * width)
            end_position = int(((sequence.end_ts - min_timestamp) / time_range) * width)
            start_position = max(0, min(start_position, width - 1))
            end_position = max(0, min(end_position, width - 1))

            if start_position == end_position:
                chart_characters[start_position] = "█"
                continue
            for index in range(start_position, end_position + 1):
                chart_characters[index] = "█"

        name = history_file.name[:35].ljust(35)
        line = Text()
        line.append(f"{name} ", style="dim")
        line.append("".join(chart_characters), style=color)
        lines.append(line)

    axis_dates = []
    for index in range(5):
        timestamp = min_timestamp + (time_range * index // 4)
        axis_dates.append(format_date_short(timestamp))

    axis = Text()
    axis.append(" " * 36)
    spacing = width // 4
    for index, date_text in enumerate(axis_dates):
        if index == 0:
            axis.append(date_text, style="dim")
            continue
        padding = spacing - len(axis_dates[index - 1])
        axis.append(" " * padding + date_text, style="dim")

    lines.append(Text(""))
    lines.append(axis)

    return Panel(
        "\n".join(str(line) for line in lines),
        title="Timeline (oldest → newest)",
        border_style="dim",
    )


def render_summary(result: AnalysisResult) -> Panel:
    """Render a summary panel with key findings."""
    main_history = next(
        (history_file for history_file in result.files if history_file.category == "main"),
        None,
    )
    backups = [
        history_file
        for history_file in result.files
        if history_file.category != "main" and history_file.lines > 0
    ]
    largest_backup = max(backups, key=lambda history_file: history_file.lines) if backups else None
    earliest_file = min(
        (history_file for history_file in result.files if history_file.start_ts),
        key=lambda history_file: history_file.start_ts,
        default=None,
    )

    lines: list[Text] = []

    if result.dirty_file_count:
        lines.append(
            Text.assemble(
                ("Note: ", "bold yellow"),
                (
                    "one or more selected history files are not clean; optimal timeline may change after cleaning.",
                    "yellow",
                ),
            )
        )
        lines.append(Text(""))

    if main_history and earliest_file and main_history.start_ts and earliest_file.start_ts:
        gap_days = (main_history.start_ts - earliest_file.start_ts) // 86400
        if gap_days > 0:
            lines.append(
                Text.assemble(
                    ("⚠️  ", "yellow"),
                    ("Missing history: ", "bold red"),
                    (f"{gap_days} days ", "bold"),
                    (
                        f"({format_date_short(earliest_file.start_ts)} → {format_date_short(main_history.start_ts)})",
                        "dim",
                    ),
                )
            )

    if largest_backup:
        lines.append(
            Text.assemble(
                ("📦 ", ""),
                ("Largest backup: ", "bold"),
                (f"{largest_backup.name} ", "cyan"),
                (f"({largest_backup.lines:,} lines)", "dim"),
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
                (
                    f"({format_date_short(result.min_ts)} → {format_date_short(result.max_ts)})",
                    "dim",
                ),
            )
        )

    if result.optimal_path:
        lines.append(Text(""))
        lines.append(Text("Optimal Coverage Path:", style="bold green"))
        for segment in result.optimal_path:
            duration = max(1, (segment.end_ts - segment.start_ts) // 86400)
            lines.append(
                Text.assemble(
                    ("  • ", "dim"),
                    (segment.file.name, "cyan"),
                    (f" ({duration}d)", "dim"),
                    (" : ", "dim"),
                    (format_date_short(segment.start_ts), "bold"),
                    (" → ", "dim"),
                    (format_date_short(segment.end_ts), "bold"),
                )
            )

    return Panel(
        "\n".join(str(line) for line in lines),
        title="Summary",
        border_style="green",
    )


def output_terminal(result: AnalysisResult) -> None:
    """Output the analysis to the terminal with Rich formatting."""
    console.print()
    console.print(render_summary(result))
    console.print()
    console.print(render_table(result))
    console.print()
    console.print(render_ascii_timeline(result))
    console.print()

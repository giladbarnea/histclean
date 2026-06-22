from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from ..history_files import discover_history_files

EXT_LINE_RE = re.compile(r"^:\s*(\d+):\d+;")


@dataclass
class Sequence:
    """A continuous sequence of history entries."""

    start_ts: int
    end_ts: int
    count: int = 0


@dataclass
class HistoryFile:
    """Represents a history file with its metadata and time sequences."""

    path: Path
    name: str
    sequences: list[Sequence] = field(default_factory=list)
    lines: int = 0
    error: str | None = None

    def __hash__(self) -> int:
        return hash(self.path)

    @property
    def start_ts(self) -> int | None:
        return self.sequences[0].start_ts if self.sequences else None

    @property
    def end_ts(self) -> int | None:
        return self.sequences[-1].end_ts if self.sequences else None

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
class OptimalSegment:
    """A segment of the optimal history path."""

    start_ts: int
    end_ts: int
    file: HistoryFile


@dataclass
class AnalysisResult:
    """Aggregated analysis of all history files."""

    files: list[HistoryFile] = field(default_factory=list)
    optimal_path: list[OptimalSegment] = field(default_factory=list)
    dirty_file_count: int = 0

    @property
    def min_ts(self) -> int | None:
        valid = [history_file.start_ts for history_file in self.files if history_file.start_ts]
        return min(valid) if valid else None

    @property
    def max_ts(self) -> int | None:
        valid = [history_file.end_ts for history_file in self.files if history_file.end_ts]
        return max(valid) if valid else None

    @property
    def time_range(self) -> int | None:
        if self.min_ts and self.max_ts:
            return self.max_ts - self.min_ts
        return None


def discover_files(*, cwd: Path | None = None, home: Path | None = None) -> list[Path]:
    """Find the same default history files histmerge would consider."""
    return discover_history_files(cwd=cwd, home=home)


def extract_timestamp(line: str) -> int | None:
    """Extract an epoch timestamp from an EXTENDED_HISTORY line."""
    match = EXT_LINE_RE.match(line)
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def scan_file(path: Path) -> tuple[list[Sequence], int]:
    """Scan a file to extract sequences and total line count."""
    timestamps: list[int] = []
    line_count = 0

    try:
        with path.open("r", encoding="utf-8", errors="replace") as file_handle:
            for line in file_handle:
                line_count += 1
                timestamp = extract_timestamp(line)
                if timestamp:
                    timestamps.append(timestamp)
    except OSError:
        return [], 0

    if not timestamps:
        return [], line_count

    timestamps.sort()
    sequences: list[Sequence] = []
    gap_threshold = 86400

    current_start = timestamps[0]
    current_end = timestamps[0]
    current_count = 1

    for timestamp in timestamps[1:]:
        if timestamp - current_end >= gap_threshold:
            sequences.append(Sequence(current_start, current_end, current_count))
            current_start = timestamp
            current_count = 0
        current_end = timestamp
        current_count += 1

    sequences.append(Sequence(current_start, current_end, current_count))
    return sequences, line_count


def analyze_file(path: Path) -> HistoryFile:
    """Analyze a single history file."""
    history_file = HistoryFile(path=path, name=path.name)

    if not path.exists():
        history_file.error = "File not found"
        return history_file

    sequences, lines = scan_file(path)
    history_file.sequences = sequences
    history_file.lines = lines

    if not history_file.sequences:
        history_file.error = "No valid timestamps found"

    return history_file


def analyze_all(paths: Iterable[Path]) -> AnalysisResult:
    """Analyze all given history files."""
    result = AnalysisResult()
    for path in paths:
        result.files.append(analyze_file(path))
    result.files.sort(key=lambda history_file: (history_file.start_ts or float("inf"), history_file.name))
    result.optimal_path = calculate_optimal_path(result.files)
    return result


def calculate_optimal_path(files: list[HistoryFile]) -> list[OptimalSegment]:
    """Calculate the minimal set of files that best covers the full timeline."""
    all_sequences: list[tuple[int, int, HistoryFile]] = []
    for history_file in files:
        if not history_file.sequences:
            continue
        for sequence in history_file.sequences:
            all_sequences.append((sequence.start_ts, sequence.end_ts, history_file))

    if not all_sequences:
        return []

    all_sequences.sort(key=lambda sequence: (sequence[0], sequence[1], sequence[2].name))
    path: list[OptimalSegment] = []

    current_timestamp = all_sequences[0][0]
    max_timestamp = max(sequence[1] for sequence in all_sequences)

    while current_timestamp < max_timestamp:
        candidates = [
            sequence
            for sequence in all_sequences
            if sequence[0] <= current_timestamp and sequence[1] >= current_timestamp
        ]

        if not candidates:
            future_starts = [sequence[0] for sequence in all_sequences if sequence[0] > current_timestamp]
            if not future_starts:
                break
            current_timestamp = min(future_starts)
            continue

        last_file = (
            path[-1].file if path and path[-1].end_ts >= current_timestamp - 1 else None
        )
        best = candidates[0]

        for candidate in candidates:
            if candidate[1] > best[1]:
                best = candidate
            elif candidate[1] == best[1]:
                if last_file and candidate[2] == last_file or candidate[2].category == "main":
                    best = candidate

        if path and path[-1].file == best[2] and path[-1].end_ts >= current_timestamp - 1:
            path[-1].end_ts = best[1]
        else:
            path.append(OptimalSegment(current_timestamp, best[1], best[2]))

        current_timestamp = best[1] + 1

    return path

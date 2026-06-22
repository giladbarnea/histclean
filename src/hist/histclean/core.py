from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from rich import box
from rich.console import Group
from rich.panel import Panel
from rich.rule import Rule
from rich.style import Style
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text as RichText

HISTORY_ENTRY_RE = re.compile(r"^: \d{10}:\d+;")


def parse_history_entries(all_lines: list[str]):
    """Parse zsh history into individual entry blocks."""
    if not all_lines:
        return

    index = 0
    line_count = len(all_lines)
    while index < line_count:
        current_line = all_lines[index]
        if HISTORY_ENTRY_RE.match(current_line):
            next_index = index + 1
            while next_index < line_count and not HISTORY_ENTRY_RE.match(
                all_lines[next_index]
            ):
                next_index += 1
            yield index, all_lines[index:next_index]
            index = next_index
            continue
        yield index, [current_line]
        index += 1


def remove_timestamp_from_entry(entry_block: list[str]) -> str:
    """Extract the command text from a history entry block."""
    if not entry_block:
        return ""
    first_line = entry_block[0]
    if HISTORY_ENTRY_RE.match(first_line):
        command_part = first_line.split(";", 1)[1]
        return "\n".join([command_part, *entry_block[1:]])
    return "\n".join(entry_block)


class BaseFlag(ABC):
    """Abstract base class for a flagged change in the history file."""

    def __init__(
        self,
        all_entries: list[list[str]],
        entry_line_nums: list[int],
        max_line_num_width: int,
        reason_text: str,
    ):
        self.all_entries = all_entries
        self.entry_line_nums = entry_line_nums
        self.max_line_num_width = max_line_num_width
        self.reason_text = reason_text

    @abstractmethod
    def get_indices_to_remove(self) -> set[int]:
        raise NotImplementedError

    def render(self) -> Panel:
        raise NotImplementedError

    @abstractmethod
    def get_sort_key(self) -> int:
        raise NotImplementedError

    @abstractmethod
    def get_all_covered_indices(self) -> set[int]:
        raise NotImplementedError

    def _format_line(
        self,
        table: Table,
        entry_index: int,
        content_renderable: RichText | Syntax,
        marker: str = " ",
    ) -> None:
        line_num = self.entry_line_nums[entry_index] + 1
        line_num_str = f"{line_num}"
        marker_text = RichText(
            marker, style=f"diff.{'plus' if marker == '+' else 'minus'}"
        )
        table.add_row(line_num_str, marker_text, content_renderable)


class IndividualFlag(BaseFlag):
    """Represents a single flagged entry to be removed."""

    def __init__(
        self,
        entry_index: int,
        reasons: list[str],
        **kwargs,
    ):
        super().__init__(reason_text="\n".join(f"- {reason}" for reason in reasons), **kwargs)
        self.entry_index = entry_index

    def get_indices_to_remove(self) -> set[int]:
        return {self.entry_index}

    def get_sort_key(self) -> int:
        return self.entry_index

    def get_all_covered_indices(self) -> set[int]:
        return {self.entry_index}

    def render(self) -> Panel:
        meta_table = Table.grid(padding=(0, 2))
        meta_table.add_column(style=Style.parse("bold #98C379"))
        meta_table.add_column()
        meta_table.add_row("Reason(s):", self.reason_text)
        entry_command = remove_timestamp_from_entry(self.all_entries[self.entry_index])

        line_num = self.entry_line_nums[self.entry_index] + 1
        line_num_str = f"{line_num:>{self.max_line_num_width}}"
        line_num_text = RichText(line_num_str, style="#3A3F4C")

        entry_syntax = Syntax(entry_command, "bash", theme="monokai", line_numbers=False)

        entry_display_table = Table.grid(padding=(0, 1))
        entry_display_table.add_column(width=self.max_line_num_width, justify="right")
        entry_display_table.add_column()
        entry_display_table.add_row(line_num_text, entry_syntax)

        meta_table.add_row("Entry:", entry_display_table)

        return Panel(
            meta_table,
            box=box.ROUNDED,
            title="[title]Flagged Entry[/title]",
            border_style="#4B5263",
            padding=(1, 2),
        )


class ClusterFlag(BaseFlag):
    """Represents a sequence of similar commands to be collapsed."""

    def __init__(self, start_index: int, end_index: int, **kwargs):
        super().__init__(**kwargs)
        self.start_index = start_index
        self.end_index = end_index

    def get_indices_to_remove(self) -> set[int]:
        return set(range(self.start_index, self.end_index))

    def get_sort_key(self) -> int:
        return self.start_index

    def get_all_covered_indices(self) -> set[int]:
        return set(range(self.start_index, self.end_index + 1))

    def render(self) -> Panel:
        meta_table = Table.grid(padding=(0, 1, 1, 2))
        meta_table.add_column(style=Style.parse("bold #98C379"))
        meta_table.add_column()
        meta_table.add_row("Reason:", self.reason_text)
        meta_table.add_row(
            "Action:",
            RichText(
                "Keep only the last entry in the sequence", style="italic #61AFEF"
            ),
        )

        entries_table = Table.grid(padding=(0, 1))
        entries_table.add_column(
            width=self.max_line_num_width + 1, justify="right", style="#3A3F4C"
        )
        entries_table.add_column(width=2, justify="right")
        entries_table.add_column()

        if self.start_index > 0:
            before_index = self.start_index - 1
            command = remove_timestamp_from_entry(self.all_entries[before_index])
            self._format_line(entries_table, before_index, RichText(command, style="#5C6370"))

        for offset, entry_index in enumerate(range(self.start_index, self.end_index + 1)):
            is_last = offset == self.end_index - self.start_index
            command = remove_timestamp_from_entry(self.all_entries[entry_index])
            if is_last:
                syntax = Syntax(command, "bash", theme="monokai", line_numbers=False)
                self._format_line(entries_table, entry_index, syntax, marker="+")
                continue
            dimmed_syntax = RichText(command, style="#5C6370")
            self._format_line(entries_table, entry_index, dimmed_syntax, marker="-")

        if self.end_index < len(self.all_entries) - 1:
            after_index = self.end_index + 1
            command = remove_timestamp_from_entry(self.all_entries[after_index])
            self._format_line(entries_table, after_index, RichText(command, style="#5C6370"))

        content_group = Group(meta_table, Rule(style="#4B5263"), entries_table)

        return Panel(
            content_group,
            box=box.ROUNDED,
            title="[title]Similar Command Sequence[/title]",
            border_style="#4B5263",
            padding=(0, 1),
        )


class DuplicateFlag(BaseFlag):
    """Represents a group of duplicate commands to be collapsed."""

    def __init__(self, entry_indices: list[int], **kwargs):
        super().__init__(**kwargs)
        self.entry_indices = entry_indices

    def get_indices_to_remove(self) -> set[int]:
        return set(self.entry_indices[:-1])

    def get_sort_key(self) -> int:
        return self.entry_indices[0]

    def get_all_covered_indices(self) -> set[int]:
        return set(self.entry_indices)

    def render(self) -> Panel:
        meta_table = Table.grid(padding=(0, 1, 1, 2))
        meta_table.add_column(style=Style.parse("bold #98C379"))
        meta_table.add_column()
        meta_table.add_row("Reason:", self.reason_text)
        meta_table.add_row(
            "Action:",
            RichText(
                "Keep only the last entry in the sequence", style="italic #61AFEF"
            ),
        )

        entries_table = Table.grid(padding=(0, 1))
        entries_table.add_column(
            width=self.max_line_num_width + 1, justify="right", style="#3A3F4C"
        )
        entries_table.add_column(width=2, justify="right")
        entries_table.add_column()

        for offset, entry_index in enumerate(self.entry_indices):
            is_last = offset == len(self.entry_indices) - 1
            command = remove_timestamp_from_entry(self.all_entries[entry_index])
            if is_last:
                syntax = Syntax(command, "bash", theme="monokai", line_numbers=False)
                self._format_line(entries_table, entry_index, syntax, marker="+")
                continue
            dimmed_syntax = RichText(command, style="#5C6370")
            self._format_line(entries_table, entry_index, dimmed_syntax, marker="-")

        content_group = Group(meta_table, Rule(style="#4B5263"), entries_table)

        return Panel(
            content_group,
            box=box.ROUNDED,
            title="[title]Duplicate Commands[/title]",
            border_style="#4B5263",
            padding=(0, 1),
        )


@dataclass
class HistoryAnalysis:
    original_lines: list[str]
    all_entries: list[list[str]]
    flagged_entries: list[BaseFlag]

    @property
    def is_clean(self) -> bool:
        return not self.flagged_entries


@dataclass
class HistoryCheckResult:
    path: Path
    is_clean: bool
    flagged_count: int = 0
    error: str | None = None

#!/usr/bin/env /opt/homebrew/bin/uvx --with=rich,textual,pygments python
"""
histclean.py - Zsh history cleaning utility

**Architecture & Extension Guide**

This document explains the core design philosophy of `histclean.py` to help you add new features easily and maintainably.

**1. The Guiding Philosophy**

The central idea is that **every proposed change is an object that knows how to manage itself.** We don't have a master function with lots of `if` statements. Instead, we have different types of `Flag` objects (e.g., `IndividualFlag`, `DuplicateFlag`), and each one encapsulates the logic for its specific kind of change.

The main reason for this design is to make the script easy to extend. Adding a new feature should feel like adding a new, self-contained module, not like performing surgery on the core logic.

For the interactive UI (built with Textual), the philosophy extends to decoupling presentation from core logic: Flags handle their own rendering, the TUI collects user intents (e.g., toggles) without mutating data, and mutations are deferred until final approval.

**2. The Lifecycle of a Change**

Any change you propose will follow this five-step journey:

1.  **Strategy:** A simple function that finds things to flag (e.g., `flag_duplicate_groups`).
2.  **Instantiation:** The main loop creates a `Flag` object from your strategy's findings.
3.  **Merging:** A central function resolves any overlaps between different `Flag` objects.
4.  **Interactive Review:** The Textual UI displays rendered flags as panels, allowing navigation (up/down to focus/center), toggling (space to disable/enable via CSS class), and global approval (y/n).
5.  **Rendering & Application:** If approved, the UI filters flags based on toggles and asks each approved `Flag` which indices to `get_indices_to_remove()` for final cleaning.

**3. How to Add a New Cleaning Feature**

Let's say you want to add a feature to flag commands longer than 200 characters. Here’s how you’d do it by following the pattern:

1.  **Create the Strategy:** Write a new function, `flag_long_commands(all_entries)`, that yields the index of each long command.
2.  **Create the `Flag` Class:** Create a new class, `LongCommandFlag(BaseFlag)`.
    *   In its `render()` method, define how it should look on screen (e.g., a Panel with reason and entry display).
    *   In its `get_indices_to_remove()` method, tell the system which entry to remove.
3.  **Add it to the Pipeline:** In `main()`, add your new strategy and class to the `pipeline_steps` list.

That's it. Notice you didn't have to touch the complex merging, display, or removal logic—or modify the Textual UI to support your new flag type. You just created a new, self-contained component and plugged it in; the interactive review will automatically render and allow toggling your new flags.
"""

# ============================================================================
# ZSH LEXER
# ============================================================================

from __future__ import annotations

import difflib
import re
import sys
from abc import ABC, abstractmethod
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterator

from pygments.lexer import RegexLexer, bygroups, include
from pygments.token import (
    Comment,
    Error,
    Generic,
    Keyword,
    Name,
    Number,
    Operator,
    Punctuation,
    String,
    Text,
    Token,
)
from rich import box
from rich.console import Console, Group
from rich.panel import Panel
from rich.prompt import Confirm
from rich.rule import Rule
from rich.style import Style
from rich.syntax import Syntax, SyntaxTheme
from rich.table import Table
from rich.text import Text as RichText
from rich.theme import Theme
from textual import on
from textual.app import App, ComposeResult, RenderableType
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.events import Focus
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Footer, Header, Label, Static


class NonScrollableVerticalScroll(VerticalScroll):
    BINDINGS = [
        b
        for b in VerticalScroll.BINDINGS
        if b.key not in ["up", "down", "pageup", "pagedown", "home", "end"]
    ]


# Define custom token types so Rich and Pygments know about them
Name.Argument = Token.Name.Argument
Name.Variable.Magic = Token.Name.Variable.Magic
Keyword.Type = Token.Keyword.Type


class ZshLexer(RegexLexer):
    """
    A robust, stateful Z-shell lexer for Pygments.
    Use like so:
    ```python
    console = Console()
    syntax = Syntax(sample, ZshLexer(), theme=MonokaiProTheme(), line_numbers=True)
    console.print(syntax)
    ```
    """

    name = "Z-shell"
    aliases = ["zsh"]
    filenames = ["*.zsh", "*.bash", "*.sh", ".zshrc", ".zprofile", "zshrc", "zprofile"]

    flags = re.MULTILINE | re.DOTALL

    tokens = {
        # '_base' contains common patterns, now correctly ordered
        "_base": [
            (r"\\.", String.Escape),
            # IMPORTANT: Arithmetic must be checked before command substitution
            (r"\$\(\(", Operator, "arithmetic_expansion"),
            (r"\$\(", String.Interpol, "command_substitution"),
            (
                r"\b(if|fi|else|elif|then|for|in|while|do|done|case|esac|function|select)\b",
                Keyword.Reserved,
            ),
            (
                r"\b(echo|printf|cd|pwd|export|unset|readonly|source|exit|return|break|continue)\b",
                Name.Builtin,
            ),
            (r"\$\{", Name.Variable.Magic, "parameter_expansion"),
            (r"\$[a-zA-Z0-9_@*#?$!~-]+", Name.Variable),
            (r"'[^']*'", String.Single),
            (r'"', String.Double, "string_double"),
        ],
        "root": [
            (r"\s+", Text),
            (r"(<<<|<<-?|>>?|<&|>&)?[0-9]*[<>]", Operator),
            (r"\|\|?|&&|&", Operator),
            (r"[;()\[\]{}]", Punctuation),
            # IMPORTANT: Give numbers explicit priority
            (r"\b[0-9]+\b", Number.Integer),
            include("_base"),
            (r"([a-zA-Z0-9_./-]+)", Name.Function, "cmdtail"),
        ],
        "cmdtail": [
            (r"\n", Text, "#pop"),
            (r"[|]", Operator, "#pop"),
            (r"[;&]", Punctuation, "#pop"),
            (r"\s+", Text),
            (r"(?:--?|\+)[a-zA-Z0-9][\w-]*", Name.Attribute),
            (r"=", Operator),
            # IMPORTANT: Give numbers explicit priority
            (r"\b[0-9]+\b", Number.Integer),
            include("_base"),
            (r"[^=\s;&|(){}<>\[\]]+", Name.Argument),
        ],
        "string_double": [
            (r'"', String.Double, "#pop"),
            (r'\\(["$`\\])', String.Escape),
            include("_base"),
        ],
        "command_substitution": [
            (r"\)", String.Interpol, "#pop"),
            include("root"),
        ],
        "arithmetic_expansion": [
            (r"\)\)", Operator, "#pop"),
            (r"[-+*/%&|<>!=^]+", Operator.Word),
            (r"\b[0-9]+\b", Number.Integer),
            (r"[a-zA-Z_][a-zA-Z0-9_]*", Name.Variable),
            (r"\s+", Text),
        ],
        "parameter_expansion": [
            (r"\}", Name.Variable.Magic, "#pop"),
            (r"\s+", Text),
            # Nested constructs
            (r"\$\{", Name.Variable.Magic, "#push"),
            (r"\$\(", String.Interpol, "command_substitution"),
            (r"\$\(\(", Operator, "arithmetic_expansion"),
            # Match flags and the variable name together
            (
                r"(\([#@=a-zA-Z:?^]+\))([a-zA-Z_][a-zA-Z0-9_]*)",
                bygroups(Keyword.Type, Name.Variable),
            ),
            # Match just a variable name if no flags
            (r"[a-zA-Z_][a-zA-Z0-9_]*", Name.Variable),
            # Operators for substitution, slicing, etc.
            (r"[#%/:|~^]+", Operator),
            # The rest is a pattern or other content
            (r"[^}]+", Text),
        ],
    }


class MonokaiProTheme(SyntaxTheme):
    """Rich syntax-highlighting theme that matches Monokai Pro."""

    _BLACK = "#2d2a2e"
    _RED = "#ff6188"
    _GREEN = "#a9dc76"
    _YELLOW = "#ffd866"
    _ORANGE = "#fc9867"
    _PURPLE = "#ab9df2"
    _CYAN = "#78dce8"
    _WHITE = "#fcfcfa"
    _COMMENT_GRAY = "#727072"

    background_color = _BLACK
    default_style = Style(color=_WHITE)

    styles = {
        # Zsh-specific additions with new, non-conflicting colors
        Name.Function: Style(color=_GREEN, bold=True),  # git, curl
        Name.Attribute: Style(color=_ORANGE),  # --long, -l
        Name.Argument: Style(color=_PURPLE),  # a filename
        Name.Variable.Magic: Style(color=_PURPLE),  # ${PATH}
        Name.Builtin: Style(color=_CYAN, italic=True),
        Number: Style(color=_CYAN),  # Colder color for numbers
        Keyword.Type: Style(color=_CYAN, italic=True),  # For parameter flags like (f)
        # Base styles
        Text: Style(color=_WHITE),
        Comment: Style(color=_COMMENT_GRAY, italic=True),
        Keyword: Style(color=_RED, bold=True),
        Operator: Style(color=_RED),
        Operator.Word: Style(color=_RED),  # For +, -, * in arithmetic
        Punctuation: Style(color=_WHITE),
        Name.Variable: Style(color=_WHITE),
        String: Style(color=_YELLOW),  # All strings are yellow
        String.Escape: Style(color=_PURPLE),
        String.Interpol: Style(color=_PURPLE, bold=True),
        Error: Style(color=_RED, bold=True),
        Generic.Emph: Style(italic=True),
        Generic.Strong: Style(bold=True),
    }

    @classmethod
    def get_style_for_token(cls, t):
        return cls.styles.get(t, cls.default_style)

    @classmethod
    def get_background_style(cls):
        return Style(bgcolor=cls._BLACK)


# ============================================================================
# CONFIGURATION & CONSTANTS
# ============================================================================

# Define a custom theme for a polished, modern look inspired by high-end dev tools
CUSTOM_THEME = Theme({
    "title": "bold #C678DD",
    "reason": "bold #98C379",
    "action": "italic #61AFEF",
    "context": "#5C6370",
    "border": "#4B5263",
    "rule": "#4B5263",
    "diff.plus": "bold #61AFEF",
    "diff.minus": "bold #E06C75",
    "info": "#61AFEF",
    "success": "#98C379",
    "warning": "#E5C07B",
    "error": "#E06C75",
    "linenumber": "#3A3F4C",
})

console = Console(stderr=True, theme=CUSTOM_THEME)

# Type aliases for better readability
IndividualCleaningStrategy = Callable[[list[list[str]]], Iterator[tuple[int, str]]]
ClusterCleaningStrategy = Callable[[list[list[str]]], Iterator[tuple[int, int]]]

# Regex patterns
HISTORY_ENTRY_RE = re.compile(r"^: \d{10}:\d+;")

BLACKLIST_PATTERNS = [
    re.compile(r"--version\s*$"),  # Version flag
    re.compile(r"[א-ת]+"),  # Hebrew characters
    re.compile(r"[^\x20-\x7E\t]+"),  # Non-ASCII characters
    re.compile(r"^ *\n?$"),  # Empty line
    re.compile(r"^.$", re.DOTALL),  # Single character
]

# Similarity thresholds
JACCARD_SIMILARITY_THRESHOLD = 0.5
DIFFLIB_SIMILARITY_THRESHOLD = 0.75
MAX_CLUSTER_LOOKAHEAD = 2


class Config:
    """Configuration for the cleaning pipeline"""

    @property
    def individual_strategies(self) -> list[IndividualCleaningStrategy]:
        """→ Individual entry flagging strategies"""
        return [
            flag_individual_multiline,
            flag_individual_empty,
            flag_individual_blacklist,
        ]

    @property
    def cluster_strategies(self) -> list[tuple[ClusterCleaningStrategy, str]]:
        """→ Cluster flagging strategies with descriptions"""
        return [
            (flag_cluster_jaccard_similarity, "Consecutive similar entries (Jaccard)"),
            (flag_cluster_difflib_similarity, "Consecutive similar entries (difflib)"),
        ]

    @property
    def duplicate_strategy(self) -> Callable[[list[list[str]]], Iterator[list[int]]]:
        """→ Duplicate detection strategy"""
        return flag_duplicate_groups


CONFIG = Config()

# ============================================================================
# DATA STRUCTURES
# ============================================================================


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
        """Returns the set of entry indices to be removed."""
        raise NotImplementedError

    @abstractmethod
    def render(self) -> Panel:
        """Returns a rich Panel object for display."""
        raise NotImplementedError

    @abstractmethod
    def get_sort_key(self) -> int:
        """Returns the primary index used for sorting."""
        raise NotImplementedError

    @abstractmethod
    def get_all_covered_indices(self) -> set[int]:
        """Returns all indices covered by this flag for overlap detection."""
        raise NotImplementedError

    def _format_line(
        self, table: Table, entry_idx: int, content_renderable: RichText | Syntax, marker: str = " "
    ):
        line_num = self.entry_line_nums[entry_idx] + 1
        line_num_str = f"{line_num}"
        marker_text = RichText(marker, style=f"diff.{'plus' if marker == '+' else 'minus'}")
        table.add_row(line_num_str, marker_text, content_renderable)

    @abstractmethod
    def get_render_entries(self) -> list[tuple[str, str, RenderableType, bool, bool]]:
        """Returns list of (line_num_str, marker, content, is_context, is_kept) for rendering."""
        raise NotImplementedError


class IndividualFlag(BaseFlag):
    """Represents a single flagged entry to be removed."""

    def __init__(
        self,
        entry_index: int,
        reasons: list[str],
        **kwargs,
    ):
        super().__init__(reason_text="\n".join(f"- {r}" for r in reasons), **kwargs)
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
        entry_cmd = remove_timestamp_from_entry(self.all_entries[self.entry_index])

        line_num = self.entry_line_nums[self.entry_index] + 1
        line_num_str = f"{line_num:>{self.max_line_num_width}}"
        line_num_text = RichText(line_num_str, style="#3A3F4C")

        entry_syntax = Syntax(entry_cmd, "bash", theme="monokai", line_numbers=False)

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

    def get_render_entries(self) -> list[tuple[str, str, RenderableType, bool, bool]]:
        entry_idx = self.entry_index
        cmd = remove_timestamp_from_entry(self.all_entries[entry_idx])
        syntax = Syntax(cmd, ZshLexer(), theme=MonokaiProTheme(), line_numbers=False)
        line_num = self.entry_line_nums[entry_idx] + 1
        line_num_str = f"{line_num:>{self.max_line_num_width}}"
        return [(line_num_str, "-", syntax, False, False)]


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
            RichText("Keep only the last entry in the sequence", style="italic #61AFEF"),
        )

        entries_table = Table.grid(padding=(0, 1))
        entries_table.add_column(
            width=self.max_line_num_width + 1, justify="right", style="#3A3F4C"
        )
        entries_table.add_column(width=2, justify="right")  # For diff markers
        entries_table.add_column()

        # Context: entry before the cluster
        if self.start_index > 0:
            before_idx = self.start_index - 1
            cmd = remove_timestamp_from_entry(self.all_entries[before_idx])
            self._format_line(entries_table, before_idx, RichText(cmd, style="#5C6370"))

        # The cluster entries
        for i, entry_idx in enumerate(range(self.start_index, self.end_index + 1)):
            is_last = i == (self.end_index - self.start_index)
            cmd = remove_timestamp_from_entry(self.all_entries[entry_idx])
            if is_last:
                syntax = Syntax(cmd, "bash", theme="monokai", line_numbers=False)
                self._format_line(entries_table, entry_idx, syntax, marker="+")
            else:
                dimmed_syntax = RichText(cmd, style="#5C6370")
                self._format_line(entries_table, entry_idx, dimmed_syntax, marker="-")

        # Context: entry after the cluster
        if self.end_index < len(self.all_entries) - 1:
            after_idx = self.end_index + 1
            cmd = remove_timestamp_from_entry(self.all_entries[after_idx])
            self._format_line(entries_table, after_idx, RichText(cmd, style="#5C6370"))

        content_group = Group(
            meta_table,
            Rule(style="#4B5263"),
            entries_table,
        )

        return Panel(
            content_group,
            box=box.ROUNDED,
            title="[title]Similar Command Sequence[/title]",
            border_style="#4B5263",
            padding=(0, 1),
        )

    def get_render_entries(self) -> list[tuple[str, str, RenderableType, bool, bool]]:
        entries: list[tuple[str, str, RenderableType, bool, bool]] = []

        # Context: entry before the cluster
        if self.start_index > 0:
            before_idx = self.start_index - 1
            cmd = remove_timestamp_from_entry(self.all_entries[before_idx])
            line_num = self.entry_line_nums[before_idx] + 1
            line_num_str = f"{line_num:>{self.max_line_num_width}}"
            entries.append((line_num_str, "", RichText(cmd), True, False))

        # The cluster entries
        for i in range(self.start_index, self.end_index + 1):
            is_last = i == self.end_index
            cmd = remove_timestamp_from_entry(self.all_entries[i])
            line_num = self.entry_line_nums[i] + 1
            line_num_str = f"{line_num:>{self.max_line_num_width}}"
            marker = "+" if is_last else "-"
            content = (
                Syntax(cmd, ZshLexer(), theme=MonokaiProTheme(), line_numbers=False)
                if is_last
                else RichText(cmd)
            )
            entries.append((line_num_str, marker, content, False, is_last))

        # Context: entry after the cluster
        if self.end_index < len(self.all_entries) - 1:
            after_idx = self.end_index + 1
            cmd = remove_timestamp_from_entry(self.all_entries[after_idx])
            line_num = self.entry_line_nums[after_idx] + 1
            line_num_str = f"{line_num:>{self.max_line_num_width}}"
            entries.append((line_num_str, "", RichText(cmd), True, False))

        return entries


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
            RichText("Keep only the last entry in the sequence", style="italic #61AFEF"),
        )

        entries_table = Table.grid(padding=(0, 1))
        entries_table.add_column(
            width=self.max_line_num_width + 1, justify="right", style="#3A3F4C"
        )
        entries_table.add_column(width=2, justify="right")
        entries_table.add_column()

        for i, entry_idx in enumerate(self.entry_indices):
            is_last = i == len(self.entry_indices) - 1
            cmd = remove_timestamp_from_entry(self.all_entries[entry_idx])
            if is_last:
                syntax = Syntax(cmd, "bash", theme="monokai", line_numbers=False)
                self._format_line(entries_table, entry_idx, syntax, marker="+")
            else:
                dimmed_syntax = RichText(cmd, style="#5C6370")
                self._format_line(entries_table, entry_idx, dimmed_syntax, marker="-")

        content_group = Group(
            meta_table,
            Rule(style="#4B5263"),
            entries_table,
        )

        return Panel(
            content_group,
            box=box.ROUNDED,
            title="[title]Duplicate Commands[/title]",
            border_style="#4B5263",
            padding=(0, 1),
        )

    def get_render_entries(self) -> list[tuple[str, str, RenderableType, bool, bool]]:
        entries: list[tuple[str, str, RenderableType, bool, bool]] = []

        for i, entry_idx in enumerate(self.entry_indices):
            is_last = i == len(self.entry_indices) - 1
            cmd = remove_timestamp_from_entry(self.all_entries[entry_idx])
            line_num = self.entry_line_nums[entry_idx] + 1
            line_num_str = f"{line_num:>{self.max_line_num_width}}"
            marker = "+" if is_last else "-"
            content = (
                Syntax(cmd, ZshLexer(), theme=MonokaiProTheme(), line_numbers=False)
                if is_last
                else RichText(cmd)
            )
            entries.append((line_num_str, marker, content, False, is_last))

        return entries


# ============================================================================
# PARSING & UTILITIES
# ============================================================================


def _console_print(string="", *args, **kwargs) -> None:
    """→ Safe console printing with fallback"""
    try:
        console.print(string, *args, **kwargs)
    except Exception:
        kwargs.setdefault("file", sys.stderr)
        kwargs_clean = {k: v for k, v in kwargs.items() if k not in ["sep", "file", "end", "flush"]}
        print(string, *args, **kwargs_clean)


def parse_history_entries(all_lines: list[str]) -> Iterator[tuple[int, list[str]]]:
    """→ Parses zsh history into individual entry blocks, yielding (start_line, block)"""
    if not all_lines:
        return

    i = 0
    num_lines = len(all_lines)
    while i < num_lines:
        current_line = all_lines[i]
        if HISTORY_ENTRY_RE.match(current_line):
            j = i + 1
            while j < num_lines and not HISTORY_ENTRY_RE.match(all_lines[j]):
                j += 1
            yield i, all_lines[i:j]  # Yield 0-indexed line number and block
            i = j
        else:
            yield i, [current_line]
            i += 1


def remove_timestamp_from_entry(entry_block: list[str]) -> str:
    """→ Extracts the command text from a history entry block"""
    if not entry_block:
        return ""
    first_line = entry_block[0]
    if HISTORY_ENTRY_RE.match(first_line):
        command_part = first_line.split(";", 1)[1]
        return "\n".join([command_part] + entry_block[1:])
    return "\n".join(entry_block)


def _ask_yes_no(prompt_text: str) -> bool:
    """→ Helper function to ask a yes/no question and return a boolean"""
    return Confirm.ask(prompt_text, console=console, default=False)


def read_history_file(file_path: Path) -> list[str] | None:
    """→ File I/O: Reads the history file and returns its lines, handling errors"""
    try:
        return file_path.read_text(errors="ignore").splitlines()
    except FileNotFoundError:
        _console_print(f"[error]Error: History file not found at '{file_path}'[/error]\n")
        return None
    except IOError as e:
        _console_print(f"[error]Error reading file '{file_path}': {e}[/error]\n")
        return None


def backup_and_write_history(
    history_path: Path, cleaned_lines: list[str], original_lines: list[str]
) -> None:
    """→ File I/O: Saves a backup and writes the new cleaned history file"""
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    backup_filename = history_path.parent / f".zsh_hist.clean.{timestamp}"
    try:
        with backup_filename.open("w", encoding="utf-8") as f:
            f.write("\n".join(original_lines) + "\n")
        _console_print(f"Backup saved to [info]{backup_filename}[/info]\n")
    except IOError as e:
        _console_print(f"[error]Error writing to backup file {backup_filename}: {e!r}[/error]\n")
        # Do not exit, we can still try to write the main file

    try:
        with history_path.open("w", encoding="utf-8") as f:
            f.write("\n".join(cleaned_lines) + "\n")
        _console_print(f"Cleaned history saved to [success]{history_path}[/success]\n")
    except IOError as e:
        _console_print(f"[error]Error writing to history file {history_path}: {e!r}[/error]\n")
        sys.exit(1)


# ============================================================================
# INDIVIDUAL ENTRY FLAGGING STRATEGIES
# ============================================================================


def flag_individual_multiline(all_entries: list[list[str]]) -> Iterator[tuple[int, str]]:
    """→ Individual strategy: Flags multi-line entries"""
    for i, entry_block in enumerate(all_entries):
        if len(entry_block) > 1:
            yield i, "It is a multi-line entry."


def flag_individual_empty(all_entries: list[list[str]]) -> Iterator[tuple[int, str]]:
    """→ Individual strategy: Flags empty entries"""
    for i, entry_block in enumerate(all_entries):
        first_line_command = remove_timestamp_from_entry(entry_block)
        if not first_line_command.strip():
            yield i, "It is an empty entry."


def flag_individual_blacklist(all_entries: list[list[str]]) -> Iterator[tuple[int, str]]:
    """→ Individual strategy: Flags entries matching blacklist patterns"""
    for i, entry_block in enumerate(all_entries):
        command = remove_timestamp_from_entry(entry_block)
        if match := next((pattern.search(command) for pattern in BLACKLIST_PATTERNS), None):
            yield i, f"Matches '{match.group()}'"


def flag_duplicate_groups(all_entries: list[list[str]]) -> Iterator[list[int]]:
    """→ Duplicate strategy: Groups duplicate commands, yielding a list of indices for each group."""
    command_to_indices: dict[str, list[int]] = defaultdict(list)
    for i, entry_block in enumerate(all_entries):
        command = remove_timestamp_from_entry(entry_block).strip()
        if command:
            command_to_indices[command].append(i)

    for indices in command_to_indices.values():
        if len(indices) > 1:
            yield sorted(indices)


# ============================================================================
# CLUSTER SIMILARITY DETECTION
# ============================================================================


def are_commands_similar_jaccard(cmd1: str, cmd2: str) -> bool:
    """→ Similarity check: Token-based Jaccard similarity"""
    tokens1 = set(re.split(r"[/ \s]+", cmd1))
    tokens2 = set(re.split(r"[/ \s]+", cmd2))
    intersection = tokens1.intersection(tokens2)
    union = tokens1.union(tokens2)
    if not union:
        return True  # Both empty
    jaccard_similarity = len(intersection) / len(union)
    return jaccard_similarity >= JACCARD_SIMILARITY_THRESHOLD


def are_commands_similar_difflib(cmd1: str, cmd2: str) -> bool:
    """→ Similarity check: Token-based difflib ratio"""
    if not cmd1.strip() or not cmd2.strip():
        return False

    tokens1 = set(re.split(r"[/ \s]+", cmd1))
    tokens2 = set(re.split(r"[/ \s]+", cmd2))

    if not tokens1 or not tokens2:
        return False

    intersection = tokens1.intersection(tokens2)
    diff1_to_2 = tokens1.difference(tokens2)
    diff2_to_1 = tokens2.difference(tokens1)

    sorted_intersection = " ".join(sorted(intersection))
    sorted_diff1_to_2 = " ".join(sorted(diff1_to_2))
    sorted_diff2_to_1 = " ".join(sorted(diff2_to_1))

    # Constructing strings for comparison
    t1 = f"{sorted_intersection} {sorted_diff1_to_2}".strip()
    t2 = f"{sorted_intersection} {sorted_diff2_to_1}".strip()

    # Ratios to check
    ratio1 = difflib.SequenceMatcher(None, sorted_intersection, t1).ratio()
    ratio2 = difflib.SequenceMatcher(None, sorted_intersection, t2).ratio()
    ratio3 = difflib.SequenceMatcher(None, t1, t2).ratio()

    return max(ratio1, ratio2, ratio3) >= DIFFLIB_SIMILARITY_THRESHOLD


# ============================================================================
# CLUSTER FLAGGING STRATEGIES
# ============================================================================


def flag_cluster_jaccard_similarity(all_entries: list[list[str]]) -> Iterator[tuple[int, int]]:
    """→ Cluster strategy: Groups similar commands using Jaccard similarity with lookahead"""
    commands = [remove_timestamp_from_entry(entry).strip() for entry in all_entries]
    if len(commands) < 2:
        return

    i = 0
    while i < len(commands):
        current_cluster_indices = [i]
        last_successful_match_j = i
        for j in range(i + 1, len(commands)):
            if (j - last_successful_match_j) > MAX_CLUSTER_LOOKAHEAD:
                break
            is_similar_to_cluster = False
            for cluster_member_index in current_cluster_indices:
                cmd1 = commands[cluster_member_index]
                cmd2 = commands[j]
                if cmd1 and cmd2 and are_commands_similar_jaccard(cmd1, cmd2):
                    is_similar_to_cluster = True
                    break
            if is_similar_to_cluster:
                for k in range(last_successful_match_j + 1, j + 1):
                    current_cluster_indices.append(k)
                last_successful_match_j = j
        if len(current_cluster_indices) > 1:
            start_index = current_cluster_indices[0]
            end_index = current_cluster_indices[-1]
            yield start_index, end_index
            i = end_index + 1
        else:
            i += 1


def flag_cluster_difflib_similarity(all_entries: list[list[str]]) -> Iterator[tuple[int, int]]:
    """→ Cluster strategy: Groups similar commands using simple adjacent-pair difflib checks"""
    commands = [remove_timestamp_from_entry(entry).strip() for entry in all_entries]
    if len(commands) < 2:
        return

    i = 0
    while i < len(commands) - 1:
        j = i
        while (
            j < len(commands) - 1
            and commands[j]
            and commands[j + 1]
            and are_commands_similar_difflib(commands[j], commands[j + 1])
        ):
            j += 1
        if j > i:
            yield i, j
            i = j + 1
        else:
            i += 1


# ============================================================================
# PROCESSING & MERGING
# ============================================================================


def merge_flagged_entries(flagged_entries: list[BaseFlag]) -> list[BaseFlag]:
    """→ Processing: Merges and de-duplicates flags"""
    # For LATER: This "god function" knows too much about each flag type's internals.
    # Adding more flag subclasses will require extending its if-isinstance branches,
    # creating a maintenance bottleneck.
    # Consider giving each flag type a class method for merging within
    # its own kind (e.g., ClusterFlag.merge_overlaps(list_of_clusters)),
    # then have merge_flagged_entries coordinate at a higher level using a type registry.
    # This encapsulates type-specific logic and simplifies the central merger.

    if not flagged_entries:
        return []

    # 1. Separate flags by type
    individual_flags: dict[int, IndividualFlag] = {}
    cluster_flags: list[ClusterFlag] = []
    duplicate_flags: list[DuplicateFlag] = []

    for entry in flagged_entries:
        if isinstance(entry, IndividualFlag):
            if entry.entry_index in individual_flags:
                # Merge reasons if the same entry is flagged multiple times
                existing_reasons = individual_flags[entry.entry_index].reason_text
                new_reasons = entry.reason_text
                individual_flags[
                    entry.entry_index
                ].reason_text = f"{existing_reasons}\n{new_reasons}"
            else:
                individual_flags[entry.entry_index] = entry
        elif isinstance(entry, ClusterFlag):
            cluster_flags.append(entry)
        elif isinstance(entry, DuplicateFlag):
            duplicate_flags.append(entry)

    # 2. Merge overlapping clusters
    merged_clusters: list[ClusterFlag] = []
    if cluster_flags:
        cluster_flags.sort(key=lambda flag: flag.start_index)
        current_cluster = cluster_flags[0]
        for next_cluster in cluster_flags[1:]:
            if next_cluster.start_index <= current_cluster.end_index + 1:
                current_cluster.end_index = max(current_cluster.end_index, next_cluster.end_index)
                if next_cluster.reason_text not in current_cluster.reason_text:
                    current_cluster.reason_text += f" / {next_cluster.reason_text}"
            else:
                merged_clusters.append(current_cluster)
                current_cluster = next_cluster
        merged_clusters.append(current_cluster)

    # 3. Filter out other flags that are now inside a merged cluster
    final_flags: list[BaseFlag] = list(merged_clusters)
    cluster_indices = set()
    for cluster in merged_clusters:
        cluster_indices.update(cluster.get_all_covered_indices())

    for index, individual_flag in individual_flags.items():
        if index not in cluster_indices:
            final_flags.append(individual_flag)

    for dup_flag in duplicate_flags:
        valid_indices = [
            i
            for i in dup_flag.entry_indices
            if i not in cluster_indices and i not in individual_flags
        ]
        if len(valid_indices) > 1:
            dup_flag.entry_indices = valid_indices
            final_flags.append(dup_flag)

    # 4. Return a single, sorted list of flags
    return sorted(final_flags, key=lambda flag: flag.get_sort_key())


def filter_flags_by_hist_keep(
    flagged_entries: list[BaseFlag], all_entries: list[list[str]]
) -> list[BaseFlag]:
    """→ Processing: Filters flags to exclude entries marked with HIST:KEEP"""

    def has_hist_keep(index: int) -> bool:
        if index >= len(all_entries):
            return False
        command = remove_timestamp_from_entry(all_entries[index])
        return bool(re.search(r"# *HIST:KEEP", command, re.IGNORECASE))

    filtered_flags = []

    for flag in flagged_entries:
        if isinstance(flag, IndividualFlag):
            # Remove individual flags for HIST:KEEP entries
            if not has_hist_keep(flag.entry_index):
                filtered_flags.append(flag)

        elif isinstance(flag, ClusterFlag):
            # For clusters, check if any entries being removed have HIST:KEEP
            indices_to_remove = set(range(flag.start_index, flag.end_index))
            hist_keep_indices = {i for i in indices_to_remove if has_hist_keep(i)}

            # If no HIST:KEEP entries in the removal set, keep the flag as-is
            if not hist_keep_indices:
                filtered_flags.append(flag)
            # If all removal entries have HIST:KEEP, drop the flag entirely
            elif hist_keep_indices == indices_to_remove:
                continue
            # If some have HIST:KEEP, we could adjust the cluster, but for simplicity, keep the flag
            # (the actual removal will be filtered later in calculate_indices_to_remove)
            else:
                filtered_flags.append(flag)

        elif isinstance(flag, DuplicateFlag):
            # Remove HIST:KEEP entries from the duplicate list, but keep the last entry
            non_hist_keep_indices = [i for i in flag.entry_indices if not has_hist_keep(i)]

            # If we still have duplicates after filtering, keep the flag with updated indices
            if len(non_hist_keep_indices) > 1:
                flag.entry_indices = non_hist_keep_indices
                filtered_flags.append(flag)
            # If only one or zero entries remain, drop the flag

    return filtered_flags


def calculate_indices_to_remove(
    approved_flags: list[BaseFlag], all_entries: list[list[str]]
) -> set[int]:
    """→ Processing: Converts approved flags into a set of indices to remove, with final HIST:KEEP safety check"""
    indices_to_remove = set()
    for flag in approved_flags:
        indices_to_remove.update(flag.get_indices_to_remove())

    # Final safety check: remove any HIST:KEEP entries that might have slipped through (e.g., in mixed clusters)
    filtered_indices = set()
    for index in indices_to_remove:
        if index < len(all_entries):
            command = remove_timestamp_from_entry(all_entries[index])
            if not re.search(r"# *HIST:KEEP", command, re.IGNORECASE):
                filtered_indices.add(index)
        else:
            filtered_indices.add(index)  # Keep invalid indices for error handling elsewhere

    return filtered_indices


# ============================================================================
# USER INTERFACE & DISPLAY
# ============================================================================


def display_and_confirm_all_changes(flagged_entries: list[BaseFlag]) -> bool:
    """→ UI: Displays all unique, merged changes and gets a single user confirmation"""
    if not flagged_entries:
        return False

    num_changes = len(flagged_entries)
    _console_print(Rule(f"[bold]Found {num_changes} potential change(s)[/bold]"))

    for i, entry in enumerate(flagged_entries, 1):
        _console_print()
        _console_print(Rule(f"Change {i} of {num_changes}", style="rule", characters="─"))
        _console_print(entry.render())

    console.print()
    return _ask_yes_no(f"Apply all {num_changes} changes above?")


class Entry(Horizontal):
    """A single entry row in the flag display."""

    DEFAULT_CSS = """
    Entry {
        layout: horizontal;
        height: auto;
    }
    Entry:focus {
        background: #FF4500 20%;
    }
    Entry.context {
        color: #5C6370;
    }
    Entry .line-num {
        width: auto;
        text-align: right;
        color: #3A3F4C;
        padding: 0 1;
    }
    Entry .marker {
        width: 2;
        text-align: right;
    }
    Entry .marker.plus {
        color: #61AFEF;
    }
    Entry .marker.minus {
        color: #E06C75;
    }
    Entry .content {
        padding: 0 1;
    }
    """

    can_focus = True


class FlagWidget(Widget):
    """A widget to display a single flag with composable entry rows."""

    DEFAULT_CSS = """
    FlagWidget {
        padding: 0 1;
        margin: 1 2;
        border: round $primary;
    }
    FlagWidget:focus {
        border: round #FF4500;
    }
    FlagWidget.disabled {
        border: round #5C6370;
    }
    FlagWidget .entries {
        height: auto;
    }
    """

    def __init__(self, flag: BaseFlag, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.flag = flag
        self.entry_widgets: list[Entry] = []

    def compose(self) -> ComposeResult:
        meta_table = Table.grid(padding=(0, 1, 1, 2))
        meta_table.add_column(style=Style.parse("bold #98C379"))
        meta_table.add_column()
        meta_table.add_row("Reason:", self.flag.reason_text)
        if isinstance(self.flag, (ClusterFlag, DuplicateFlag)):
            meta_table.add_row(
                "Action:",
                RichText("Keep only the last entry in the sequence", style="italic #61AFEF"),
            )
        elif isinstance(self.flag, IndividualFlag):
            meta_table.add_row(
                "Action:",
                RichText("Remove this entry", style="italic #61AFEF"),
            )

        yield Static(meta_table)
        yield Static(Rule(style="#4B5263"))

        with Vertical(classes="entries"):
            for (
                line_num_str,
                marker,
                content,
                is_context,
                is_kept,
            ) in self.flag.get_render_entries():
                with Entry(classes="context" if is_context else ""):
                    yield Label(line_num_str, classes="line-num")
                    yield Label(marker, classes=f"marker {'plus' if is_kept else 'minus'}")
                    yield Static(content, classes="content")

    def on_mount(self):
        self.entry_widgets = [e for e in self.query(Entry) if 'context' not in e.classes]


class HistoryCleanApp(App[list[BaseFlag]]):
    CSS = """
    .panel {
        margin: 1 2;
        border: round $primary;
    }
    .panel:focus {
        border: round #FF4500;
    }
    .panel.disabled {
        border: round #5C6370;
    }
    """

    mode = reactive("flag")
    current_flag: FlagWidget | None = None
    current_entries: list[Entry] = []

    def __init__(self, flagged_entries: list[BaseFlag], *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.flagged_entries = flagged_entries
        self.panels: list[FlagWidget] = []
        self.scroll_container: VerticalScroll | None = None
        self.flag_states: dict[BaseFlag, bool] = {flag: True for flag in flagged_entries}

    BINDINGS = [
        Binding("up", "focus_previous", "Focus previous", priority=True),
        Binding("down", "focus_next", "Focus next", priority=True),
        Binding("space", "toggle_panel", "Toggle panel"),
        Binding("enter", "enter_entry_mode", "Enter Entry Mode"),
        Binding("escape", "exit_entry_mode", "Exit Entry Mode", show=False),
        ("y", "approve", "Approve all changes"),
        ("n", "reject", "Reject changes"),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        self.scroll_container = NonScrollableVerticalScroll()
        with self.scroll_container:
            for entry in self.flagged_entries:
                panel_widget = FlagWidget(entry, classes="panel")
                yield panel_widget
                panel_widget.flag = entry
                self.panels.append(panel_widget)
        yield Footer()

    def on_mount(self):
        if self.panels:
            self.panels[0].focus()
            if self.scroll_container:
                self.scroll_container.scroll_to_center(self.panels[0], animate=False)

    @on(Focus)
    def handle_focus(self, event: Focus):
        if self.scroll_container:
            self.scroll_container.scroll_to_center(event.widget)

    def get_current_panel_index(self) -> int:
        focused = self.focused
        if isinstance(focused, FlagWidget):
            return self.panels.index(focused)
        return 0

    def action_focus_previous(self):
        if not self.panels:
            return
        if self.mode == "flag":
            current_idx = self.get_current_panel_index()
            next_idx = (current_idx - 1) % len(self.panels)
            self.panels[next_idx].focus()
        elif self.mode == "entry" and self.current_entries:
            focused = self.focused
            if isinstance(focused, Entry):
                current_idx = self.current_entries.index(focused)
                if current_idx > 0:
                    self.current_entries[current_idx - 1].focus()

    def action_focus_next(self):
        if not self.panels:
            return
        if self.mode == "flag":
            current_idx = self.get_current_panel_index()
            next_idx = (current_idx + 1) % len(self.panels)
            self.panels[next_idx].focus()
        elif self.mode == "entry" and self.current_entries:
            focused = self.focused
            if isinstance(focused, Entry):
                current_idx = self.current_entries.index(focused)
                if current_idx < len(self.current_entries) - 1:
                    self.current_entries[current_idx + 1].focus()

    def action_toggle_panel(self):
        if self.mode == "flag":
            focused = self.focused
        elif self.mode == "entry" and self.current_flag:
            focused = self.current_flag
        else:
            return

        if isinstance(focused, FlagWidget) and (flag := focused.flag):
            self.flag_states[flag] = not self.flag_states[flag]
            if self.flag_states[flag]:
                focused.remove_class("disabled")
            else:
                focused.add_class("disabled")

    def action_enter_entry_mode(self):
        focused = self.focused
        if self.mode == "flag" and isinstance(focused, FlagWidget):
            self.mode = "entry"
            self.current_flag = focused
            self.current_entries = focused.entry_widgets
            if self.current_entries:
                self.current_entries[0].focus()
                if self.scroll_container:
                    self.scroll_container.scroll_to_center(self.current_entries[0])

    def action_exit_entry_mode(self):
        if self.mode == "entry" and self.current_flag:
            self.mode = "flag"
            self.current_flag.focus()
            if self.scroll_container:
                self.scroll_container.scroll_to_center(self.current_flag)
            self.current_entries = []

    def action_approve(self):
        approved_flags = [flag for flag, enabled in self.flag_states.items() if enabled]
        self.exit(approved_flags)

    def action_reject(self):
        self.exit([])


def main() -> None:
    """→ Main: Orchestrates the entire cleaning pipeline"""
    if len(sys.argv) > 1:
        history_file_path = Path(sys.argv[1])
    else:
        history_file_path = Path.home() / ".zsh_history"

    original_lines = read_history_file(history_file_path)
    if original_lines is None:
        sys.exit(1)

    all_entries_with_lines = list(parse_history_entries(original_lines))
    all_entries = [block for _, block in all_entries_with_lines]
    entry_line_nums = [line_num for line_num, _ in all_entries_with_lines]
    max_line_num_width = len(str(len(original_lines)))

    # --- Common data for all flag instances ---
    flag_context = {
        "all_entries": all_entries,
        "entry_line_nums": entry_line_nums,
        "max_line_num_width": max_line_num_width,
    }

    # --- Declarative pipeline definition ---
    pipeline_steps = [
        {
            "flag_class": IndividualFlag,
            "strategy": strategy,
        }
        for strategy in CONFIG.individual_strategies
    ]
    pipeline_steps.extend(
        {
            "flag_class": ClusterFlag,
            "strategy": strategy,
            "reason": reason,
        }
        for strategy, reason in CONFIG.cluster_strategies
    )
    pipeline_steps.append({
        "flag_class": DuplicateFlag,
        "strategy": CONFIG.duplicate_strategy,
        "reason": "Duplicate command; keeping the last instance",
    })

    # --- PHASE 1: COLLECT ---
    raw_flagged_entries: list[BaseFlag] = []
    for step in pipeline_steps:
        FlagClass = step["flag_class"]
        strategy = step["strategy"]
        reason = step.get("reason", "")

        for result in strategy(all_entries):
            # The structure of `result` depends on the strategy
            if FlagClass is IndividualFlag:
                index, single_reason = result
                # We group reasons later in merge, so start with a list
                flag = IndividualFlag(entry_index=index, reasons=[single_reason], **flag_context)
            elif FlagClass is ClusterFlag:
                start, end = result
                flag = ClusterFlag(
                    start_index=start, end_index=end, reason_text=reason, **flag_context
                )
            elif FlagClass is DuplicateFlag:
                indices = result
                flag = DuplicateFlag(entry_indices=indices, reason_text=reason, **flag_context)
            else:
                continue
            raw_flagged_entries.append(flag)

    # --- PHASE 2: MERGE & FILTER ---
    merged_flagged_entries = merge_flagged_entries(raw_flagged_entries)
    final_flagged_entries = filter_flags_by_hist_keep(merged_flagged_entries, all_entries)

    if not final_flagged_entries:
        _console_print("[success]No entries needed cleaning. History file unchanged.[/success]")
        return

    # --- PHASE 3: CONFIRM & APPLY ---
    app = HistoryCleanApp(final_flagged_entries)
    approved_flags = app.run() or []

    if not approved_flags:
        _console_print("[warning]No changes applied. History file unchanged.[/warning]")
        return

    indices_to_remove = calculate_indices_to_remove(approved_flags, all_entries)

    # Build the final list of entries by keeping those not in the removal set.
    final_cleaned_entries = [
        entry for i, entry in enumerate(all_entries) if i not in indices_to_remove
    ]

    if len(all_entries) == len(final_cleaned_entries):
        _console_print(
            "\n[warning]Approval given, but no entries were ultimately removed. History file unchanged.[/warning]"
        )
        return

    cleaned_lines = [line for entry in final_cleaned_entries for line in entry]

    backup_and_write_history(history_file_path, cleaned_lines, original_lines)

    removed_count = len(all_entries) - len(final_cleaned_entries)
    _console_print(f"[success]Cleaned history: removed {removed_count} entries.[/success]")


if __name__ == "__main__":
    main()

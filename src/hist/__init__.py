"""Tools for cleaning and inspecting zsh history files."""

from .histclean import (
    HistoryCheckResult,
    check,
    clean,
    console,
    inspect_history_file,
    inspect_history_files,
)

__all__ = [
    "HistoryCheckResult",
    "check",
    "clean",
    "console",
    "inspect_history_file",
    "inspect_history_files",
]

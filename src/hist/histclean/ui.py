from __future__ import annotations

import sys

from rich.console import Console
from rich.prompt import Confirm
from rich.rule import Rule
from rich.theme import Theme
from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.events import Focus
from textual.widgets import Footer, Header, Static

from .core import BaseFlag

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


def _console_print(string: str = "", *args, **kwargs) -> None:
    """Print with Rich and fall back to stderr on failure."""
    try:
        console.print(string, *args, **kwargs)
    except Exception:
        kwargs.setdefault("file", sys.stderr)
        cleaned_kwargs = {
            key: value
            for key, value in kwargs.items()
            if key not in ["sep", "file", "end", "flush"]
        }
        print(string, *args, **cleaned_kwargs)


def _ask_yes_no(prompt_text: str) -> bool:
    """Ask a yes or no question and return the answer."""
    return Confirm.ask(prompt_text, console=console, default=False)


def display_and_confirm_all_changes(flagged_entries: list[BaseFlag]) -> bool:
    """Display merged changes and ask for a single confirmation."""
    if not flagged_entries:
        return False

    change_count = len(flagged_entries)
    _console_print(Rule(f"[bold]Found {change_count} potential change(s)[/bold]"))

    for index, entry in enumerate(flagged_entries, start=1):
        _console_print()
        _console_print(
            Rule(f"Change {index} of {change_count}", style="rule", characters="─")
        )
        _console_print(entry.render())

    console.print()
    return _ask_yes_no(f"Apply all {change_count} changes above?")


class NonScrollableVerticalScroll(VerticalScroll):
    BINDINGS = [  # noqa: RUF012
        binding
        for binding in VerticalScroll.BINDINGS
        if binding.key not in ["up", "down", "pageup", "pagedown", "home", "end"]
    ]


class FocusableStatic(Static):
    can_focus = True
    flag: BaseFlag | None = None


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

    BINDINGS = [  # noqa: RUF012
        Binding("up", "focus_previous_panel", "Focus previous panel", priority=True),
        Binding("down", "focus_next_panel", "Focus next panel", priority=True),
        Binding("space", "toggle_panel", "Toggle panel"),
        ("y", "approve", "Approve all changes"),
        ("n", "reject", "Reject changes"),
    ]

    def __init__(self, flagged_entries: list[BaseFlag], *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.flagged_entries = flagged_entries
        self.panels: list[FocusableStatic] = []
        self.scroll_container: VerticalScroll | None = None
        self.flag_states: dict[BaseFlag, bool] = {
            flag: True for flag in flagged_entries
        }

    def compose(self) -> ComposeResult:
        yield Header()
        self.scroll_container = NonScrollableVerticalScroll()
        with self.scroll_container:
            for entry in self.flagged_entries:
                panel_widget = FocusableStatic(entry.render(), classes="panel")
                panel_widget.flag = entry
                self.panels.append(panel_widget)
                yield panel_widget
        yield Footer()

    def on_mount(self) -> None:
        if not self.panels:
            return
        self.panels[0].focus()
        if self.scroll_container:
            self.scroll_container.scroll_to_center(self.panels[0], animate=False)

    @on(Focus)
    def handle_focus(self, event: Focus) -> None:
        if event.widget in self.panels and self.scroll_container:
            self.scroll_container.scroll_to_center(event.widget)

    def get_current_index(self) -> int:
        focused = self.focused
        if focused in self.panels:
            return self.panels.index(focused)
        return 0

    def action_focus_previous_panel(self) -> None:
        if not self.panels:
            return
        current_index = self.get_current_index()
        next_index = (current_index - 1) % len(self.panels)
        self.panels[next_index].focus()

    def action_focus_next_panel(self) -> None:
        if not self.panels:
            return
        current_index = self.get_current_index()
        next_index = (current_index + 1) % len(self.panels)
        self.panels[next_index].focus()

    def action_toggle_panel(self) -> None:
        focused = self.focused
        if not isinstance(focused, FocusableStatic) or not focused.flag:
            return
        flag = focused.flag
        self.flag_states[flag] = not self.flag_states[flag]
        if self.flag_states[flag]:
            focused.remove_class("disabled")
            return
        focused.add_class("disabled")

    def action_approve(self) -> None:
        approved_flags = [flag for flag, enabled in self.flag_states.items() if enabled]
        self.exit(approved_flags)

    def action_reject(self) -> None:
        self.exit([])

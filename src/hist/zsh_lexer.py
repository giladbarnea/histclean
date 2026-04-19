# ============================================================================
# ZSH LEXER
# ============================================================================

from __future__ import annotations

import re

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
from rich.style import Style
from rich.syntax import SyntaxTheme
from textual.containers import VerticalScroll


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

from .analysis import AnalysisResult, HistoryFile, OptimalSegment, Sequence, analyze_all, discover_files
from .cli import main
from .html import generate_html, output_html
from .terminal import output_terminal

__all__ = [
    "AnalysisResult",
    "HistoryFile",
    "OptimalSegment",
    "Sequence",
    "analyze_all",
    "discover_files",
    "generate_html",
    "main",
    "output_html",
    "output_terminal",
]

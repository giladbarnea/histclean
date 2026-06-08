from __future__ import annotations

import os
import re
from collections.abc import Iterable
from pathlib import Path

SNAP_RE = re.compile(r"^\.zsh_history\.(?:shrinkbackup\.)?(\d+)$")
BACKUP_RE = re.compile(r"^\d+$")
CLEAN_RE = re.compile(
    r"^\.zsh_hist\.clean\.\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}(?:_\d{6})?$"
)
EXTRA_DOT_HISTORY_NAMES = {".zsh_history.merged", ".zsh_history.prevsnapshot"}
SUFFIX_HISTORY_RE = re.compile(r"^.+\.zsh_history$")


def detect_sort_key(path: Path) -> tuple[int, str]:
    """Return a chronological-ish sort key for history files."""
    if match := SNAP_RE.match(path.name):
        return int(match.group(1)), path.name
    if BACKUP_RE.match(path.name):
        return int(path.name), path.name
    try:
        return int(path.stat().st_mtime), path.name
    except (FileNotFoundError, OSError):
        return 0, path.name


def _is_discoverable_history_file(
    path: Path,
    *,
    include_clean_outputs: bool = False,
    include_all: bool = False,
    in_backups_dir: bool = False,
) -> bool:
    name = path.name

    if name == ".zsh_history":
        return True
    if SNAP_RE.match(name):
        return True
    if in_backups_dir and BACKUP_RE.match(name):
        return True
    if include_clean_outputs and CLEAN_RE.match(name):
        return True
    if not include_all:
        return False
    if CLEAN_RE.match(name):
        return True
    if name in EXTRA_DOT_HISTORY_NAMES:
        return True
    return bool(SUFFIX_HISTORY_RE.match(name))


def discover_history_files(
    raw_paths: Iterable[str] | None = None,
    *,
    cwd: Path | None = None,
    home: Path | None = None,
    include_clean_outputs: bool = False,
    include_all: bool = False,
) -> list[Path]:
    """Discover history files for histclean, histmerge, and histcompare."""
    cwd = Path.cwd() if cwd is None else cwd
    home = Path.home() if home is None else home

    if raw_paths:
        paths = [Path(os.path.expanduser(path)) for path in raw_paths]
    else:
        from glob import glob as _glob

        glob_patterns = [".zsh_history.*"]
        if include_clean_outputs or include_all:
            glob_patterns.append(".zsh_hist.clean.*")
        if include_all:
            glob_patterns.extend(["*.zsh_history", ".*.zsh_history"])

        paths: list[Path] = []
        for root in (cwd, home):
            for pattern in glob_patterns:
                matches = {Path(match) for match in _glob(str(root / pattern))}
                paths.extend(
                    path
                    for path in matches
                    if _is_discoverable_history_file(
                        path,
                        include_clean_outputs=include_clean_outputs,
                        include_all=include_all,
                    )
                )

        backups_dir = home / ".zsh_history_backups"
        if backups_dir.is_dir():
            paths.extend(
                path
                for path in backups_dir.iterdir()
                if path.is_file()
                and _is_discoverable_history_file(
                    path,
                    include_clean_outputs=include_clean_outputs,
                    include_all=include_all,
                    in_backups_dir=True,
                )
            )

        live_cwd = cwd / ".zsh_history"
        live_home = home / ".zsh_history"
        if live_cwd.exists():
            paths.append(live_cwd)
        elif live_home.exists():
            paths.append(live_home)

    deduped_paths: dict[str, Path] = {}
    for path in paths:
        try:
            dedupe_key = str(path.resolve())
        except OSError:
            dedupe_key = str(path)
        deduped_paths.setdefault(dedupe_key, path)

    return sorted(deduped_paths.values(), key=detect_sort_key)

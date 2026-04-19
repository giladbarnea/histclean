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


def discover_history_files(
    raw_paths: Iterable[str] | None = None,
    *,
    cwd: Path | None = None,
    home: Path | None = None,
    include_clean_outputs: bool = False,
) -> list[Path]:
    """Discover history files for histclean, histmerge, and histcompare."""
    cwd = Path.cwd() if cwd is None else cwd
    home = Path.home() if home is None else home

    if raw_paths:
        paths = [Path(os.path.expanduser(path)) for path in raw_paths]
    else:
        from glob import glob as _glob

        snapshot_matches = {
            Path(match) for match in _glob(str(cwd / ".zsh_history.*"))
        } | {Path(match) for match in _glob(str(home / ".zsh_history.*"))}
        paths = [path for path in snapshot_matches if SNAP_RE.match(path.name)]

        if include_clean_outputs:
            clean_matches = {
                Path(match) for match in _glob(str(cwd / ".zsh_hist.clean.*"))
            } | {Path(match) for match in _glob(str(home / ".zsh_hist.clean.*"))}
            paths.extend(path for path in clean_matches if CLEAN_RE.match(path.name))

        backups_dir = home / ".zsh_history_backups"
        if backups_dir.is_dir():
            paths.extend(
                path
                for path in backups_dir.iterdir()
                if path.is_file() and BACKUP_RE.match(path.name)
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

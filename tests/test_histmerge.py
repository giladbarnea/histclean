from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from hist import histmerge


class BrokenPipeOutput:
    def write(self, value: str) -> int:
        raise BrokenPipeError

    def flush(self) -> None:
        pass


class HistmergeCleanupTest(unittest.TestCase):
    def test_cleanup_removes_only_selected_backups(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            home = Path(temporary_directory)
            live_history = home / ".zsh_history"
            selected_backup = home / ".zsh_history.1"
            unselected_backup = home / ".zsh_hist.clean.unselected"
            live_history.write_text(": 3:0;third\n", encoding="utf-8")
            selected_backup.write_text(": 2:0;second\n: 1:0;first\n", encoding="utf-8")
            unselected_backup.write_text(": 4:0;fourth\n", encoding="utf-8")
            output = io.StringIO()

            with (
                patch.object(
                    histmerge, "ensure_histories_are_clean", return_value=True
                ),
                redirect_stdout(output),
                redirect_stderr(io.StringIO()),
            ):
                status = histmerge.main([
                    "--cleanup",
                    str(selected_backup),
                    str(live_history),
                ])

            self.assertEqual(status, 0)
            self.assertEqual(
                output.getvalue(),
                ": 1:0;first\n: 2:0;second\n: 3:0;third\n",
            )
            self.assertFalse(selected_backup.exists())
            self.assertTrue(live_history.exists())
            self.assertTrue(unselected_backup.exists())

    def test_cleanup_defaults_to_false(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            selected_backup = Path(temporary_directory) / ".zsh_history.1"
            selected_backup.write_text(": 1:0;first\n", encoding="utf-8")

            with (
                patch.object(
                    histmerge, "ensure_histories_are_clean", return_value=True
                ),
                redirect_stdout(io.StringIO()),
                redirect_stderr(io.StringIO()),
            ):
                status = histmerge.main([str(selected_backup)])

            self.assertEqual(status, 0)
            self.assertTrue(selected_backup.exists())

    def test_cleanup_removes_empty_backup_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            home = Path(temporary_directory)
            backup_directory = home / ".zsh_history_backups"
            backup_directory.mkdir()
            selected_backup = backup_directory / "123"
            selected_backup.write_text(": 1:0;first\n", encoding="utf-8")

            with redirect_stderr(io.StringIO()):
                histmerge.remove_merged_source_files([selected_backup])

            self.assertFalse(backup_directory.exists())

    def test_cleanup_keeps_unselected_backup_directory_contents(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            home = Path(temporary_directory)
            backup_directory = home / ".zsh_history_backups"
            backup_directory.mkdir()
            selected_backup = backup_directory / "123"
            unselected_file = backup_directory / "notes"
            selected_backup.write_text(": 1:0;first\n", encoding="utf-8")
            unselected_file.write_text("keep me\n", encoding="utf-8")

            with redirect_stderr(io.StringIO()):
                histmerge.remove_merged_source_files([selected_backup])

            self.assertFalse(selected_backup.exists())
            self.assertTrue(unselected_file.exists())
            self.assertTrue(backup_directory.exists())

    def test_cleanup_keeps_sources_when_output_breaks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            selected_backup = Path(temporary_directory) / ".zsh_history.1"
            selected_backup.write_text(": 1:0;first\n", encoding="utf-8")

            with (
                patch.object(
                    histmerge, "ensure_histories_are_clean", return_value=True
                ),
                patch.object(histmerge.sys, "stdout", BrokenPipeOutput()),
                redirect_stderr(io.StringIO()),
            ):
                status = histmerge.main(["--cleanup", str(selected_backup)])

            self.assertEqual(status, 0)
            self.assertTrue(selected_backup.exists())

    def test_cleanup_is_invalid_with_dry_run(self) -> None:
        with (
            self.assertRaises(SystemExit) as raised,
            redirect_stderr(io.StringIO()),
        ):
            histmerge.main(["--cleanup", "--dry-run"])

        self.assertEqual(raised.exception.code, 2)


if __name__ == "__main__":
    unittest.main()

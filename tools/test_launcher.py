"""Contract tests for the macOS POSIX launcher."""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import unittest


ROOT = Path(__file__).parent.parent
LAUNCHER = ROOT / "harness"


class LauncherTests(unittest.TestCase):
    def test_launcher_resolves_repository_and_python_fallbacks(self) -> None:
        self.assertTrue(LAUNCHER.is_file(), "macOS launcher is missing")
        text = LAUNCHER.read_text(encoding="utf-8")
        for fragment in (
            "#!/bin/sh",
            'SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)',
            'command -v python3',
            'command -v python',
            'exec python3 "$SCRIPT_DIR/tools/harness.py" "$@"',
            'exec python "$SCRIPT_DIR/tools/harness.py" "$@"',
            "exit 127",
        ):
            self.assertIn(fragment, text)

    def test_launcher_has_valid_shell_syntax_when_shell_is_available(self) -> None:
        shell = shutil.which("sh")
        if shell is None:
            self.skipTest("POSIX shell unavailable on this host")
        result = subprocess.run([shell, "-n", str(LAUNCHER)], capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)

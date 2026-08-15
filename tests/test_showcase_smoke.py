"""Black-box test for the documented showcase smoke command."""
import subprocess
import sys


def test_showcase_smoke_command_exercises_web_and_mcp():
    result = subprocess.run(
        [sys.executable, "scripts/smoke_showcase.py"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "showcase smoke check passed" in result.stdout.lower()

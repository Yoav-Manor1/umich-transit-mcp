"""The poller container fails closed when initialization cannot finish."""

import os
import subprocess
from pathlib import Path

ENTRYPOINT = Path(__file__).parents[2] / "deploy" / "entrypoint.sh"


def test_entrypoint_does_not_start_poller_after_seed_failure(tmp_path):
    calls = tmp_path / "calls.log"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_uv = fake_bin / "uv"
    fake_uv.write_text(
        "#!/bin/sh\n"
        'printf "%s\\n" "$*" >> "$CALLS_LOG"\n'
        'case "$*" in\n'
        '  "run python scripts/seed_static_data.py") exit 9 ;;\n'
        "  *) exit 0 ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    fake_uv.chmod(0o755)
    env = {
        **os.environ,
        "CALLS_LOG": str(calls),
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
    }

    result = subprocess.run(
        ["sh", os.fspath(ENTRYPOINT)],
        cwd=os.fspath(tmp_path),
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 9
    assert "run umich-transit-poller" not in calls.read_text(encoding="utf-8")

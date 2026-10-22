"""Regression tests for development scripts."""

import os
import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize("status", [0, 1, 4])
def test_coverage_preserves_test_exit_status(tmp_path, status):
    script = Path(__file__).resolve().parents[1] / "scripts" / "coverage.sh"
    bin_dir = tmp_path / ".venv" / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "activate").touch()
    pytest_stub = bin_dir / "pytest"
    pytest_stub.write_text(f"#!/bin/sh\necho 'test output'\nexit {status}\n")
    pytest_stub.chmod(0o755)

    result = subprocess.run(
        ["bash", str(script), "pillow_degas"],
        check=False,
        cwd=tmp_path,
        env={**os.environ, "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"]},
        capture_output=True,
        text=True,
    )

    assert result.returncode == status, result.stderr
    assert (tmp_path / "htmlcov" / "coverage_report.txt").read_text() == "test output\n"

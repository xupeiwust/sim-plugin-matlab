"""Build the wheel and assert that bundled skill files ship."""
from __future__ import annotations

import subprocess
import sys
import zipfile
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.integration
def test_wheel_contains_skills(tmp_path: Path) -> None:
    out_dir = tmp_path / "dist"
    out_dir.mkdir()

    proc = subprocess.run(
        [sys.executable, "-m", "build", "--wheel", "--outdir", str(out_dir)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert proc.returncode == 0, f"build failed: {proc.stderr[-2000:]}"

    wheels = list(out_dir.glob("sim_plugin_matlab-*.whl"))
    assert len(wheels) == 1, f"expected one wheel, got {wheels}"

    with zipfile.ZipFile(wheels[0]) as zf:
        names = set(zf.namelist())

    required = {
        "sim_plugin_matlab/__init__.py",
        "sim_plugin_matlab/driver.py",
        "sim_plugin_matlab/compatibility.yaml",
        "sim_plugin_matlab/matlab_pkg/+sim_shim/run.m",
        "sim_plugin_matlab/_skills/matlab/SKILL.md",
        "sim_plugin_matlab/_skills/matlab/base/driver_upgrade.md",
        "sim_plugin_matlab/_skills/matlab/base/reference/simulink.md",
        "sim_plugin_matlab/_skills/matlab/base/workflows/README.md",
        "sim_plugin_matlab/_skills/matlab/sdk/24.1/notes.md",
    }
    missing = required - names
    assert not missing, f"missing from wheel: {missing}"

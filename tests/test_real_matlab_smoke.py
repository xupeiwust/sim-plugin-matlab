"""Opt-in smoke coverage for a real MATLAB installation.

This test is intentionally skipped in ordinary CI. Enable it on a machine with
MATLAB available by setting ``SIM_MATLAB_RUN_INTEGRATION=1`` when preparing a
release or validating first-class plugin readiness.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from sim_plugin_matlab import MatlabDriver


if os.environ.get("SIM_MATLAB_RUN_INTEGRATION") != "1":
    pytest.skip(
        "set SIM_MATLAB_RUN_INTEGRATION=1 to run the real MATLAB smoke",
        allow_module_level=True,
    )


FIXTURES = Path(__file__).parent.parent / "fixtures"


def test_real_matlab_check_and_batch_script(tmp_path: Path) -> None:
    driver = MatlabDriver()
    installs = driver.detect_installed()
    assert installs, "expected MATLAB to be detected before real smoke"

    connection = driver.connect()
    assert connection.status == "ok", connection.to_dict()

    matlab_bin = installs[0].extra.get("matlab_bin")
    if matlab_bin:
        os.environ["PATH"] = (
            str(Path(matlab_bin).parent) + os.pathsep + os.environ["PATH"]
        )

    result = driver.run_file(FIXTURES / "matlab_ok.m")
    payload = driver.parse_output(result.stdout)

    evidence = {
        "install": installs[0].to_dict(),
        "connection": connection.to_dict(),
        "run": result.to_dict(),
        "payload": payload,
    }
    (tmp_path / "sim_matlab_smoke_evidence.json").write_text(
        json.dumps(evidence, indent=2, default=str),
        encoding="utf-8",
    )

    assert result.exit_code == 0, result.stderr
    assert payload["status"] == "ok"
    assert payload["value"] == 42

"""Tests for the MATLAB driver."""
from pathlib import Path
from types import SimpleNamespace

from sim_plugin_matlab import MatlabDriver

FIXTURES = Path(__file__).parent.parent / "fixtures"


class TestMatlabDetect:
    def test_detects_m_script(self):
        driver = MatlabDriver()
        assert driver.detect(FIXTURES / "matlab_ok.m") is True

    def test_detects_slx_model(self):
        driver = MatlabDriver()
        assert driver.detect(FIXTURES / "empty_model.slx") is True

    def test_detects_mdl_model(self):
        driver = MatlabDriver()
        assert driver.detect(FIXTURES / "empty_model.mdl") is True

    def test_rejects_python_script(self):
        driver = MatlabDriver()
        assert driver.detect(FIXTURES / "mock_solver.py") is False


class TestMatlabParseOutput:
    def test_parses_last_json_line(self):
        driver = MatlabDriver()
        payload = driver.parse_output("hello\n{\"status\":\"ok\",\"value\":42}\n")
        assert payload["status"] == "ok"
        assert payload["value"] == 42


class TestMatlabConnect:
    def test_reports_not_installed_when_missing(self, monkeypatch):
        from sim_plugin_matlab import driver as drv

        monkeypatch.setattr(drv, "_INSTALL_FINDERS", [lambda: []])
        driver = MatlabDriver()
        info = driver.connect()
        assert info.status == "not_installed"


class TestMatlabRunFile:
    def test_uses_matlab_batch(self, monkeypatch):
        monkeypatch.setattr(
            "sim_plugin_matlab.driver.shutil.which",
            lambda _: "/usr/local/bin/matlab",
        )

        recorded = {}

        def fake_run(command, capture_output, text):
            recorded["command"] = command
            return SimpleNamespace(returncode=0, stdout='{"status":"ok"}\n', stderr="")

        monkeypatch.setattr("sim.runner.subprocess.run", fake_run)

        driver = MatlabDriver()
        result = driver.run_file(FIXTURES / "matlab_ok.m")
        assert result.exit_code == 0
        assert recorded["command"][0] == "/usr/local/bin/matlab"
        assert recorded["command"][1] == "-batch"

    def test_slx_dispatches_via_sim_shim(self, monkeypatch, tmp_path):
        """Issue #27 Phase A: `.slx` routes through load_system → sim_shim.run
        → close_system, not through `run('...')`."""
        monkeypatch.setattr(
            "sim_plugin_matlab.driver.shutil.which",
            lambda _: "/usr/local/bin/matlab",
        )

        recorded = {}

        def fake_run(command, capture_output, text):
            recorded["command"] = command
            return SimpleNamespace(
                returncode=0,
                stdout='{"ok":true,"result_file":"/tmp/out.parquet","format":"parquet","signals":[]}\n',
                stderr="",
            )

        monkeypatch.setattr("sim.runner.subprocess.run", fake_run)

        model = tmp_path / "rc_circuit.slx"
        model.touch()

        driver = MatlabDriver()
        result = driver.run_file(model)

        assert result.exit_code == 0
        expr = recorded["command"][2]
        assert "load_system(" in expr
        assert "sim_shim.run(" in expr
        assert "close_system(" in expr
        assert "addpath(" in expr
        assert "rc_circuit" in expr
        # Does not fall back to the `.m` top-level `run('...')` wrapper
        assert not expr.startswith("run('")
        # Regression: MATLAB silently refuses to put a folder named
        # `resources` on the path (reserved name alongside `private`
        # and `@<class>`). The shim package parent must use a
        # non-reserved name, otherwise `which('sim_shim.run')` returns
        # empty inside MATLAB and dispatch fails with
        # "Unable to resolve the name 'sim_shim.run'." See the PR that
        # introduced `matlab_pkg/` for the reserved-name bug context.
        assert "/resources'" not in expr
        assert "matlab_pkg" in expr


class TestSimulinkLint:
    def test_slx_lint_is_info_only(self):
        driver = MatlabDriver()
        result = driver.lint(FIXTURES / "empty_model.slx")
        assert result.ok is True
        assert result.diagnostics
        assert result.diagnostics[0].level == "info"


class TestSimulinkProbe:
    def test_simulink_flag_populated_from_filesystem(self, tmp_path, monkeypatch):
        """detect_installed() should set extra.simulink_installed based on
        whether toolbox/simulink/simulink exists under the MATLAB root."""
        from sim_plugin_matlab import driver as drv

        matlab_root = tmp_path / "R2024a"
        (matlab_root / "bin").mkdir(parents=True)
        (matlab_root / "bin" / "matlab").write_text("#!/bin/sh\n")
        (matlab_root / "toolbox" / "simulink" / "simulink").mkdir(parents=True)

        monkeypatch.setattr(
            drv, "_INSTALL_FINDERS",
            [lambda: [(matlab_root / "bin" / "matlab", "test:synth")]],
        )

        installs = drv._scan_matlab_installs()
        assert len(installs) == 1
        assert installs[0].extra["simulink_installed"] is True

    def test_simulink_flag_false_when_toolbox_missing(self, tmp_path, monkeypatch):
        from sim_plugin_matlab import driver as drv

        matlab_root = tmp_path / "R2024a"
        (matlab_root / "bin").mkdir(parents=True)
        (matlab_root / "bin" / "matlab").write_text("#!/bin/sh\n")
        # No toolbox/simulink/

        monkeypatch.setattr(
            drv, "_INSTALL_FINDERS",
            [lambda: [(matlab_root / "bin" / "matlab", "test:synth")]],
        )

        installs = drv._scan_matlab_installs()
        assert len(installs) == 1
        assert installs[0].extra["simulink_installed"] is False


class TestMatlabLint:
    def test_lint_returns_install_error_when_matlab_missing(self, monkeypatch):
        monkeypatch.setattr("sim_plugin_matlab.driver.shutil.which", lambda _: None)
        driver = MatlabDriver()
        result = driver.lint(FIXTURES / "matlab_ok.m")
        assert result.ok is False
        assert "not available" in result.diagnostics[0].message.lower()


class TestReleaseEngineMap:
    """Every MATLAB release sim-cli claims to support must resolve to a
    concrete matlabengine pip version — otherwise detect_installed()
    reports engine_version='?', compat.yaml lookup silently fails, and
    `sim env install matlab` emits `pip install matlabengine==?`.
    """

    def test_known_releases_resolve(self):
        from sim_plugin_matlab.driver import _engine_version_for

        assert _engine_version_for("R2025b") == "25.2"
        assert _engine_version_for("R2025a") == "25.1"
        assert _engine_version_for("R2024b") == "24.2"
        assert _engine_version_for("R2024a") == "24.1"

    def test_unknown_release_returns_none(self):
        from sim_plugin_matlab.driver import _engine_version_for

        assert _engine_version_for("R2099z") is None


# A real Mathworks VersionInfo.xml from an R2024b install. Embedded
# verbatim — this is the contract format we depend on.
_VERSION_INFO_XML_R2024B = """<?xml version="1.0" encoding="UTF-8"?>
<!-- Version information for MathWorks R2024b Release -->
<MathWorks_version_info>
  <version>24.2.0.2712019</version>
  <release>R2024b</release>
  <description></description>
  <date>Aug 22 2024</date>
  <checksum>75238527</checksum>
</MathWorks_version_info>
"""


class TestVersionInfoXmlProbe:
    """`VersionInfo.xml` is the Mathworks-published contract for release
    identification; works regardless of install directory naming."""

    def test_reads_release_tag(self, tmp_path):
        from sim_plugin_matlab.driver import _version_from_versioninfo_xml

        (tmp_path / "VersionInfo.xml").write_text(_VERSION_INFO_XML_R2024B)
        assert _version_from_versioninfo_xml(tmp_path) == "R2024b"

    def test_missing_file_returns_none(self, tmp_path):
        from sim_plugin_matlab.driver import _version_from_versioninfo_xml

        assert _version_from_versioninfo_xml(tmp_path) is None

    def test_malformed_xml_returns_none(self, tmp_path):
        from sim_plugin_matlab.driver import _version_from_versioninfo_xml

        (tmp_path / "VersionInfo.xml").write_text("not xml at all")
        assert _version_from_versioninfo_xml(tmp_path) is None

    def test_lowercases_release_letter(self, tmp_path):
        from sim_plugin_matlab.driver import _version_from_versioninfo_xml

        (tmp_path / "VersionInfo.xml").write_text(
            "<release>R2023B</release>"
        )
        assert _version_from_versioninfo_xml(tmp_path) == "R2023b"


class TestMakeInstallNonCanonicalName:
    """Regression: Mathworks-China-style installs like
    ``E:\\Program Files (x86)\\Matlab_2024b\\`` have no ``R20XX`` in the
    path string. They must still be recognized via VersionInfo.xml."""

    def test_install_with_non_canonical_dir_name_is_recognized(self, tmp_path):
        from sim_plugin_matlab.driver import _make_install

        install_dir = tmp_path / "Matlab_2024b"  # NO "R" prefix
        (install_dir / "bin").mkdir(parents=True)
        matlab_bin = install_dir / "bin" / "matlab.exe"
        matlab_bin.write_text("")
        (install_dir / "VersionInfo.xml").write_text(_VERSION_INFO_XML_R2024B)

        inst = _make_install(matlab_bin, source="test:synth")
        assert inst is not None
        assert inst.version == "R2024b"
        assert inst.extra["engine_version"] == "24.2"
        assert inst.path == str(install_dir)

    def test_install_with_no_versioninfo_falls_back_to_path_regex(self, tmp_path):
        from sim_plugin_matlab.driver import _make_install

        install_dir = tmp_path / "R2024a"
        (install_dir / "bin").mkdir(parents=True)
        matlab_bin = install_dir / "bin" / "matlab.exe"
        matlab_bin.write_text("")

        inst = _make_install(matlab_bin, source="test:synth")
        assert inst is not None
        assert inst.version == "R2024a"

    def test_install_with_neither_signal_returns_none(self, tmp_path):
        from sim_plugin_matlab.driver import _make_install

        install_dir = tmp_path / "weirdname"  # no R20XX, no VersionInfo.xml
        (install_dir / "bin").mkdir(parents=True)
        matlab_bin = install_dir / "bin" / "matlab.exe"
        matlab_bin.write_text("")

        assert _make_install(matlab_bin, source="test:synth") is None


class TestBinarySniff:
    """Capability sniffing — does this dir have a runnable MATLAB binary?
    Used by the default-path finders to gate emission."""

    def test_windows_layout(self, tmp_path):
        from sim_plugin_matlab.driver import _has_matlab_binary

        (tmp_path / "bin").mkdir()
        (tmp_path / "bin" / "matlab.exe").write_text("")
        assert _has_matlab_binary(tmp_path) is True

    def test_linux_layout(self, tmp_path):
        from sim_plugin_matlab.driver import _has_matlab_binary

        (tmp_path / "bin" / "glnxa64").mkdir(parents=True)
        (tmp_path / "bin" / "glnxa64" / "matlab").write_text("")
        assert _has_matlab_binary(tmp_path) is True

    def test_macos_apple_silicon_layout(self, tmp_path):
        from sim_plugin_matlab.driver import _has_matlab_binary

        (tmp_path / "bin" / "maca64").mkdir(parents=True)
        (tmp_path / "bin" / "maca64" / "matlab").write_text("")
        assert _has_matlab_binary(tmp_path) is True

    def test_empty_dir_is_not_a_matlab_install(self, tmp_path):
        from sim_plugin_matlab.driver import _has_matlab_binary

        assert _has_matlab_binary(tmp_path) is False

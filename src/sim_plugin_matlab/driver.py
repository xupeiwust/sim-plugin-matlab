"""MATLAB driver for sim."""
from __future__ import annotations

import io
import json
import os
import re
import shutil
import time
import uuid
from pathlib import Path
from typing import Callable

from sim.driver import ConnectionInfo, Diagnostic, LintResult, SolverInstall
from sim.runner import run_subprocess


# ─── extension points ─────────────────────────────────────────────────────
#
# Detection follows the same strategy-chain pattern used by the COMSOL
# driver: a list of "where to look" finders + a list of "how to read the
# version out of an install dir" probes. To support a new MATLAB layout
# (e.g. macOS .app bundles, a custom enterprise install path) you append
# one function to the relevant list. Existing functions stay validated.

# Map MATLAB release labels (R2024a) to matlabengine pkg versions. This is
# the canonical MathWorks-published table; extend as new releases ship.
# Source: https://pypi.org/project/matlabengine/
_MATLAB_RELEASE_TO_ENGINE: dict[str, str] = {
    "R2025b": "25.2",
    "R2025a": "25.1",
    "R2024b": "24.2",
    "R2024a": "24.1",
    "R2023b": "23.2",
    "R2023a": "9.14",
    "R2022b": "9.13",
    "R2022a": "9.12",
}


def _release_from_path(path: Path) -> str | None:
    """Extract a MATLAB release label (e.g. 'R2024a') from a filesystem path.

    Examples:
        C:\\Program Files\\MATLAB\\R2024a\\bin\\matlab.exe → R2024a
        /usr/local/MATLAB/R2023b/bin/matlab               → R2023b
        /Applications/MATLAB_R2024a.app/bin/maci64/matlab → R2024a
    """
    for part in (str(path), str(path.parent), str(path.parent.parent)):
        m = re.search(r"R(\d{4})([ab])", part, re.IGNORECASE)
        if m:
            return f"R{m.group(1)}{m.group(2).lower()}"
    return None


def _engine_version_for(release: str) -> str | None:
    """Look up matlabengine pip version for a release label."""
    return _MATLAB_RELEASE_TO_ENGINE.get(release)


# ─── version probes ───────────────────────────────────────────────────────
#
# Same strategy-chain shape as the COMSOL driver: install-dir finders
# answer "where is MATLAB?", version probes answer "what release is the
# install at <dir>?". Decoupling these two questions is what lets us
# recognize installs whose directory name doesn't match the canonical
# `R20XXa` convention (e.g. Mathworks-China-style `Matlab_2024b/`).


def _version_from_versioninfo_xml(install_dir: Path) -> str | None:
    """MathWorks ships ``VersionInfo.xml`` at every install root since
    R2008b. It contains a ``<release>R20XXa</release>`` tag, which is the
    canonical, locale-invariant, dir-name-invariant source of truth.

    Example file content::

        <?xml version="1.0" encoding="UTF-8"?>
        <MathWorks_version_info>
          <version>24.2.0.2712019</version>
          <release>R2024b</release>
          ...
        </MathWorks_version_info>

    This is a Mathworks contract, not a heuristic — preferred over any
    path-string parsing.
    """
    xml = install_dir / "VersionInfo.xml"
    if not xml.is_file():
        return None
    try:
        text = xml.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    m = re.search(r"<release>\s*R(\d{4})([ab])\s*</release>", text, re.IGNORECASE)
    if m:
        return f"R{m.group(1)}{m.group(2).lower()}"
    return None


def _version_from_install_path(install_dir: Path) -> str | None:
    """Last-resort path-string probe. Kept for layouts without
    VersionInfo.xml (very old MATLAB releases, custom enterprise repacks)
    and as the macOS .app bundle fallback (``MATLAB_R2024a.app/``).
    """
    return _release_from_path(install_dir)


_VERSION_PROBES: list[Callable[[Path], str | None]] = [
    _version_from_versioninfo_xml,
    _version_from_install_path,
]
"""Strategy chain. APPEND new probes for new MATLAB layouts; do not edit."""


def _read_install_release(install_dir: Path) -> str | None:
    """Walk _VERSION_PROBES in order; first non-None result wins."""
    for probe in _VERSION_PROBES:
        try:
            v = probe(install_dir)
        except Exception:
            v = None
        if v:
            return v
    return None


def _make_install(matlab_bin: Path, source: str) -> SolverInstall | None:
    if not matlab_bin.is_file():
        return None
    # Resolve install root from the binary path. Most layouts place the
    # binary at <root>/bin/<arch>/matlab (Linux/macOS) or <root>/bin/matlab.exe
    # (Windows); walk up until we find VersionInfo.xml or run out of parents.
    install_dir = matlab_bin.parent.parent
    if not (install_dir / "VersionInfo.xml").is_file() and matlab_bin.parent.parent.parent != matlab_bin.parent.parent:
        # Linux/macOS arch-suffixed layout: bin/glnxa64/matlab → root is one more up
        alt = matlab_bin.parent.parent.parent
        if (alt / "VersionInfo.xml").is_file():
            install_dir = alt
    release = _read_install_release(install_dir)
    if release is None:
        return None
    engine = _engine_version_for(release) or "?"
    return SolverInstall(
        name="matlab",
        version=release,
        path=str(install_dir),
        source=source,
        extra={
            "release_label": release,
            "matlab_bin": str(matlab_bin),
            "engine_version": engine,
        },
    )


def _candidates_from_env() -> list[tuple[Path, str]]:
    out: list[tuple[Path, str]] = []
    for var in ("MATLAB_ROOT", "MATLABROOT"):
        v = os.environ.get(var)
        if not v:
            continue
        for sub in ("bin/matlab.exe", "bin/matlab"):
            p = Path(v) / sub
            if p.is_file():
                out.append((p, f"env:{var}"))
                break
    return out


def _candidates_from_path() -> list[tuple[Path, str]]:
    out: list[tuple[Path, str]] = []
    p = shutil.which("matlab")
    if p:
        # `matlab` on PATH is often a launcher script; resolve to the real binary
        out.append((Path(p).resolve(), "which:matlab"))
    return out


# ─── install-dir probing helpers ──────────────────────────────────────────


def _matlab_binary_paths(install_dir: Path) -> list[Path]:
    """All known platform-specific MATLAB launcher binary locations under
    an install root. Capability sniffing uses this; it's also the source
    of truth for which file path to record in the SolverInstall.
    """
    return [
        install_dir / "bin" / "matlab.exe",
        install_dir / "bin" / "matlab",
        install_dir / "bin" / "glnxa64" / "matlab",
        install_dir / "bin" / "maci64" / "matlab",
        install_dir / "bin" / "maca64" / "matlab",
    ]


def _has_matlab_binary(install_dir: Path) -> bool:
    return any(p.is_file() for p in _matlab_binary_paths(install_dir))


def _first_matlab_binary(install_dir: Path) -> Path | None:
    for p in _matlab_binary_paths(install_dir):
        if p.is_file():
            return p
    return None


def _candidates_from_windows_defaults() -> list[tuple[Path, str]]:
    """Probe common Windows install layouts.

    Capability-sniffs ``bin/matlab.exe`` instead of regex-matching the
    directory name — this catches Mathworks-China-style installs like
    ``E:\\Program Files (x86)\\Matlab_2024b\\`` and any other layout
    that doesn't follow the canonical ``R20XXa`` naming convention.
    """
    bases: list[Path] = []
    for drive in ("C:", "D:", "E:", "F:"):
        bases.extend([
            Path(rf"{drive}\Program Files\MATLAB"),
            Path(rf"{drive}\Program Files (x86)\MATLAB"),
            # Flat layouts: localized installers sometimes drop the install
            # directly under Program Files\<MatlabXXXX>\, no MATLAB\ parent.
            Path(rf"{drive}\Program Files"),
            Path(rf"{drive}\Program Files (x86)"),
        ])
    out: list[tuple[Path, str]] = []
    seen: set[Path] = set()
    for base in bases:
        if not base.is_dir():
            continue
        # Direct hit: base IS already the install root.
        if _has_matlab_binary(base):
            mexe = _first_matlab_binary(base)
            assert mexe is not None
            if mexe not in seen:
                seen.add(mexe)
                out.append((mexe, f"default-path:{base}"))
            continue
        # Otherwise scan one level for any child that looks like a MATLAB
        # install. Soft name filter ("matlab" substring) avoids walking
        # every app under Program Files; binary sniff still gates emission.
        try:
            children = sorted(base.iterdir(), reverse=True)
        except OSError:
            continue
        for child in children:
            if "matlab" not in child.name.lower():
                continue
            if not _has_matlab_binary(child):
                continue
            mexe = _first_matlab_binary(child)
            assert mexe is not None
            if mexe in seen:
                continue
            seen.add(mexe)
            out.append((mexe, f"default-path:{base}"))
    return out


def _candidates_from_linux_defaults() -> list[tuple[Path, str]]:
    """Probe common Linux install layouts via binary sniff.

    Soft name filter accepts either ``R20XXa``-style names (canonical
    Mathworks install) or anything containing ``matlab`` (non-standard
    layouts, custom repacks).
    """
    bases = [
        Path("/usr/local/MATLAB"),
        Path("/opt/MATLAB"),
        Path("/usr/local"),
        Path("/opt"),
    ]
    out: list[tuple[Path, str]] = []
    seen: set[Path] = set()
    for base in bases:
        if not base.is_dir():
            continue
        try:
            children = sorted(base.iterdir(), reverse=True)
        except OSError:
            continue
        for child in children:
            name_lc = child.name.lower()
            if "matlab" not in name_lc and not re.match(
                r"R\d{4}[ab]$", child.name, re.IGNORECASE
            ):
                continue
            if not _has_matlab_binary(child):
                continue
            mexe = _first_matlab_binary(child)
            assert mexe is not None
            if mexe in seen:
                continue
            seen.add(mexe)
            out.append((mexe, f"default-path:{base}"))
    return out


def _candidates_from_macos_defaults() -> list[tuple[Path, str]]:
    """macOS: ``/Applications/MATLAB_R20XXa.app/`` and friends.

    The ``.app`` bundle root contains ``bin/maci64/matlab`` (Intel) or
    ``bin/maca64/matlab`` (Apple Silicon) plus ``VersionInfo.xml`` at the
    same level as the canonical Linux/Windows layout.
    """
    base = Path("/Applications")
    if not base.is_dir():
        return []
    out: list[tuple[Path, str]] = []
    seen: set[Path] = set()
    try:
        children = sorted(base.iterdir(), reverse=True)
    except OSError:
        return []
    for child in children:
        if "matlab" not in child.name.lower():
            continue
        if not _has_matlab_binary(child):
            continue
        mexe = _first_matlab_binary(child)
        assert mexe is not None
        if mexe in seen:
            continue
        seen.add(mexe)
        out.append((mexe, f"default-path:{base}"))
    return out


_INSTALL_FINDERS: list[Callable[[], list[tuple[Path, str]]]] = [
    _candidates_from_env,
    _candidates_from_path,
    _candidates_from_windows_defaults,
    _candidates_from_linux_defaults,
    _candidates_from_macos_defaults,
]
"""Strategy chain. APPEND new finders for new MATLAB layouts; do not edit."""


def _probe_simulink_installed(matlab_root: Path) -> bool:
    """Filesystem-level check for a Simulink toolbox install under a MATLAB root.

    Does NOT launch MATLAB and does NOT check the license. This is the
    "installed on disk" signal — a looser gate than `license('test','Simulink')`
    (which itself is looser than `license('checkout','Simulink')`). See
    `matlab_driver.md` for the rationale behind preferring installed-on-disk
    over a license checkout (which would hold a seat for the process lifetime
    and is hostile to shared MATLAB installs).
    """
    try:
        return (matlab_root / "toolbox" / "simulink" / "simulink").is_dir()
    except Exception:
        return False


def _scan_matlab_installs() -> list[SolverInstall]:
    found: dict[str, SolverInstall] = {}
    for finder in _INSTALL_FINDERS:
        try:
            cands = finder()
        except Exception:
            continue
        for path, source in cands:
            inst = _make_install(path, source=source)
            if inst is None:
                continue
            key = str(Path(inst.path).resolve())
            if key in found:
                continue
            if _probe_simulink_installed(Path(inst.path)):
                inst.extra["simulink_installed"] = True
            else:
                inst.extra["simulink_installed"] = False
            found[key] = inst
    return sorted(found.values(), key=lambda i: i.version, reverse=True)


def _default_matlab_probes(enable_gui: bool = False) -> list:
    """MATLAB probe list — generic_probes() + optional GUI observation.

    No driver-layer semantic assertions: "what counts as an error" is the
    agent's job, not the driver's. Probes here only extract facts.
    """
    from sim.inspect import (                                            # noqa: PLC0415
        GuiDialogProbe, ScreenshotProbe, generic_probes,
    )
    probes: list = list(generic_probes())
    if enable_gui:
        probes.append(GuiDialogProbe(
            process_name_substrings=("matlab", "MATLAB"),
            code_prefix="matlab.gui"))
        probes.append(ScreenshotProbe(
            filename_prefix="matlab_shot",
            process_name_substrings=("matlab", "MATLAB")))
    return probes


class MatlabDriver:
    """MATLAB driver — one-shot and persistent session execution."""

    def __init__(self):
        self._engine = None
        self._session_id: str | None = None
        self._desktop: bool = False
        self.probes: list = _default_matlab_probes(enable_gui=False)
        self._sim_dir = Path.cwd() / ".sim"

    @property
    def name(self) -> str:
        return "matlab"

    @property
    def supports_session(self) -> bool:
        return True

    def detect(self, script: Path) -> bool:
        """Treat `.m` scripts and `.slx`/`.mdl` Simulink models as MATLAB inputs.

        Simulink models dispatch through a separate `run_file` branch that
        wraps `load_system → sim_shim.run → close_system` (see Issue #27 Phase A).
        """
        return script.suffix.lower() in (".m", ".slx", ".mdl")

    def lint(self, script: Path) -> LintResult:
        """Run MATLAB-native linting when MATLAB is available.

        `.m` files go through `checkcode`. `.slx`/`.mdl` models have no
        equivalent static lint in the driver surface today; we report
        an info-level diagnostic rather than an error so `sim lint
        model.slx` exits cleanly.
        """
        suffix = script.suffix.lower()
        if suffix in (".slx", ".mdl"):
            return LintResult(
                ok=True,
                diagnostics=[Diagnostic(
                    level="info",
                    message="Simulink model lint is not implemented; "
                            "skipping static checks",
                )],
            )
        if not self.detect(script):
            return LintResult(
                ok=False,
                diagnostics=[Diagnostic(level="error", message="Not a MATLAB `.m` script")],
            )

        matlab = shutil.which("matlab")
        if matlab is None:
            return LintResult(
                ok=False,
                diagnostics=[
                    Diagnostic(
                        level="error",
                        message="MATLAB is not available on PATH; cannot lint `.m` files",
                    )
                ],
            )

        expr = (
            "issues = checkcode('{path}', '-id'); "
            "if isempty(issues), disp(jsonencode(struct('ok', true, 'diagnostics', {{}}))); "
            "else, msgs = strings(numel(issues), 1); "
            "for i = 1:numel(issues), msgs(i) = string(issues(i).message); end; "
            "payload = struct('ok', false, 'diagnostics', cellstr(msgs)); "
            "disp(jsonencode(payload)); end"
        ).format(path=_matlab_string(script.resolve()))

        result = run_subprocess(
            [matlab, "-batch", expr],
            script=script,
            solver=self.name,
        )
        if result.exit_code != 0:
            return LintResult(
                ok=False,
                diagnostics=[
                    Diagnostic(
                        level="error",
                        message=result.stderr or "MATLAB lint command failed",
                    )
                ],
            )

        payload = self.parse_output(result.stdout)
        diagnostics = [
            Diagnostic(level="warning", message=message)
            for message in payload.get("diagnostics", [])
        ]
        return LintResult(ok=payload.get("ok", not diagnostics), diagnostics=diagnostics)

    def connect(self) -> ConnectionInfo:
        """Report MATLAB availability via detect_installed."""
        installs = self.detect_installed()
        if not installs:
            return ConnectionInfo(
                solver="matlab",
                version=None,
                status="not_installed",
                message="No MATLAB installation detected on this host",
            )
        top = installs[0]
        simulink = top.extra.get("simulink_installed")
        simulink_note = ""
        if simulink is True:
            simulink_note = " (Simulink toolbox installed)"
        elif simulink is False:
            simulink_note = " (Simulink toolbox not found on disk)"
        return ConnectionInfo(
            solver="matlab",
            version=top.version,
            status="ok",
            message=f"MATLAB {top.version} at {top.path}{simulink_note}",
            solver_version=top.version,
        )

    def detect_installed(self) -> list[SolverInstall]:
        """Enumerate MATLAB installations visible on this host.

        Strategy chain (deduped by resolved install root):
          1. MATLAB_ROOT / MATLABROOT env vars
          2. PATH probe via `which matlab`
          3. C:\\Program Files\\MATLAB\\R20XXa\\bin\\matlab.exe (Windows)
          4. /usr/local/MATLAB/R20XXa/bin/matlab (Linux/macOS)

        Pure stdlib. Does NOT import matlabengine. Returns highest
        release first. Each install reports the matched matlabengine
        pkg version in extra.engine_version so the resolver can map
        binary release → SDK pin.
        """
        return _scan_matlab_installs()

    def parse_output(self, stdout: str) -> dict:
        """Parse the last JSON object printed by a MATLAB script."""
        for line in reversed(stdout.strip().splitlines()):
            line = line.strip()
            if line.startswith("{"):
                try:
                    return json.loads(line)
                except json.JSONDecodeError:
                    continue
        return {}

    def run_file(self, script: Path):
        """Execute a MATLAB `.m` script or a Simulink `.slx`/`.mdl` model.

        `.m` → `matlab -batch "run('<path>')"`.
        `.slx` / `.mdl` → `addpath(<matlab_pkg>); load_system('<path>');
        sim_shim.run('<model>', '{}', '<out_dir>'); close_system('<model>', 0)`.
        The `+sim_shim/run.m` helper (see Issue #27 Phase B) flattens the
        resulting `Simulink.SimulationOutput` to Parquet (preferred) or MAT
        and prints a JSON pointer as the final stdout line, consumed by
        `parse_output`.
        """
        matlab = shutil.which("matlab")
        if matlab is None:
            raise RuntimeError("matlab is not available on PATH")

        suffix = script.suffix.lower()
        if suffix in (".slx", ".mdl"):
            expr = self._simulink_batch_expr(script)
        else:
            expr = f"run('{_matlab_string(script.resolve())}')"

        return run_subprocess(
            [matlab, "-batch", expr],
            script=script,
            solver=self.name,
        )

    def _simulink_batch_expr(self, script: Path) -> str:
        """Build the MATLAB `-batch` expression for a Simulink model file.

        The expression:
          1. Adds `matlab_pkg/` to path so the `+sim_shim/` package resolves
             (we deliberately do NOT name this folder `resources/` —
             MATLAB reserves that name and silently refuses to put it
             on the path, which makes `+sim_shim` invisible)
          2. Loads the model from its absolute path
          3. Invokes `sim_shim.run(<model>, '{}', <out_dir>)`
          4. Always closes the model (via onCleanup) — even if sim() throws

        The output directory is `<script parent>/.sim/<model>/` so artifacts
        land beside the source model and out of the way of other runs.
        """
        abs_path = script.resolve()
        model_name = abs_path.stem
        out_dir = abs_path.parent / ".sim" / model_name
        out_dir.mkdir(parents=True, exist_ok=True)

        # NOTE: name is `matlab_pkg`, not `resources`. MATLAB reserves
        # the name `resources` (alongside `private` and `@<class>`) and
        # silently refuses to put folders with those names on the path —
        # `addpath` only emits a warning, then `which('sim_shim.run')`
        # comes up empty. See MATLAB R2024+ path() doc.
        matlab_pkg = Path(__file__).parent / "matlab_pkg"
        parts = [
            f"addpath('{_matlab_string(matlab_pkg)}')",
            f"load_system('{_matlab_string(abs_path)}')",
            f"cleanup__ = onCleanup(@() close_system('{model_name}', 0))",
            f"sim_shim.run('{model_name}', '{{}}', '{_matlab_string(out_dir)}')",
        ]
        return "; ".join(parts)

    # ── Persistent session API ───────────────────────────────────────────────

    def launch(self, ui_mode: str = "desktop", **kwargs) -> dict:
        """Start a persistent MATLAB session via matlab.engine."""
        try:
            import matlab.engine  # noqa: PLC0415
        except ImportError as exc:
            raise RuntimeError(
                "matlabengine is not installed. "
                "Run: pip install matlabengine"
            ) from exc

        self._desktop = ui_mode in ("desktop", "gui")
        if self._desktop:
            self._engine = matlab.engine.start_matlab("-desktop")
        else:
            self._engine = matlab.engine.start_matlab()

        self._session_id = str(uuid.uuid4())
        self.probes = _default_matlab_probes(enable_gui=self._desktop)
        return {
            "ok": True,
            "session_id": self._session_id,
            "ui_mode": ui_mode,
        }

    def _dispatch(self, code: str, label: str = "snippet") -> dict:
        """Execute MATLAB code in the persistent session (no probes)."""
        if self._engine is None:
            raise RuntimeError("No active MATLAB session.")

        stdout_buf = io.StringIO()
        stderr_buf = io.StringIO()
        ok = True
        error = None

        try:
            self._engine.eval(code, nargout=0, stdout=stdout_buf, stderr=stderr_buf)
        except Exception as e:
            ok = False
            error = str(e)

        stdout = stdout_buf.getvalue()
        parsed = self.parse_output(stdout) if ok else None

        return {
            "ok": ok,
            "label": label,
            "stdout": stdout,
            "stderr": stderr_buf.getvalue(),
            "error": error,
            "result": parsed,
        }

    def run(self, code: str, label: str = "snippet") -> dict:
        """Execute MATLAB code and attach inspect diagnostics."""
        from sim.inspect import InspectCtx, collect_diagnostics         # noqa: PLC0415

        wd = self._sim_dir
        try:
            wd.mkdir(parents=True, exist_ok=True)
            before = sorted(
                str(p.relative_to(wd)).replace("\\", "/")
                for p in wd.rglob("*") if p.is_file()
            )
        except Exception:
            before = []

        t0 = time.monotonic()
        result = self._dispatch(code, label)
        wall = time.monotonic() - t0

        ctx = InspectCtx(
            stdout=result.get("stdout", "") or "",
            stderr=result.get("stderr", "") or result.get("error", "") or "",
            workdir=str(wd),
            wall_time_s=wall,
            exit_code=0 if result.get("ok") else 1,
            driver_name=self.name,
            session_ns={"_result": result.get("result")},
            workdir_before=before,
        )
        diags, arts = collect_diagnostics(self.probes, ctx)
        result["diagnostics"] = [d.to_dict() for d in diags]
        result["artifacts"] = [a.to_dict() for a in arts]
        return result

    def query(self, name: str) -> dict:
        """Named query against the MATLAB session."""
        if name == "workspace.summary":
            if self._engine is None:
                return {"connected": False}
            variables = self._engine.eval("who", nargout=1)
            return {"connected": True, "variables": list(variables) if variables else []}

        if name == "session.summary":
            return {
                "connected": self._engine is not None,
                "session_id": self._session_id,
                "ui_mode": "desktop" if self._desktop else "headless",
            }

        return {"error": f"unknown query: {name}"}

    def disconnect(self) -> dict:
        """Shut down the MATLAB session."""
        if self._engine is None:
            return {"ok": False, "reason": "no active session"}
        sid = self._session_id
        try:
            self._engine.quit()
        except Exception:
            pass
        self._engine = None
        self._session_id = None
        return {"ok": True, "session_id": sid, "disconnected": True}


def _matlab_string(path: Path) -> str:
    """Convert a filesystem path to a MATLAB-quoted string literal."""
    text = path.as_posix()
    return re.sub(r"'", "''", text)

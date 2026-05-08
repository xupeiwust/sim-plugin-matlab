---
name: matlab-sim
description: Use when running MATLAB `.m` scripts or Simulink `.slx` / `.mdl` models through sim-cli's MATLAB plugin — one-shot via `sim run --solver matlab`, local persistent sessions via `sim connect --solver matlab`, explicit JSON result extraction, and conservative handling of MATLAB desktop and Simulink model state. Shared / remote Simulink sessions are a non-goal.
---

# matlab-sim

You are driving **MATLAB** via the sim MATLAB plugin. This skill is
self-contained for MATLAB-specific work: it covers one-shot batch runs,
local persistent sessions, Simulink dispatch, version probing, acceptance, and
escalation points for this plugin.

Start every real task with:

```bash
sim check matlab
```

For one-shot execution, use `sim run --solver matlab <script-or-model>`. For a
local persistent MATLAB engine session, use `sim connect --solver matlab`, then
bounded `sim exec` snippets, then `sim disconnect`. Persistent sessions require
the optional `matlabengine` package that matches the installed MATLAB release;
use `sim env install matlab` or install the matching pin from
`compatibility.yaml`.

---

## MATLAB-specific layered content

`sim inspect session.versions` (run against a short-lived session
before your real `sim run`) returns:

```json
"session.versions": {
  "profile":             "matlabengine_24_1",  // or 24.2 / 23.2
  "active_sdk_layer":    "24.1",                // matlabengine package version
  "active_solver_layer": null                   // engine version IS the release pin
}
```

`active_sdk_layer` is the matlabengine package version. There is no
separate `solver/` overlay because each matlabengine X.Y is rigidly
coupled to one MATLAB release (24.1 ↔ R2024a, 24.2 ↔ R2024b, …).

Always read `base/`, then your active `sdk/<slug>/`.

### `base/` — always relevant

| Path | What's there |
|---|---|
| `base/reference/` | MATLAB-specific control patterns: how to pass numpy arrays to engine, how to read engine.workspace, how to surface MATLAB errors as Python exceptions. |
| `base/snippets/` | Ready-made `sim run` payloads for common analyses. |
| `base/workflows/` | End-to-end multi-script examples. |
| `base/driver_upgrade.md` | Process notes for bumping the matlabengine SDK pin. |

### `sdk/<active_sdk_layer>/` — engine-version specifics

Empty stubs by default; per-engine deltas land here as discovered.

- `sdk/24.2/notes.md` — matlabengine 24.2 / R2024b
- `sdk/24.1/notes.md` — matlabengine 24.1 / R2024a
- `sdk/23.2/notes.md` — matlabengine 23.2 / R2023b

### Documentation lookup

Primary route for every MATLAB doc question is **MATLAB's own `help()`
/ `doc` via the engine**. This plugin does not bundle a documentation scanner;
on R2024+ MathWorks ships most reference docs as a Lucene binary index, not
static HTML.

#### Primary: `help()` / `doc` via the engine

From a live sim session:

```bash
sim exec "disp(help('fft'))"
sim exec "disp(help('ode45'))"
sim exec "disp(help('fmincon'))"        # Optimization Toolbox
sim exec "disp(help('solve'))"          # Symbolic Math Toolbox
```

Without a session (and without paying matlabengine startup cost), use
the MATLAB launcher directly:

```bash
matlab -batch "disp(help('fft'))"
```

This is authoritative — it reflects the toolboxes actually loaded,
respects shadowing, and handles overloaded methods correctly. Works
identically across all MATLAB releases. Verified end-to-end against
R2025b: returns structured syntax + arguments + examples + see-also.

For a longer write-up (the `doc` command's content), use
`sim exec "open(which('fft'));"` only when a desktop is available;
otherwise query the online docs at `https://www.mathworks.com/help/`.

#### Fallback: local docs and online docs

**Known limitation:** on MATLAB R2024a and later, the per-toolbox
folders under `<matlabroot>/help/` (`optim/`, `simulink/`, `stats/`,
`signal/`, `control/`, `symbolic/`, …) contain **no HTML reference
pages** — only Lucene binary indexes (`.cfs`/`.cfe`/`.si`) that the
regex scanner can't read. The `matlab/` folder does have ~500 HTML
files, but they're Code Analyzer diagnostics, not function refs.

What the scanner still catches on modern installs:
- `derived/toolbox/learning/…` — Simulink tutorial / learning content.
- Pockets of HTML under `customdoc/`, `coder/`, and a few other dirs.
- The core MATLAB help on **R2023b and earlier** (full static HTML).

If you need longer prose than `help()` gives, use MATLAB's `doc` command when a
desktop is available, or query `https://www.mathworks.com/help/`. For function
and API questions on R2024+, go straight to `help()`.

### `tests/` (top-level, QA-only)

Not loaded during a normal session.

---

## Simulink

The MATLAB driver dispatches on input suffix. `.slx` and `.mdl` models
route through a package helper shipped with this plugin at
`src/sim_plugin_matlab/matlab_pkg/+sim_shim/run.m`, not through the
generic `matlab -batch run('<script>')` wrapper used for `.m` files.
The driver adds the `matlab_pkg/` parent to the MATLAB path, opens the
model with `load_system`, registers an `onCleanup` that calls
`close_system(<name>, 0)`, calls `sim_shim.run(<name>, '{}', <out_dir>)`,
and parses the final JSON line from stdout. `sim_shim.run` runs `sim()`,
tries to flatten the `Simulink.SimulationOutput` to a `timetable`, and
writes either `<out_dir>/<model>_out.parquet` (preferred) or
`<out_dir>/<model>_out.mat` (fallback), then emits a single line of the
form `{"ok":true,"result_file":"<path>","format":"parquet|mat","signals":[...]}`.
`out_dir` defaults to `<script_parent>/.sim/<model_name>/`. The
`sim check matlab` probe additionally surfaces `simulink: installed |
not found on disk` per install, driven by a filesystem check for
`<matlabroot>/toolbox/simulink/simulink/`. Full contract in
[`base/reference/simulink.md`](base/reference/simulink.md).

What is **not** wired yet (deferred per [sim-cli issue
#27](https://github.com/svd-ai-lab/sim-cli/issues/27)): the rest of the
`+sim_shim/` package helpers beyond `run` (Phase B — `models`,
`blocks`, `signals`, `set`, and `sweep` / `parsim` parameter sweeps);
`models.summary` / `blocks.summary` / `signals.summary` /
`figures.summary` inspect verbs (Phase C); a typed `SimulationResult`
/ `SweepResult` dataclass wrapping the pointer JSON (Phase D); sample
`.slx` regression fixtures in sim-datasets (Phase F); and shared /
persistent Simulink sessions (listed under Non-goals in issue #27).
Today you get one `sim run <model.slx>` per simulation and read the
result file yourself; do not assume any of the deferred surface exists.

---

## MATLAB-specific hard constraints

These add to — do not replace — the shared skill's hard constraints.

1. **MATLAB output is not structured by default.** Always wrap the
   final result in an explicit JSON line on stdout that the driver's
   `parse_output()` can pick up. Free-form `disp()` output gets lost —
   the parser only picks up the **last** JSON object in stdout.
2. **Don't depend on workspace survival across calls.** v0 is
   one-shot per script; the driver tears the engine down between
   `sim run` invocations. Do not write snippets whose correctness
   depends on workspace state set by an earlier `sim run`.
3. **No MATLAB desktop.** Driver launches headless. Do not add
   `desktop` / `-desktop` flags — there is no display.

---

## Required protocol (one paragraph)

Follow the shared skill's required protocol for the **one-shot batch**
model. MATLAB-specific steps: validate the `.m` script exists and its
dependencies (data files, toolboxes) are on the MATLAB path; confirm
the final script line emits a structured JSON object on stdout; run
`sim run <script.m> --solver matlab`; parse the JSON line from stdout
(the driver does this via `parse_output()`) and evaluate against the
user's acceptance criterion per the shared skill's `acceptance.md`.
For multi-step pipelines, chain `sim run` calls — each is its own
engine lifecycle with no shared state.

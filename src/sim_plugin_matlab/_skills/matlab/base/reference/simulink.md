# Simulink via the MATLAB driver

Status: **Phase A + minimum-viable Phase B** from
[sim-cli issue #27](https://github.com/svd-ai-lab/sim-cli/issues/27).
Everything else on that roadmap (rest-of-Phase B shim helpers,
`models.summary` / `blocks.summary` / `signals.summary` inspect verbs
in Phase C, `SimulationResult` dataclass in Phase D, sample `.slx`
assets in Phase F, and shared / persistent Simulink sessions — a
[non-goal](https://github.com/svd-ai-lab/sim-cli/issues/27) for now) is
**deferred** and not available at the `sim` CLI today. This skill doc
is the sim-skills side of Phase E.

## Input dispatch

The MATLAB driver's `run_file()` inspects the input suffix:

| Suffix    | Path                                                      |
|-----------|-----------------------------------------------------------|
| `.m`      | `matlab -batch "run('<abs_path>')"`                       |
| `.slx`    | `matlab -batch "addpath(...); load_system(...); sim_shim.run(...); close_system(...)"` |
| `.mdl`    | same as `.slx`                                            |

So `sim run my_model.slx --solver matlab` does **not** invoke
`matlab -batch run('my_model.slx')`. It goes through the package
helper `sim_shim.run` shipped alongside the driver.

## Package helper: `sim_shim.run`

Shipped as a MATLAB package at
`src/sim/drivers/matlab/resources/+sim_shim/run.m` (in the sim-cli
repo). The driver adds `resources/` to the MATLAB path so the
package is resolvable as `sim_shim.run`.

### Signature

```matlab
sim_shim.run(model)
sim_shim.run(model, params_json)
sim_shim.run(model, params_json, out_dir)
```

- **`model`** — model name (already `load_system`'d). The driver
  passes the stem of the input file (e.g. `rc_circuit` for
  `rc_circuit.slx`).
- **`params_json`** — JSON-encoded struct of top-level model
  parameters. Each field becomes a `set_param(modelName, field,
  value)` call **before** `sim()` is invoked. Example:
  `'{"StopTime":"10"}'`. Defaults to `'{}'`. *Phase A always passes
  `'{}'` — the loop runs but sets nothing.*
- **`out_dir`** — directory to write artifacts into. Created if
  missing. Defaults to a fresh `tempname` folder. The driver passes
  `<script_parent>/.sim/<model_name>/` so artifacts live next to the
  input.

### What it does

1. Decodes `params_json` and `set_param`'s each top-level field (no
   coercion — numeric JSON values currently decode to double and would
   need `num2str` wrapping to satisfy `set_param`; Phase A does not
   exercise this path).
2. Runs `simOut = sim(modelName)` with the currently active
   configuration.
3. Tries to flatten `simOut` (a `Simulink.SimulationOutput`) to a
   MATLAB `timetable` by walking `simOut.who`:
   - `timeseries` elements are merged via `timetable + synchronize`.
   - `Simulink.SimulationData.Dataset` is expanded: each
     `Element.Values` is merged the same way.
   - Conversion failures are swallowed; the result is an empty
     timetable which routes to the MAT fallback.
4. If the timetable is non-empty **and** `parquetwrite` exists,
   writes `<out_dir>/<model>_out.parquet` via
   `parquetwrite(parquetPath, timetable2table(tt))`.
5. Otherwise writes `<out_dir>/<model>_out.mat` with the raw
   `simOut` via `save(matPath, 'simOut')`.
6. Emits a **single JSON line on stdout** (last line — the MATLAB
   driver's `parse_output()` picks up the last JSON object in
   stdout):

```json
{
  "ok": true,
  "result_file": "/abs/path/to/<model>_out.parquet",
  "format": "parquet",   // or "mat"
  "signals": ["V_out", "I_R1"]
}
```

`signals` is the list of `VariableNames` from the flattened
timetable. For the MAT fallback it's the same list if flattening
succeeded, otherwise `[]`.

## Lifecycle wrapper (what the driver actually runs)

```matlab
addpath('<sim-cli>/src/sim/drivers/matlab/resources');
load_system('/abs/path/to/<model>.<ext>');
cleanup__ = onCleanup(@() close_system('<model>', 0));
sim_shim.run('<model>', '{}', '<script_parent>/.sim/<model>/');
```

The `onCleanup` guarantees `close_system(<name>, 0)` runs even if
`sim()` errors, so the model is not left open in the MATLAB base
workspace between invocations. The `0` argument means "do not save"
— a safety default; if you ever need to persist model edits, do it
explicitly via `save_system` *inside* the model, not here.

## Reading the result in Python

The driver only forwards the JSON line; you open the artifact yourself.
Parquet is preferred because it round-trips cleanly to pandas /
PyArrow without a MATLAB runtime on the reader side:

```python
import json
import pandas as pd

result = json.loads(stdout.splitlines()[-1])
assert result["ok"] is True
if result["format"] == "parquet":
    df = pd.read_parquet(result["result_file"])
else:
    # MAT fallback — requires scipy or h5py depending on MAT version
    from scipy.io import loadmat
    mat = loadmat(result["result_file"])
    # raw Simulink.SimulationOutput — inspect mat["simOut"]
```

The Parquet schema is a flat table with one `Time` column (seconds)
plus one column per timetable variable. Multi-dimensional signals
are squeezed via `squeeze(value.Data)` then transposed if needed so
the time axis ends up on the rows — check `signals` against the
actual columns if you're building a generic reader.

## Simulink probe in `sim check matlab`

`detect_installed()` sets `extra.simulink_installed` per discovered
MATLAB install by testing for the existence of
`<matlabroot>/toolbox/simulink/simulink/`. `sim check matlab`
renders this as:

```
      simulink: installed
```

or

```
      simulink: not found on disk
```

The probe is filesystem-only — it does **not** call
`license('test','Simulink')` or `license('checkout','Simulink')` and
so does not consume a floating license or start the MATLAB engine.
A missing flag means Simulink is not installed for that specific
MATLAB root; if the flag is `installed` but `sim run <model>.slx`
still fails with a license error, that's a floating-license issue,
not a skill-layer bug.

## What is not wired (do not assume)

From issue #27's phased plan — everything below is **future work**:

- **Phase B extras.** Only `sim_shim.run` is shipped today. The rest
  of the `+sim_shim/` package (`models()`, `blocks(model)`,
  `signals(model)`, `set(model, struct_json)`, and `sweep(model,
  sim_input_array_json)` for `parsim` / `Simulink.SimulationInput`
  parameter sweeps) is not present. One `sim run` is exactly one
  `sim()` call — no batch sweeps, no batched `set_param` from JSON.
- **Phase C — driver query surface.**
  `sim inspect session.models.summary` / `blocks.summary` /
  `signals.summary` / `figures.summary` do not exist. You cannot
  interrogate a model's block list through the CLI; open it in
  MATLAB if you need that.
- **Phase D — structured result handling.** No `SimulationResult`
  dataclass, no `SweepResult`, no `parse_output` branch that
  resolves the artifact pointer. You read the `result_file` path
  yourself (see the Python recipe above).
- **Phase F — test assets.** No `.slx` samples land in sim-datasets
  yet; there is no per-release regression fixture. If you want a
  smoke-test model, supply your own.
- **Shared / persistent Simulink session.** Listed under issue #27's
  Non-goals — same deferral as the rest of the MATLAB driver's
  remote-session story. Every `sim run` is a cold MATLAB batch;
  workspace / loaded-systems state does not survive between
  invocations. `sim connect --solver matlab` works for pure `.m`
  scripting but is not a documented path for driving `.slx` models.

## Common pitfalls

1. **Empty timetable → MAT fallback.** If `simOut.who` returns
   nothing (e.g. the model has no logged outputs, no Outports with
   logging enabled, and no `ToWorkspace` blocks), the flattener
   gives up silently and you get a MAT file with the raw
   `Simulink.SimulationOutput`. Enable signal logging on at least
   one signal if you want Parquet.
2. **`parquetwrite` absent on older MATLAB.** Present in R2019a+;
   if you're on anything older the driver always writes MAT. Check
   the `format` field, don't hard-code Parquet.
3. **Model name vs. file name.** `load_system` and `sim()` take the
   model name (no extension). The driver derives this from the
   input path stem — don't pass a full path to `sim_shim.run`.
4. **`params_json` numeric coercion.** If you pass
   `'{"StopTime":10}'` (numeric JSON), `set_param` will fail
   because it wants a string. Use `'{"StopTime":"10"}'`. The
   `sim_shim.run` helper has a TODO to wrap with `num2str`, but
   today the Phase A call site only passes `'{}'` so this is not
   exercised.
5. **`onCleanup` vs. `catch`.** The driver uses `onCleanup` to
   `close_system(..., 0)`. If your own `.m` wrapper calls
   `sim_shim.run` inside a `try/catch` that rethrows, make sure the
   model is still closed — `onCleanup` only fires when its anchor
   variable goes out of scope.

# License Notice

`sim-plugin-matlab` is released under Apache-2.0 (see [LICENSE](LICENSE)).

## Vendor SDK / binary disclaimer

This plugin is a thin adapter that delegates to:

- **MATLAB** (the `matlab`/`matlab.exe` binary), a commercial product of
  The MathWorks, Inc.
- **`matlabengine`**, the MathWorks-published Python binding to MATLAB
  (distributed on PyPI by The MathWorks, Inc., not by this project).

This repository **does not bundle, redistribute, or otherwise embed**
any MathWorks binary, source, mechanism file, or SDK. Users are
responsible for:

1. Obtaining a valid MATLAB license from MathWorks.
2. Installing MATLAB on the host where this plugin runs.
3. Installing the `matlabengine` Python package version that matches
   their MATLAB release (see `src/sim_plugin_matlab/compatibility.yaml`
   for the release ↔ engine pin table).

The Apache-2.0 license on this repository covers only the adapter code
in `src/sim_plugin_matlab/` and the bundled MATLAB-side helper
(`+sim_shim/run.m`), both of which are original work.

Use of MATLAB itself is governed by the MathWorks Software License
Agreement, not by this project's license.

# sim-plugin-matlab

[MATLAB](https://www.mathworks.com/products/matlab.html) driver for [sim-cli](https://github.com/svd-ai-lab/sim-cli), distributed as an out-of-tree plugin via Python `entry_points`.

This plugin delegates to MathWorks' `matlabengine` package and the local MATLAB binary. It does **not** bundle MATLAB or any MathWorks SDK — see [LICENSE-NOTICE.md](LICENSE-NOTICE.md).

## Install

```bash
pip install git+https://github.com/svd-ai-lab/sim-plugin-matlab@main
```

The right `matlabengine` pin depends on the MATLAB release installed on
your machine (24.1 ↔ R2024a, 24.2 ↔ R2024b, 25.1 ↔ R2025a, 25.2 ↔ R2025b).
The plugin declares an unpinned `matlabengine` dependency; let pip pick the
default and override with `pip install matlabengine==24.1` (or similar) if
the auto-selected version mismatches your MATLAB.

After install, sim-cli auto-discovers the driver:

```bash
sim drivers | grep matlab
sim run --solver matlab path/to/script.m
sim run --solver matlab path/to/model.slx
```

## How it works

The plugin registers via two entry-point groups:

```toml
[project.entry-points."sim.drivers"]
matlab = "sim_plugin_matlab:MatlabDriver"

[project.entry-points."sim.skills"]
matlab = "sim_plugin_matlab:skills_dir"
```

`sim.drivers` exposes the driver class; `sim.skills` exposes a directory
of skill files bundled inside the wheel.

`.m` scripts dispatch via `matlab -batch "run('<path>')"`. `.slx`/`.mdl`
Simulink models dispatch via `load_system → sim_shim.run → close_system`,
where `+sim_shim/run.m` is the MATLAB-side helper bundled under
`src/sim_plugin_matlab/matlab_pkg/`.

## Develop

```bash
git clone https://github.com/svd-ai-lab/sim-plugin-matlab
cd sim-plugin-matlab
uv sync
uv run pytest  # most tests need MATLAB + matlabengine; integration suite is skipped otherwise
```

## License

Apache-2.0. See [LICENSE](LICENSE) and [LICENSE-NOTICE.md](LICENSE-NOTICE.md).

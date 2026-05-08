# sim-plugin-matlab

[MATLAB](https://www.mathworks.com/products/matlab.html) and Simulink driver for [sim-cli](https://github.com/svd-ai-lab/sim-cli), distributed as a plugin via Python `entry_points`.

This plugin delegates to MathWorks' `matlabengine` package and the local MATLAB binary. It does **not** bundle MATLAB or any MathWorks SDK — see [LICENSE-NOTICE.md](LICENSE-NOTICE.md).

## Install

```bash
pip install git+https://github.com/svd-ai-lab/sim-plugin-matlab@main
```

For local persistent sessions, install the MathWorks engine SDK that matches
the MATLAB release installed on your machine (24.1 ↔ R2024a, 24.2 ↔ R2024b,
25.1 ↔ R2025a, 25.2 ↔ R2025b):

```bash
pip install matlabengine==24.1
```

The plugin keeps `matlabengine` optional because the SDK build itself requires
a matching local MATLAB installation. `sim env install matlab` can also choose
the matching SDK pin from `compatibility.yaml`.

After install, sim-cli auto-discovers the driver:

```bash
sim drivers | grep matlab
sim run --solver matlab path/to/script.m
sim run --solver matlab path/to/model.slx
```

## How it works

The plugin registers via three entry-point groups:

```toml
[project.entry-points."sim.drivers"]
matlab = "sim_plugin_matlab:MatlabDriver"

[project.entry-points."sim.skills"]
matlab = "sim_plugin_matlab:skills_dir"

[project.entry-points."sim.plugins"]
matlab = "sim_plugin_matlab:plugin_info"
```

`sim.drivers` exposes the driver class, `sim.skills` exposes the bundled skill
files, and `sim.plugins` exposes catalogue-style metadata for local discovery.

`.m` scripts dispatch via `matlab -batch "run('<path>')"`. `.slx`/`.mdl`
Simulink models dispatch via `load_system → sim_shim.run → close_system`,
where `+sim_shim/run.m` is the MATLAB-side helper bundled under
`src/sim_plugin_matlab/matlab_pkg/`.

## Develop

```bash
git clone https://github.com/svd-ai-lab/sim-plugin-matlab
cd sim-plugin-matlab
uv sync
uv run pytest  # unit tests run without MATLAB
SIM_MATLAB_RUN_INTEGRATION=1 uv run pytest tests/test_real_matlab_smoke.py -q
```

## License

Apache-2.0. See [LICENSE](LICENSE) and [LICENSE-NOTICE.md](LICENSE-NOTICE.md).

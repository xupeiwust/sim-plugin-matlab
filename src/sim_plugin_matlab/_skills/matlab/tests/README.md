# Tests

This folder is for MATLAB driver integration tests that exercise real `sim` + MATLAB behavior.

Planned focus:

- `uv run sim check matlab`
- `uv run sim lint` on `.m` files
- `uv run sim run --solver matlab` against small JSON-emitting fixtures
- `uv run sim connect --solver matlab` / `uv run sim exec` / `uv run sim disconnect` for local
  persistent MATLAB engine sessions

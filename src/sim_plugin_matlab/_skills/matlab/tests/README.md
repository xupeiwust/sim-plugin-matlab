# Tests

This folder is for MATLAB driver integration tests that exercise real `sim` + MATLAB behavior.

Planned focus:

- `sim check matlab`
- `sim lint` on `.m` files
- `sim run --solver matlab` against small JSON-emitting fixtures
- `sim connect --solver matlab` / `sim exec` / `sim disconnect` for local
  persistent MATLAB engine sessions

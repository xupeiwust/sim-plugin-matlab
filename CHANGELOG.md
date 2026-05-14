# Changelog

## 0.1.2 - 2026-05-15

- Detect MATLAB installs whose directory name doesn't follow the canonical
  `R20XXa` convention (e.g. Mathworks-China-style
  `E:\Program Files (x86)\Matlab_2024b\`). Release identification now reads
  `VersionInfo.xml` first — the Mathworks-published, locale-invariant
  source — and falls back to the path-string regex only when the XML is
  missing.
- Discovery now capability-sniffs `bin/matlab.exe` instead of name-matching
  the install directory. Mirrors the strategy-chain shape already used by
  the COMSOL driver: separate `_INSTALL_FINDERS` (where) from
  `_VERSION_PROBES` (which release).
- Windows default-path scan covers `C:`/`D:`/`E:`/`F:` × `Program Files`
  and `Program Files (x86)`, plus flat installs directly under those
  bases (not just under a `MATLAB\` subdir).
- Add a `_candidates_from_macos_defaults` finder for
  `/Applications/MATLAB_R20XXa.app/` layouts.

## 0.1.1 - 2026-05-11

- Prepare the first PyPI release with PyPI install instructions.
- Keep `matlabengine` optional so users can install the SDK version that
  matches their local MATLAB release.

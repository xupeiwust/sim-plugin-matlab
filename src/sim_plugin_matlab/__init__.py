"""MATLAB driver plugin for sim-cli.

Distributed as a plugin; discovered by sim-cli via the
``sim.drivers`` entry-point group. Bundled skill files (under ``_skills/``)
are exposed via the ``sim.skills`` entry-point group.
"""
from importlib.resources import files

from .driver import MatlabDriver

skills_dir = files(__name__) / "_skills"


plugin_info = {
    "name": "matlab",
    "summary": "MATLAB and Simulink driver plugin for sim-cli.",
    "homepage": "https://github.com/svd-ai-lab/sim-plugin-matlab",
    "license_class": "commercial",
    "solver_name": "matlab",
}

__all__ = ["MatlabDriver", "skills_dir", "plugin_info"]

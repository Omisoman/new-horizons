"""Where the repository lives — data, .env and the app tree hang off it.

In a source checkout (``uv sync`` installs the package editable) the root is
the directory holding ``pyproject.toml``. Installed as a wheel elsewhere
(sojourner's tiers import ``new_horizons.shared``) there is no checkout: the root
is ``HORIZONS_HOME`` when set, else the working directory.
"""

from __future__ import annotations

import os
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent
APP = PACKAGE / "app"


def _root() -> Path:
    if os.environ.get("HORIZONS_HOME"):
        return Path(os.environ["HORIZONS_HOME"]).resolve()
    checkout = PACKAGE.parents[1]
    return checkout if (checkout / "pyproject.toml").exists() else Path.cwd()


ROOT = _root()
DATA = ROOT / "data"

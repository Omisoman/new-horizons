"""Where the repository lives, and where its data lives.

ROOT — the checkout: the directory holding ``pyproject.toml`` (``.env``,
``docs/``, ``assets/`` hang off it). Installed as a wheel without a checkout,
the root is ``HORIZONS_HOME`` when set, else the working directory.

DATA — the generated data (analytics, KB, sample scans, UI settings, the audit
mirror): ``ROOT/data`` unless ``HORIZONS_DATA`` puts it elsewhere. sojourner
runs the app from trees it may not write (a read-only staging deploy, a
baseline bake) with the data on a writable volume — ROOT stays the code,
DATA moves.
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
DATA = Path(os.environ["HORIZONS_DATA"]).resolve() if os.environ.get("HORIZONS_DATA") else ROOT / "data"


def data_path(value: str | None, default: str) -> Path:
    """A configured location (an env var's value) as a path. Unset: DATA/default.
    Absolute: as given. ``data/…``: under DATA, wherever HORIZONS_DATA put it.
    Any other relative path: under ROOT."""
    if not value:
        return DATA / default
    p = Path(value)
    if p.is_absolute():
        return p
    if p.parts and p.parts[0] == "data":
        return DATA.joinpath(*p.parts[1:])
    return ROOT / p

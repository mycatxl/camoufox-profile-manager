"""PyInstaller entry point for the desktop app.

The frozen build is portable: the database, the `.env` file placed beside the
executable, and everything camoufox downloads — the browser, the GeoIP databases,
the addons — all live inside the folder that was unzipped. Deleting that folder
is therefore a complete uninstall. Running this file from a source checkout
changes none of that; :func:`_anchor` only acts inside a bundle.
"""

import os
import sys
from pathlib import Path

PORTABLE_CACHE_DIRNAME = "portable"


def _anchor() -> None:
    """Pin every runtime path to the folder holding the executable.

    A no-op outside a PyInstaller bundle (``sys.frozen``), so a checkout keeps
    its usual behaviour.
    """
    if not getattr(sys, "frozen", False):
        return

    root = Path(sys.executable).resolve().parent

    # Relative paths — ``data/profiles.db``, the ``.env`` file — resolve against
    # the working directory, which a shortcut or a shell can point anywhere.
    os.chdir(root)

    # camoufox keeps the browser, the GeoIP databases and the addons under
    # platformdirs' per-user cache directory, which would escape the folder: half
    # a gigabyte of it after a `fetch`. platformdirs honours this override for
    # CSIDL_LOCAL_APPDATA, and every one of those paths goes through it.
    # setdefault, so an override the user set deliberately still wins.
    os.environ.setdefault(
        "WIN_PD_OVERRIDE_LOCAL_APPDATA", str(root / PORTABLE_CACHE_DIRNAME)
    )


def main() -> None:
    """Anchor the portable layout, then hand over to the CLI."""
    _anchor()

    # Imported here rather than at the top: camoufox computes its cache
    # directory at import time (``pkgman.INSTALL_DIR`` and
    # ``geolocation.GEOIP_DIR`` are module-level), so the override above has to
    # be in place before any of it loads.
    from camoufox_pm.cli import main as run_cli

    run_cli()


if __name__ == "__main__":
    main()

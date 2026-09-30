"""PyInstaller entry point for the desktop app.

The frozen build is portable: the database, the `.env` file placed beside the
executable, and everything camoufox downloads — the browser, the GeoIP databases,
the addons — all live inside the folder that was unzipped. Deleting that folder
is therefore a complete uninstall. Running this file from a source checkout
changes none of that; :func:`_anchor` only acts inside a bundle.

The browser binary keeps one directory of its own outside the folder, which no
Python-level switch can move; :func:`_clear_browser_leftovers` clears it.
"""

import os
import sys
from pathlib import Path

PORTABLE_CACHE_DIRNAME = "portable"

# Firefox's pre-XUL skeleton UI is compiled into the browser's mozglue.dll and
# writes its lock file to "%LOCALAPPDATA%\<vendor>\<name>" using the names baked
# in at build time — for this browser, "Camoufox" twice. It runs before XUL
# exists, so it never consults platformdirs and WIN_PD_OVERRIDE_LOCAL_APPDATA
# cannot move it. The lock itself is gone by the time the browser exits; this
# only sweeps up what a crash leaves behind.
BROWSER_APP_DIRNAME = "Camoufox"
SKELETON_LOCK_PREFIX = "SkeletonUILock-"


def _local_appdata() -> Path | None:
    """The per-user local app data directory, or None when it is not defined."""
    value = os.environ.get("LOCALAPPDATA")
    return Path(value) if value else None


def _clear_browser_leftovers(local_appdata: Path | None = None) -> list[Path]:
    """Remove the browser's own leftovers from outside the package folder.

    Deletes the lock files and then the directories that held them, and nothing
    else: the whole tree is left alone unless every entry in it is one of those
    lock files. A real Camoufox install, or the cache an older non-portable
    build of this app left behind, therefore stays untouched.

    Returns what was removed, which is what the tests assert on.
    """
    base = local_appdata if local_appdata is not None else _local_appdata()
    if base is None:
        return []

    target = base / BROWSER_APP_DIRNAME / BROWSER_APP_DIRNAME
    if not target.is_dir():
        return []

    entries = list(target.iterdir())
    if any(not (e.is_file() and e.name.startswith(SKELETON_LOCK_PREFIX)) for e in entries):
        return []

    removed: list[Path] = []
    for entry in entries:
        entry.unlink()
        removed.append(entry)
    for directory in (target, target.parent):
        if directory != base and not any(directory.iterdir()):
            directory.rmdir()
            removed.append(directory)
    return removed


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
    os.environ.setdefault("WIN_PD_OVERRIDE_LOCAL_APPDATA", str(root / PORTABLE_CACHE_DIRNAME))

    # The browser binary has one directory of its own that no environment
    # variable reaches, so sweep that one instead.
    try:
        _clear_browser_leftovers()
    except OSError:
        # A locked file is a reason to leave the folder alone, not to refuse to
        # start. Whatever survived is cleaned up on the next run.
        pass


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

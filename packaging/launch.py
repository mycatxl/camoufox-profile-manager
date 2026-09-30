"""PyInstaller entry point for the desktop app.

The frozen build is portable: the database, the `.env` file placed beside the
executable, and everything camoufox downloads — the browser, the GeoIP databases,
the addons — all live inside the folder that was unzipped. Deleting that folder
is therefore a complete uninstall. Running this file from a source checkout
changes none of that; :func:`_anchor` only acts inside a bundle.

The browser binary keeps one directory of its own outside the folder, which no
Python-level switch can move; :func:`_clear_browser_leftovers` clears it.

The Windows build has no console, which is what keeps a terminal window from
opening beside the desktop app. Output therefore goes to the console this process
was started from when there is one, and otherwise into ``logs/camoufox-pm.log``
beside the executable, so a start that fails is still diagnosable.
"""

import io
import os
import sys
from datetime import datetime
from pathlib import Path

PORTABLE_CACHE_DIRNAME = "portable"

# A windowed build on Windows has no stdout or stderr at all (see the spec), so
# _redirect_output gives the process one of two places to write: the console it
# was started from, or this file inside the package folder.
LOG_DIRNAME = "logs"
LOG_FILENAME = "camoufox-pm.log"
LOG_ROTATE_BYTES = 5 * 1024 * 1024

_ATTACH_PARENT_PROCESS = 0xFFFFFFFF


def _attach_parent_console() -> bool:
    """Borrow the console of the process that started us, if there is one.

    A windowed Windows build is not attached to any console, so `camoufox-pm
    fetch` run from a terminal would print nothing at all. Attaching puts that
    output back. False means there was no console to borrow — a double-click —
    and the caller falls back to a log file.
    """
    if sys.platform != "win32":
        return False
    try:
        import ctypes

        if not ctypes.windll.kernel32.AttachConsole(_ATTACH_PARENT_PROCESS):
            return False
        sys.stdout = open("CONOUT$", "w", encoding="utf-8", buffering=1)
        sys.stderr = open("CONOUT$", "w", encoding="utf-8", buffering=1)
        if sys.stdin is None:
            try:
                sys.stdin = open("CONIN$", encoding="utf-8")
            except OSError:
                # Only the interactive prompts need it, and they can fail loudly.
                pass
        return True
    except (AttributeError, OSError):
        return False


def _open_log(path: Path) -> io.TextIOWrapper:
    """Open the log for appending, moving one previous file out of the way.

    The server logs a line per request, so this would grow without bound over the
    life of an install.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.stat().st_size > LOG_ROTATE_BYTES:
        previous = path.with_suffix(path.suffix + ".1")
        previous.unlink(missing_ok=True)
        path.rename(previous)
    handle = path.open("a", encoding="utf-8", buffering=1)
    handle.write(
        f"\n--- {datetime.now().isoformat(timespec='seconds')} "
        f"{sys.executable} (python {sys.version.split()[0]}) ---\n"
    )
    return handle


def _redirect_output(root: Path) -> Path | None:
    """Point stdout and stderr somewhere, for a build that has neither.

    Returns the log path when a file was opened, or None when the process already
    had a stream — a console build, or a source checkout.
    """
    if sys.stdout is not None and sys.stderr is not None:
        return None
    if _attach_parent_console():
        return None

    handle = _open_log(root / LOG_DIRNAME / LOG_FILENAME)
    sys.stdout = handle
    sys.stderr = handle
    return root / LOG_DIRNAME / LOG_FILENAME


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

    # A windowed build has no console at all. Give the process somewhere to
    # write before anything imports loguru, whose default handler needs a stream.
    _redirect_output(root)

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

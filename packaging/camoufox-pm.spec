# PyInstaller spec for the Camoufox Profile Manager desktop app.
#
# Build (after `python scripts/build_webui.py`):
#   pyinstaller packaging/camoufox-pm.spec --noconfirm --clean
#
# Produces dist/camoufox-pm/ (a standalone bundle) and, on macOS, a .app.
# The browser, the GeoIP databases and the addons are not part of this bundle;
# the Windows build installs them into the package directory afterwards.
import os
import sys

from PyInstaller.utils.hooks import collect_all, collect_submodules

# SPECPATH is this file's directory (packaging/); ROOT is the repository root.
ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))

datas = [(os.path.join(ROOT, "src", "camoufox_pm", "webui"), "camoufox_pm/webui")]
binaries = []
hiddenimports = collect_submodules("uvicorn")

# These packages ship data files (fingerprint datapoints, language tags, …) that
# PyInstaller does not pick up automatically.
for _pkg in (
    "camoufox",
    "browserforge",
    "apify_fingerprint_datapoints",
    "language_tags",
    "ua_parser",
):
    _d, _b, _h = collect_all(_pkg)
    datas += _d
    binaries += _b
    hiddenimports += _h

a = Analysis(
    [os.path.join(SPECPATH, "launch.py")],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="camoufox-pm",
    # No console window: this is the desktop app, and a black terminal sitting
    # next to it is the first thing anyone asks about. The price is that a frozen
    # build has no stdout or stderr, which launch.py pays back by attaching to the
    # console it was started from (so `camoufox-pm fetch` still prints there) and
    # writing logs/camoufox-pm.log instead when it was double-clicked.
    # Left alone elsewhere: on macOS this only changes whether the bundle opens a
    # Terminal window, and nothing has been verified against that.
    console=sys.platform != "win32",
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    name="camoufox-pm",
)
app = BUNDLE(
    coll,
    name="Camoufox Profile Manager.app",
    bundle_identifier="com.github.polyackiy.camoufox-pm",
)

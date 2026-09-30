"""Put the GeoIP databases and the default addons inside the desktop package.

`camoufox fetch` installs these itself (camoufox/__main__.py), but the desktop
build only calls the browser downloader, so without this step they would arrive
on the first profile launch instead of being in the zip. That first launch needs
an internet connection for ~45 MB, which is the difference between "unzip and
run" and "unzip, run, and hope the network is there".

Every path here goes through platformdirs, so running this with
``WIN_PD_OVERRIDE_LOCAL_APPDATA`` pointing at the package's ``portable``
directory puts the databases and the addons beside the browser that
``camoufox-pm fetch`` already installed. The workflow sets exactly that variable
for this step and for the browser download.

Deleting the unzipped folder still removes all of it.
"""

from camoufox.addons import ADDONS_DIR, DefaultAddons, maybe_download_addons
from camoufox.geolocation import MMDB_DIR, download_mmdb


def main() -> None:
    """Download both, then refuse to report success unless they are really there."""
    download_mmdb()
    maybe_download_addons(list(DefaultAddons))

    # maybe_download_addons prints a warning and carries on when a download
    # fails, so ask the filesystem what actually landed. A package that quietly
    # needs the network on first launch should fail the build instead.
    missing_addons = [a.name for a in DefaultAddons if not (ADDONS_DIR / a.name).is_dir()]
    if missing_addons:
        raise SystemExit(f"addons not installed into {ADDONS_DIR}: {missing_addons}")

    databases = sorted(p.name for p in MMDB_DIR.glob("*.mmdb"))
    if not databases:
        raise SystemExit(f"no GeoIP database installed into {MMDB_DIR}")

    print(f"addons  : {sorted(a.name for a in DefaultAddons)} in {ADDONS_DIR}")
    print(f"geoip   : {databases} in {MMDB_DIR}")


if __name__ == "__main__":
    main()

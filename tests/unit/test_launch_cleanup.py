"""The one directory the browser writes outside the package folder.

The browser binary's pre-XUL skeleton UI puts a lock file in
``%LOCALAPPDATA%\\Camoufox\\Camoufox`` — a path baked into mozglue.dll, so no
environment variable reaches it. ``packaging/launch.py`` sweeps it at startup.

That file is loaded by path rather than imported, because ``packaging`` is also
the name of a real distribution and ``import packaging.launch`` would find that
one instead.
"""

import importlib.util
from pathlib import Path

LAUNCH_PY = Path(__file__).resolve().parents[2] / "packaging" / "launch.py"


def _load_launch():
    spec = importlib.util.spec_from_file_location("camoufox_pm_launch_under_test", LAUNCH_PY)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


launch = _load_launch()


def _browser_dir(base: Path) -> Path:
    """The directory the browser binary derives from its own baked-in name."""
    return base / "Camoufox" / "Camoufox"


def _lock() -> str:
    """A lock file name, with the hash shape the browser actually uses."""
    return "SkeletonUILock-ed9e719b"


def test_the_entry_point_is_where_this_test_expects_it():
    assert LAUNCH_PY.is_file()
    assert launch.BROWSER_APP_DIRNAME == "Camoufox"


def test_nothing_to_clean_is_not_an_error(tmp_path):
    assert launch._clear_browser_leftovers(tmp_path) == []
    assert list(tmp_path.iterdir()) == []


def test_a_lock_left_by_a_crash_is_removed_with_its_directories(tmp_path):
    target = _browser_dir(tmp_path)
    target.mkdir(parents=True)
    lock = target / _lock()
    lock.write_bytes(b"")

    removed = launch._clear_browser_leftovers(tmp_path)

    assert lock in removed
    assert not lock.exists()
    assert not target.exists()
    assert not (tmp_path / "Camoufox").exists()


def test_empty_directories_are_removed_too(tmp_path):
    target = _browser_dir(tmp_path)
    target.mkdir(parents=True)

    removed = launch._clear_browser_leftovers(tmp_path)

    assert target in removed
    assert not (tmp_path / "Camoufox").exists()


def test_a_real_install_is_left_alone(tmp_path):
    """A Camoufox someone installed for real keeps its cache."""
    target = _browser_dir(tmp_path)
    (target / "Cache" / "geoip").mkdir(parents=True)
    lock = target / _lock()
    lock.write_bytes(b"")

    assert launch._clear_browser_leftovers(tmp_path) == []
    assert lock.exists()
    assert (target / "Cache" / "geoip").is_dir()


def test_one_foreign_file_stops_the_cleanup(tmp_path):
    target = _browser_dir(tmp_path)
    target.mkdir(parents=True)
    lock = target / _lock()
    lock.write_bytes(b"")
    foreign = target / "profiles.ini"
    foreign.write_text("[Profile0]\n")

    assert launch._clear_browser_leftovers(tmp_path) == []
    assert lock.exists()
    assert foreign.exists()


def test_a_directory_named_like_a_lock_stops_the_cleanup(tmp_path):
    target = _browser_dir(tmp_path)
    (target / _lock()).mkdir(parents=True)

    assert launch._clear_browser_leftovers(tmp_path) == []
    assert (target / _lock()).is_dir()


def test_an_undefined_local_app_data_is_a_no_op(monkeypatch):
    monkeypatch.delenv("LOCALAPPDATA", raising=False)

    assert launch._clear_browser_leftovers() == []


def test_the_environment_variable_is_used_when_no_path_is_given(tmp_path, monkeypatch):
    target = _browser_dir(tmp_path)
    target.mkdir(parents=True)
    lock = target / _lock()
    lock.write_bytes(b"")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    removed = launch._clear_browser_leftovers()

    assert lock in removed
    assert not (tmp_path / "Camoufox").exists()

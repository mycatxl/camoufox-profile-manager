"""Where a consoleless Windows build sends its output.

The desktop build is windowed (``console=False`` in the spec), so the frozen
process starts with ``sys.stdout`` and ``sys.stderr`` set to None. ``launch.py``
either borrows the console it was started from or opens a log file inside the
package folder. Without one of the two, loguru's default handler breaks on the
first log line — which is exactly why the build used to keep a console window.

Loaded by path, because ``packaging`` is also the name of a real distribution.
"""

import importlib.util
import sys
from pathlib import Path

LAUNCH_PY = Path(__file__).resolve().parents[2] / "packaging" / "launch.py"


def _load_launch():
    spec = importlib.util.spec_from_file_location("camoufox_pm_launch_output_test", LAUNCH_PY)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


launch = _load_launch()


def _no_console(monkeypatch):
    """Make the process look like a double-clicked windowed build."""
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    monkeypatch.setattr(launch, "_attach_parent_console", lambda: False)


def test_a_process_that_already_has_streams_is_left_alone(tmp_path):
    assert launch._redirect_output(tmp_path) is None
    assert not (tmp_path / "logs").exists()


def test_started_from_a_console_it_borrows_that_console(tmp_path, monkeypatch):
    _no_console(monkeypatch)
    monkeypatch.setattr(launch, "_attach_parent_console", lambda: True)

    assert launch._redirect_output(tmp_path) is None
    assert not (tmp_path / "logs").exists()


def test_a_double_clicked_run_gets_a_log_inside_the_folder(tmp_path, monkeypatch):
    _no_console(monkeypatch)

    path = launch._redirect_output(tmp_path)

    try:
        assert path == tmp_path / "logs" / "camoufox-pm.log"
        assert path is not None and path.is_file()
        assert sys.stdout is sys.stderr, "both streams have to be usable, not just one"
        print("a line the log has to keep")
        sys.stdout.flush()
        written = path.read_text(encoding="utf-8")
        assert "a line the log has to keep" in written
        assert f"python {sys.version.split()[0]}" in written, "the header names the build"
    finally:
        handle = sys.stdout
        if handle is not None:
            handle.close()


def test_the_log_keeps_growing_while_it_is_small(tmp_path, monkeypatch):
    monkeypatch.setattr(launch, "LOG_ROTATE_BYTES", 10_000)
    log = tmp_path / "logs" / "camoufox-pm.log"
    log.parent.mkdir(parents=True)
    log.write_text("earlier run\n", encoding="utf-8")

    launch._open_log(log).close()

    assert "earlier run" in log.read_text(encoding="utf-8")
    assert not log.with_suffix(".log.1").exists()


def test_a_large_log_is_rotated_before_the_new_run(tmp_path, monkeypatch):
    monkeypatch.setattr(launch, "LOG_ROTATE_BYTES", 10)
    log = tmp_path / "logs" / "camoufox-pm.log"
    log.parent.mkdir(parents=True)
    log.write_text("x" * 500, encoding="utf-8")
    previous = tmp_path / "logs" / "camoufox-pm.log.1"

    launch._open_log(log).close()

    assert previous.read_text(encoding="utf-8") == "x" * 500
    assert log.stat().st_size < 500, "the run that just started gets a fresh file"


def test_rotating_twice_keeps_only_the_previous_run(tmp_path, monkeypatch):
    monkeypatch.setattr(launch, "LOG_ROTATE_BYTES", 10)
    log = tmp_path / "logs" / "camoufox-pm.log"
    log.parent.mkdir(parents=True)
    log.write_text("first\n" + "x" * 500, encoding="utf-8")
    launch._open_log(log).close()
    log.write_text("second\n" + "y" * 500, encoding="utf-8")

    launch._open_log(log).close()

    previous = (tmp_path / "logs" / "camoufox-pm.log.1").read_text(encoding="utf-8")
    assert "second" in previous
    assert "first" not in previous


def test_borrowing_a_console_is_windows_only(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")

    assert launch._attach_parent_console() is False

"""The one-click launcher (run.py at the repo root) for people running from source."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import run  # noqa: E402


def test_old_python_is_refused_with_a_clear_message():
    message = run.check_python((3, 10, 4))
    assert message and "3.12" in message and "python.org" in message
    assert run.check_python((3, 12, 0)) is None
    assert run.check_python((3, 13, 1)) is None


def test_needs_install_until_stamp_matches(tmp_path):
    venv = tmp_path / ".venv"
    venv.mkdir()
    assert run.needs_install(venv, "abc")
    run.write_stamp(venv, "abc")
    assert not run.needs_install(venv, "abc")
    assert run.needs_install(venv, "changed")  # app updated -> reinstall


def test_install_stamp_follows_pyproject(tmp_path):
    p = tmp_path / "pyproject.toml"
    p.write_text("a")
    first = run.install_stamp(p)
    p.write_text("b")
    assert run.install_stamp(p) != first


def test_venv_python_paths(tmp_path):
    gui = run.venv_python(tmp_path, gui=True)
    console = run.venv_python(tmp_path, gui=False)
    if sys.platform == "win32":
        assert gui == tmp_path / "Scripts" / "pythonw.exe"
        assert console == tmp_path / "Scripts" / "python.exe"
    else:
        assert gui == console == tmp_path / "bin" / "python"


def test_setup_output_goes_to_log_not_screen(tmp_path, capfd):
    import subprocess

    import pytest

    log = tmp_path / "setup.log"
    run.run_logged([sys.executable, "-c", "print('noisy build warning')"], log)
    assert "noisy build warning" in log.read_text(encoding="utf-8")
    assert "noisy build warning" not in capfd.readouterr().out
    with pytest.raises(subprocess.CalledProcessError):
        run.run_logged([sys.executable, "-c", "import sys; sys.exit(3)"], log)

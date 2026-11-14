"""Start PDF Touch-up from the source code: `python run.py` (or double-click run.bat).

The first run sets up a private Python environment in .venv and installs what the app needs
(this needs internet once and takes a few minutes). Later runs just open the app.
Running from source works even where Windows Smart App Control blocks the installer,
because only Python itself (signed by the Python Software Foundation) is started.
"""
from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
PYPROJECT = ROOT / "pyproject.toml"
STAMP_NAME = ".pdf-touchup-installed"
SETUP_LOG = ROOT / "setup.log"
MIN_PYTHON = (3, 12)


def check_python(version: tuple) -> str | None:
    """A message for the user if this Python is too old, else None."""
    if tuple(version[:2]) >= MIN_PYTHON:
        return None
    have = ".".join(str(v) for v in version[:3])
    return (f"PDF Touch-up needs Python 3.12 or newer, but this is Python {have}.\n"
            "Install the latest Python from https://www.python.org/downloads/ "
            "(tick \"Add python.exe to PATH\"), then run this again.")


def venv_python(venv: Path, gui: bool) -> Path:
    if sys.platform == "win32":
        return venv / "Scripts" / ("pythonw.exe" if gui else "python.exe")
    return venv / "bin" / "python"


def install_stamp(pyproject: Path) -> str:
    """Changes whenever the app's requirements change, so an update triggers a reinstall."""
    return hashlib.sha256(pyproject.read_bytes()).hexdigest()


def needs_install(venv: Path, stamp: str) -> bool:
    marker = venv / STAMP_NAME
    return not marker.is_file() or marker.read_text(encoding="utf-8").strip() != stamp


def write_stamp(venv: Path, stamp: str) -> None:
    (venv / STAMP_NAME).write_text(stamp, encoding="utf-8")


def run_logged(cmd: list, log: Path) -> None:
    """Run a setup step, keeping its (often noisy) output in a log file instead of on screen."""
    with open(log, "a", encoding="utf-8") as out:
        subprocess.run([str(c) for c in cmd], check=True, cwd=ROOT, stdout=out, stderr=subprocess.STDOUT)


def setup() -> None:
    stamp = install_stamp(PYPROJECT)
    if not venv_python(VENV, gui=False).is_file():
        print("First run: setting up PDF Touch-up (this takes a few minutes)...")
        run_logged([sys.executable, "-m", "venv", VENV], SETUP_LOG)
    if needs_install(VENV, stamp):
        print("Installing what PDF Touch-up needs (internet required this once)...")
        py = venv_python(VENV, gui=False)
        run_logged([py, "-m", "pip", "install", "--disable-pip-version-check", "--upgrade", "pip"], SETUP_LOG)
        run_logged([py, "-m", "pip", "install", "--disable-pip-version-check", "-e", ROOT], SETUP_LOG)
        write_stamp(VENV, stamp)
        print("Done.")


def main() -> int:
    problem = check_python(sys.version_info)
    if problem:
        print(problem)
        return 1
    try:
        setup()
    except subprocess.CalledProcessError:
        print("\nSetup failed. Check your internet connection and run this again.\n"
              "If it keeps failing, delete the .venv folder next to run.py and retry.")
        return 1
    # Open the app without a console window; any PDF path given is passed along.
    subprocess.Popen([str(venv_python(VENV, gui=True)), "-m", "pdf_touchup", *sys.argv[1:]], cwd=ROOT)
    return 0


if __name__ == "__main__":
    sys.exit(main())

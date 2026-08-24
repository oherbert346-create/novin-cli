"""Install or update the local Novin terminal. Does not start a server."""
from __future__ import annotations

import os
import stat
import subprocess
import tarfile
import tempfile
from pathlib import Path

import httpx

from novin import __version__

CLI_REPO = os.environ.get("NOVIN_CLI_REPO", "oherbert346-create/novin-cli")
CLI_BRANCH = os.environ.get("NOVIN_CLI_BRANCH", "main")


def novin_home() -> Path:
    return Path(os.environ.get("NOVIN_HOME") or (Path.home() / ".novin"))


def bin_dir() -> Path:
    return Path(os.environ.get("NOVIN_BIN") or (Path.home() / ".local" / "bin"))


def venv_python() -> Path:
    return novin_home() / "venv" / "bin" / "python"


def wrapper_path() -> Path:
    return bin_dir() / "novin"


def current_version() -> str:
    return __version__


def _ensure_venv() -> Path:
    py = venv_python()
    if py.is_file():
        return py
    novin_home().mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [os.environ.get("NOVIN_PYTHON") or "python3", "-m", "venv", str(novin_home() / "venv")],
        check=True,
    )
    return py


def _download_latest(dest: Path) -> Path:
    url = f"https://codeload.github.com/{CLI_REPO}/tar.gz/refs/heads/{CLI_BRANCH}"
    archive = dest / "novin.tar.gz"
    with httpx.Client(timeout=60.0, follow_redirects=True) as client:
        response = client.get(url)
        response.raise_for_status()
        archive.write_bytes(response.content)
    with tarfile.open(archive, "r:gz") as tar:
        tar.extractall(dest)
    matches = [path for path in dest.iterdir() if path.is_dir() and path.name.startswith("novin-cli-")]
    if not matches or not (matches[0] / "pyproject.toml").is_file():
        raise RuntimeError("could not unpack the Novin terminal package")
    return matches[0]


def _write_wrapper(python_bin: Path) -> bool:
    """Write ~/.local/bin/novin when missing, or when it already launches the local venv."""
    path = wrapper_path()
    body = (
        "#!/bin/sh\n"
        "# Local Novin terminal. Does not start a server.\n"
        f'exec "{python_bin.parent / "novin"}" "$@"\n'
    )
    if path.is_file():
        existing = path.read_text(errors="replace")
        if str(novin_home() / "venv") not in existing:
            return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return True


def update_local_install() -> dict[str, str | bool]:
    """Replace this machine's installed terminal with the latest published package.

    Already-installed copies stay put until this runs. A new install always
    gets the current package.
    """
    python_bin = _ensure_venv()
    subprocess.run([str(python_bin), "-m", "pip", "install", "-q", "--upgrade", "pip"], check=True)
    with tempfile.TemporaryDirectory() as raw:
        src = _download_latest(Path(raw))
        # Same public version (1.0.0) can still ship new terminal files.
        subprocess.run(
            [
                str(python_bin),
                "-m",
                "pip",
                "install",
                "-q",
                "--upgrade",
                "--force-reinstall",
                "--no-cache-dir",
                str(src),
            ],
            check=True,
        )
    wrote = _write_wrapper(python_bin)
    return {
        "version": current_version(),
        "venv": str(python_bin),
        "wrapper": str(wrapper_path()),
        "wrapper_written": wrote,
    }

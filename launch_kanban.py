"""launch_kanban.py
Bootstrap + run script for the Flask Kanban app.
* Creates (or re-uses) a local virtualenv
* Installs/updates Flask + Flask-SQLAlchemy inside it
* Starts kanban_app.py in a child process
* Polls http://localhost:5000 until it responds, then auto-opens the browser
Usage:
    python launch_kanban.py
Env vars:
    KANBAN_VENV  Path for virtualenv dir (default .venv)
    KANBAN_PORT  Port to bind (default 5000)
"""
from __future__ import annotations

import http.client
import os
import subprocess
import sys
import time
import venv
import webbrowser
from pathlib import Path

REQUIRED = [
    "flask>=3.0",
    "flask_sqlalchemy>=3.1",
]

PORT = int(os.getenv("KANBAN_PORT", 5000))


def ensure_venv(path: Path) -> Path:
    if not path.exists():
        print(f"[+] Creating virtualenv at {path}")
        venv.create(path, with_pip=True)
    python = path / ("Scripts" if os.name == "nt" else "bin") / ("python.exe" if os.name == "nt" else "python")
    if not python.exists():
        sys.exit("❌ Could not locate python inside virtualenv")
    return python


def pip_install(python: Path) -> None:
    need = []
    for pkg in REQUIRED:
        name, version_spec = pkg.split(">=", 1)
        try:
            subprocess.check_call(
                [python, "-c", f"import importlib.metadata, sys; "
                               f"sys.exit(importlib.metadata.version('{name}') < '{version_spec}')"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        except subprocess.CalledProcessError:
            need.append(pkg)

    if need:
        subprocess.check_call([python, "-m", "pip", "install", "--upgrade", *need])


def start_server(python: Path, base: Path) -> subprocess.Popen:
    print("[✓] Dependencies satisfied — launching server …")
    return subprocess.Popen(
        [str(python), "-u", str(base / "kanban_app.py")],
        cwd=base,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def wait_until_up(port: int, timeout: int = 15) -> bool:
    start = time.time()
    while time.time() - start < timeout:
        try:
            conn = http.client.HTTPConnection("localhost", port, timeout=1)
            conn.request("GET", "/")
            if conn.getresponse().status == 200:
                return True
        except (ConnectionRefusedError, http.client.HTTPException, OSError):
            pass
        time.sleep(0.5)
    return False


def main():
    base = Path(__file__).resolve().parent
    env_dir = Path(os.getenv("KANBAN_VENV", base / ".venv")).resolve()
    python = ensure_venv(env_dir)
    pip_install(python)

    proc = start_server(python, base)

    if wait_until_up(PORT):
        url = f"http://localhost:{PORT}"
        print(f"[🌐] Opening {url}")
        webbrowser.open(url)
    else:
        print("❌ Server did not start within timeout.")
        proc.terminate()
        sys.exit(1)

    # Stream server logs to console.
    try:
        for line in proc.stdout:  # type: ignore[attr-defined]
            print(line, end="")
    finally:
        proc.wait()


if __name__ == "__main__":
    main()

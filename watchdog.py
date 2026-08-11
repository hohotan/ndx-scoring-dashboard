"""
watchdog.py - keep serve.py alive
=================================
Launches serve.py as a subprocess, watches it, and restarts on crash.
Designed to be invoked by the Startup-folder VBS launcher at user logon.

Logs to serve.watchdog.log in the same directory.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent
PYTHON_EXE = sys.executable  # use whatever python is running us (pythonw.exe)
LOG_PATH = OUT_DIR / "serve.watchdog.log"

# If we ourselves die, the parent VBS will respawn us. Keep this script
# tiny and robust — no fancy deps.

CREATE_NO_WINDOW = 0x08000000  # Win: hide console window

_max_restarts_per_minute = 10  # safety: prevent crash loops


def log(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, file=sys.stderr)
    try:
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def spawn_serve() -> subprocess.Popen:
    return subprocess.Popen(
        [PYTHON_EXE, "serve.py"],
        cwd=str(OUT_DIR),
        creationflags=CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def main():
    log("watchdog starting")
    restarts_in_window: list[float] = []
    while True:
        proc = spawn_serve()
        log(f"spawned serve.py pid={proc.pid}")
        # Wait for it to die
        rc = proc.wait()
        log(f"serve.py exited rc={rc}")

        now = time.time()
        restarts_in_window.append(now)
        # Trim entries older than 60s
        restarts_in_window = [t for t in restarts_in_window if now - t < 60]

        if len(restarts_in_window) > _max_restarts_per_minute:
            log(f"TOO MANY RESTARTS ({len(restarts_in_window)} in 60s); pausing 5 min")
            time.sleep(300)
            restarts_in_window.clear()
            continue

        # Cooldown before restart
        time.sleep(3)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
    except Exception as e:
        log(f"watchdog FATAL: {e}")
        sys.exit(1)
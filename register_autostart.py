"""
register_autostart.py - Register watchdog.py to auto-start at user login
========================================================================
Uses the Task Scheduler COM API (no schtasks.exe needed, works without
admin elevation in most cases). If that fails, falls back to dropping a
shortcut in the user's Startup folder.

Python interpreter is auto-detected: prefers a bundled `python\\pythonw.exe`
inside the project (Method 3 - portable bundle). Falls back to the currently
running interpreter if no embedded Python is found.

Usage:
    python register_autostart.py install    # register auto-start
    python register_autostart.py remove     # unregister
    python register_autostart.py status     # check
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

# Auto-detect: project lives next to this script
WORK_DIR = str(Path(__file__).resolve().parent)

# Auto-detect Python: prefer EMBEDDED python.exe in ./python/ (Method 3 portable).
# Falls back to current interpreter (sys.executable) if no embedded copy found.
_EMBED_PY      = Path(WORK_DIR) / "python" / "python.exe"
_EMBED_PYW     = Path(WORK_DIR) / "python" / "pythonw.exe"
if _EMBED_PY.exists():
    PYTHON_EXE = str(_EMBED_PY)
    PYTHONW_EXE = str(_EMBED_PYW if _EMBED_PYW.exists() else _EMBED_PY)
else:
    PYTHON_EXE  = sys.executable
    PYTHON_DIR  = str(Path(sys.executable).parent)
    _pyexe_stem = Path(sys.executable).stem              # "python" or "python3"
    _pw_candidate = Path(PYTHON_DIR) / f"{_pyexe_stem.replace('python', 'pythonw')}.exe"
    PYTHONW_EXE = str(_pw_candidate) if _pw_candidate.exists() else PYTHON_EXE

LAUNCHER    = "watchdog.py"   # watchdog launches serve.py and restarts on crash
TASK_NAME   = "NDXDashboard"
LOG_FILE    = Path(WORK_DIR) / "serve.log"
ERR_FILE    = Path(WORK_DIR) / "serve.err.log"


def _build_command() -> str:
    """Command string for the task. Uses pythonw.exe (no console window)."""
    return f'"{PYTHONW_EXE}" "{WORK_DIR}\\{LAUNCHER}"'


def _register_via_taskscheduler() -> bool:
    """Try to register via Task Scheduler COM API."""
    try:
        import win32com.client
    except ImportError:
        print("  [skip] pywin32 not available")
        return False

    try:
        scheduler = win32com.client.Dispatch("Schedule.Service")
        scheduler.Connect()
        root = scheduler.GetFolder("\\")

        # Delete existing if any
        try:
            root.DeleteTask(TASK_NAME, 0)
        except Exception:
            pass

        task = scheduler.NewTask(0)
        # General settings
        task.Settings.MultipleInstances = 1   # TASK_INSTANCES_IGNORE_NEW
        task.Settings.DisallowStartIfOnBatteries = False
        task.Settings.StopIfGoingOnBatteries = False
        task.Settings.AllowDemandStart = True
        task.Settings.Enabled = True

        # Trigger: at logon
        trig = task.Triggers.Create(9)  # TASK_TRIGGER_LOGON = 9
        # default user is current

        # Action: run watchdog (which launches serve.py)
        action = task.Actions.Create(0)  # TASK_ACTION_EXEC
        action.Path = PYTHONW_EXE
        action.Arguments = f'"{WORK_DIR}\\{LAUNCHER}"'
        action.WorkingDirectory = WORK_DIR

        # Register
        root.RegisterTaskDefinition(
            TASK_NAME,
            task,
            6,    # TASK_CREATE_OR_UPDATE
            "",   # no user
            "",   # no password
            0,    # TASK_LOGON_NONE (run as current user)
        )
        print(f"  [OK] Registered via Task Scheduler COM as '{TASK_NAME}'")
        return True
    except Exception as e:
        print(f"  [skip] Task Scheduler COM failed: {e}")
        return False


def _register_via_startup_folder() -> bool:
    """Fallback: drop a .bat (via pythonw) shortcut in Startup folder."""
    startup = Path(os.environ["APPDATA"]) / "Microsoft/Windows/Start Menu/Programs/Startup"
    if not startup.exists():
        print(f"  [skip] Startup folder not found: {startup}")
        return False

    # Use a VBS launcher to avoid cmd window flash
    vbs_content = (
        'Set WshShell = CreateObject("WScript.Shell")\n'
        f'WshShell.Run """{PYTHONW_EXE}"" ""{WORK_DIR}\\{LAUNCHER}""", 0, False\n'
        'Set WshShell = Nothing\n'
    )
    vbs_path = startup / "NDXDashboard.vbs"
    try:
        vbs_path.write_text(vbs_content, encoding="utf-8")
        print(f"  [OK] Created startup launcher: {vbs_path}")
        return True
    except Exception as e:
        print(f"  [skip] Startup folder write failed: {e}")
        return False


def register() -> bool:
    print(f"[register] Auto-starting '{TASK_NAME}'...")
    print(f"  Python: {PYTHONW_EXE}")
    print(f"  Launcher: {WORK_DIR}\\{LAUNCHER} (auto-restarts serve.py on crash)")
    if _register_via_taskscheduler():
        return True
    print("  Falling back to Startup folder...")
    return _register_via_startup_folder()


def unregister() -> bool:
    ok = True
    # Try Task Scheduler first
    try:
        import win32com.client
        scheduler = win32com.client.Dispatch("Schedule.Service")
        scheduler.Connect()
        try:
            scheduler.GetFolder("\\").DeleteTask(TASK_NAME, 0)
            print(f"  [OK] Removed Task Scheduler entry '{TASK_NAME}'")
        except Exception:
            pass
    except Exception as e:
        print(f"  [skip] Task Scheduler cleanup: {e}")
        ok = True  # don't fail if not there
    # Cleanup Startup folder
    startup = Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs/Startup"
    vbs = startup / "NDXDashboard.vbs" if startup.exists() else None
    if vbs and vbs.exists():
        try:
            vbs.unlink()
            print(f"  [OK] Removed startup launcher: {vbs}")
        except Exception as e:
            print(f"  [skip] Cleanup VBS: {e}")
            ok = False
    return ok


def status():
    print(f"[status] {TASK_NAME}:")
    # Check Task Scheduler
    try:
        import win32com.client
        scheduler = win32com.client.Dispatch("Schedule.Service")
        scheduler.Connect()
        try:
            t = scheduler.GetFolder("\\").GetTask(TASK_NAME)
            print(f"  Task Scheduler: registered (state={t.State}, enabled={t.Enabled})")
        except Exception:
            print(f"  Task Scheduler: not registered")
    except Exception:
        print(f"  Task Scheduler: COM unavailable")
    # Check startup folder
    startup = Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs/Startup"
    vbs = startup / "NDXDashboard.vbs" if startup.exists() else None
    print(f"  Startup folder: {'exists' if vbs and vbs.exists() else 'not found'}")
    # Check if serve.py is currently running
    import subprocess
    try:
        out = subprocess.check_output(["tasklist", "/FI", "IMAGENAME eq python.exe", "/FO", "CSV"],
                                       text=True, stderr=subprocess.DEVNULL)
        pids = [l for l in out.splitlines()[1:] if l.strip()]
        print(f"  python.exe processes running: {len(pids)}")
    except Exception:
        pass


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "install"
    if cmd == "install":
        ok = register()
        sys.exit(0 if ok else 1)
    elif cmd == "remove":
        ok = unregister()
        sys.exit(0 if ok else 1)
    elif cmd == "status":
        status()
    else:
        print(f"Usage: python register_autostart.py [install|remove|status]")
        sys.exit(2)


if __name__ == "__main__":
    main()
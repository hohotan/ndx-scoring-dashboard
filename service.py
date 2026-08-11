"""
NDXDashboard Windows Service
============================
Wraps serve.py as a Windows service so the dashboard auto-starts on boot,
restarts on crash, and runs as a real background service (visible in
services.msc).

Install:
    python service.py install
    python service.py start

Other commands:
    python service.py stop
    python service.py remove        # uninstall
    python service.py restart
    python service.py update        # re-register if exe path changes

Note: requires pywin32 (pip install pywin32). Install / remove need
      Administrator privileges.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

try:
    import win32serviceutil
    import win32service
    import win32event
    import servicemanager
except ImportError:
    print("[ERROR] pywin32 not installed. Run: pip install pywin32", file=sys.stderr)
    sys.exit(1)


# ============================================================================
# Configuration
# ============================================================================

# Auto-detect Python and project paths so service.py works on any machine
PYTHON_EXE = sys.executable
WORK_DIR   = str(Path(__file__).resolve().parent)
SCRIPT     = "serve.py"

SVC_NAME        = "NDXDashboard"
SVC_DISPLAY     = "NDX Investment Scoring Dashboard"
SVC_DESCRIPTION = (
    "Local HTTP dashboard (port 8765) for the Nasdaq-100 investment scoring "
    "system. Auto-refreshes data daily and on-demand."
)


# ============================================================================
# Service class
# ============================================================================

class NDXDashboardService(win32serviceutil.ServiceFramework):
    _svc_name_ = SVC_NAME
    _svc_display_name_ = SVC_DISPLAY
    _svc_description_ = SVC_DESCRIPTION

    def __init__(self, args):
        super().__init__(args)
        self.hWaitStop = win32event.CreateEvent(None, 0, 0, None)
        self.hWaitResume = win32event.CreateEvent(None, 0, 0, None)
        self.proc: subprocess.Popen | None = None
        self._stop_requested = False
        self.restart_delay = 5  # seconds between restart attempts

    # --- service control handlers --------------------------------------

    def SvcStop(self):
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        self._stop_requested = True
        win32event.SetEvent(self.hWaitStop)
        self._terminate_child()

    def SvcPause(self):
        self.ReportServiceStatus(win32service.SERVICE_PAUSED)
        win32event.ResetEvent(self.hWaitResume)
        # Pause: just kill the child; SvcContinue can restart it
        self._terminate_child()

    def SvcContinue(self):
        self.ReportServiceStatus(win32service.SERVICE_CONTINUE_PENDING)
        win32event.SetEvent(self.hWaitResume)

    # --- helpers --------------------------------------------------------

    def _terminate_child(self):
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.terminate()
                try:
                    self.proc.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
                    self.proc.wait(timeout=3)
            except Exception as e:
                servicemanager.LogInfoMsg(f"terminate error: {e}")

    def _spawn_child(self):
        try:
            # CREATE_NO_WINDOW flag (0x08000000) keeps the console hidden
            flags = 0x08000000 if sys.platform == "win32" else 0
            self.proc = subprocess.Popen(
                [PYTHON_EXE, SCRIPT],
                cwd=WORK_DIR,
                creationflags=flags,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            servicemanager.LogInfoMsg(
                f"Started serve.py as PID {self.proc.pid}"
            )
        except Exception as e:
            servicemanager.LogErrorMsg(f"Failed to start serve.py: {e}")
            self.proc = None

    # --- main loop ------------------------------------------------------

    def SvcDoRun(self):
        servicemanager.LogMsg(
            servicemanager.EVENTLOG_INFORMATION_TYPE,
            servicemanager.PYS_SERVICE_STARTED,
            (self._svc_name_, "")
        )
        self.ReportServiceStatus(win32service.SERVICE_RUNNING)

        # Run serve.py in a subprocess; restart on crash
        while not self._stop_requested:
            self._spawn_child()
            if not self.proc:
                # Spawn failed; wait a bit and retry
                if win32event.WaitForSingleObject(self.hWaitStop, 30000) == win32event.WAIT_OBJECT_0:
                    break
                continue

            # Wait for either: child exits OR stop signal
            proc_handle = self.proc._handle if hasattr(self.proc, "_handle") else None
            # Simpler: poll the process and the stop event
            while True:
                rc = win32event.WaitForSingleObject(self.hWaitStop, 2000)
                if self._stop_requested:
                    return
                if self.proc.poll() is not None:
                    # Child died
                    code = self.proc.returncode
                    servicemanager.LogErrorMsg(
                        f"serve.py exited with code {code}; restarting in {self.restart_delay}s"
                    )
                    break
                if rc == win32event.WAIT_OBJECT_0:
                    # Stop requested
                    return
            if self._stop_requested:
                return
            time.sleep(self.restart_delay)

        servicemanager.LogInfoMsg("NDXDashboard service exiting")


# ============================================================================
# Entry point
# ============================================================================

if __name__ == "__main__":
    win32serviceutil.HandleCommandLine(NDXDashboardService)
"""
NDX Dashboard Backend - http server + auto-refresh
==================================================
Wraps fetch_data.py in a long-running HTTP service so the dashboard has a
"refresh" button and (optionally) auto-updates data on a schedule.

Endpoints:
    GET  /                  -> serve index.html
    GET  /echarts.min.js    -> serve the ECharts library
    GET  /refresh           -> run fetch_data.py synchronously, return JSON
    GET  /api/snapshot      -> return latest snapshot as JSON
    GET  /api/status        -> data freshness + server info

Run:
    python serve.py [PORT]   # default 8765

Note: Serve only what the dashboard needs; serves out of CWD.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

OUT_DIR = Path(__file__).resolve().parent
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8765

# Auto-refresh: if data is older than this, run fetch_data.py on the next request
STALE_AFTER_HOURS = 24

# Background scheduler: runs fetch_data.py once per day at ~09:00 local time
SCHEDULE_HOUR = 9

_lock = threading.Lock()
_last_refresh_at = None  # type: float | None
_last_refresh_ok = None  # type: bool | None
_last_refresh_msg = None  # type: str | None


# ============================================================================
# Helpers
# ============================================================================

def run_fetch_data() -> tuple[bool, str]:
    """Run fetch_data.py as a subprocess and capture the result."""
    global _last_refresh_at, _last_refresh_ok, _last_refresh_msg
    with _lock:
        _last_refresh_at = time.time()
        print(f"[refresh] starting fetch_data.py at {datetime.now().isoformat()}")
        try:
            r = subprocess.run(
                [sys.executable, str(OUT_DIR / "fetch_data.py")],
                capture_output=True, text=True, timeout=120,
                cwd=str(OUT_DIR),
            )
            ok = r.returncode == 0
            msg = (r.stdout or "").strip().splitlines()[-1] if r.stdout else ""
            if not ok:
                msg = (r.stderr or "").strip().splitlines()[-1] if r.stderr else "unknown error"
            _last_refresh_ok = ok
            _last_refresh_msg = msg
            print(f"[refresh] {'OK' if ok else 'FAIL'} - {msg}")
            return ok, msg
        except subprocess.TimeoutExpired:
            _last_refresh_ok = False
            _last_refresh_msg = "timeout after 120s"
            return False, _last_refresh_msg
        except Exception as e:
            _last_refresh_ok = False
            _last_refresh_msg = str(e)
            return False, _last_refresh_msg


def data_age_hours() -> float | None:
    """How old is the snapshot, based on generated_at in ndx_snapshot.json."""
    snap = OUT_DIR / "ndx_snapshot.json"
    if not snap.exists():
        return None
    try:
        d = json.loads(snap.read_text(encoding="utf-8"))
        ts = datetime.fromisoformat(d["generated_at"])
        return (datetime.now() - ts).total_seconds() / 3600
    except Exception:
        return None


def data_generated_at() -> str | None:
    """Snapshot's generated_at as ISO string (local time, naive)."""
    snap = OUT_DIR / "ndx_snapshot.json"
    if not snap.exists():
        return None
    try:
        d = json.loads(snap.read_text(encoding="utf-8"))
        return d.get("generated_at")
    except Exception:
        return None


def maybe_auto_refresh() -> None:
    """If snapshot is older than STALE_AFTER_HOURS, refresh in background."""
    age = data_age_hours()
    if age is None or age > STALE_AFTER_HOURS:
        def _job():
            ok, _ = run_fetch_data()
            print(f"[auto-refresh] {'done' if ok else 'failed'}")
        threading.Thread(target=_job, daemon=True).start()


def scheduler_loop():
    """Background thread: at SCHEDULE_HOUR local time, run fetch_data."""
    while True:
        now = datetime.now()
        target = now.replace(hour=SCHEDULE_HOUR, minute=0, second=0, microsecond=0)
        if target <= now:
            target = target + timedelta(days=1)
        wait = (target - now).total_seconds()
        time.sleep(min(wait, 3600))  # wake every hour to re-evaluate
        if datetime.now().hour == SCHEDULE_HOUR:
            print(f"[scheduler] scheduled refresh at {datetime.now().isoformat()}")
            run_fetch_data()


# ============================================================================
# HTTP handler
# ============================================================================

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        sys.stderr.write("[%s] %s\n" % (self.address_string(), fmt % args))

    def _send_json(self, obj: dict, status: int = 200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path: Path):
        if not path.exists():
            self.send_error(404, "not found")
            return
        try:
            data = path.read_bytes()
        except OSError as e:
            self.send_error(500, str(e))
            return
        ctype = "text/html; charset=utf-8" if path.suffix == ".html" else \
                "application/javascript; charset=utf-8" if path.suffix == ".js" else \
                "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        url = urlparse(self.path)
        path = url.path

        if path == "/refresh":
            ok, msg = run_fetch_data()
            age = data_age_hours()
            self._send_json({
                "ok": ok,
                "message": msg,
                "data_age_hours": round(age, 2) if age is not None else None,
                "data_generated_at": data_generated_at(),
                "refreshed_at": datetime.now().isoformat(),
            })
            return

        if path == "/api/snapshot":
            snap = OUT_DIR / "ndx_snapshot.json"
            if snap.exists():
                self._send_file(snap)
            else:
                self._send_json({"error": "no snapshot yet"}, 404)
            return

        if path == "/api/status":
            age = data_age_hours()
            self._send_json({
                "ok": True,
                "data_age_hours": round(age, 2) if age is not None else None,
                "data_is_stale": (age is None or age > STALE_AFTER_HOURS),
                "data_generated_at": data_generated_at(),
                "last_refresh_at": _last_refresh_at,
                "last_refresh_ok": _last_refresh_ok,
                "last_refresh_msg": _last_refresh_msg,
                "next_scheduled_refresh_hour": SCHEDULE_HOUR,
                "stale_after_hours": STALE_AFTER_HOURS,
                "server_time": datetime.now().isoformat(),
            })
            return

        # Static files
        rel = path.lstrip("/") or "index.html"
        target = (OUT_DIR / rel).resolve()
        # Path traversal guard
        if not str(target).startswith(str(OUT_DIR)):
            self.send_error(403, "forbidden")
            return
        if target.is_dir():
            target = target / "index.html"
        # Auto-refresh data if stale (best-effort, non-blocking)
        maybe_auto_refresh()
        self._send_file(target)


def main():
    print(f"[serve] starting on http://localhost:{PORT}")
    print(f"[serve] serving {OUT_DIR}")
    print(f"[serve] auto-refresh threshold: {STALE_AFTER_HOURS}h, scheduled at {SCHEDULE_HOUR:02d}:00 daily")

    # Background scheduler
    threading.Thread(target=scheduler_loop, daemon=True).start()

    # Initial freshness check
    age = data_age_hours()
    if age is None:
        print("[serve] no data found, will run fetch_data.py on first request")
    else:
        print(f"[serve] data age: {age:.2f}h ({'stale' if age > STALE_AFTER_HOURS else 'fresh'})")

    try:
        httpd = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
        print(f"[serve] ready")
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[serve] shutting down")
    except OSError as e:
        if e.errno == 10048:  # WSAEADDRINUSE on Windows
            print(f"[ERROR] port {PORT} already in use. Stop the existing process or pass a different port.")
            sys.exit(1)
        raise


if __name__ == "__main__":
    main()
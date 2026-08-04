"""Daemon lifecycle: run the Lemory server as a managed background process.

`lemory serve` is the foreground server. This module is the layer around it
that a shipped product needs: start it detached, know whether it is alive,
stop it cleanly, read its logs · without the user learning nohup/pkill.

    lemory daemon start [--port 8377]
    lemory daemon status
    lemory daemon logs [-n 50]
    lemory daemon stop

State lives next to the index (data_dir): `daemon.pid`, `daemon.log`,
`daemon.json` (port + started_at). The pidfile is authoritative only
together with a liveness check · a stale pidfile after a crash or reboot is
detected (the pid is gone, or belongs to a different process) and cleaned
up rather than trusted.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path


def _paths(data_dir: Path) -> tuple[Path, Path, Path]:
    return data_dir / "daemon.pid", data_dir / "daemon.log", data_dir / "daemon.json"


def _pid_alive(pid: int) -> bool:
    """Is this pid a live process we may signal? (kill 0 probes without
    sending). EPERM would mean "alive but not ours" · treat as not-ours-dead
    since we only ever manage daemons we spawned as the same user."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return False


@dataclass
class DaemonStatus:
    running: bool
    pid: int | None = None
    port: int | None = None
    started_at: float | None = None
    stale_pidfile: bool = False   # a pidfile existed but the process is gone
    healthy: bool | None = None   # /status probe result (None = not probed)


def read_status(data_dir: Path, probe: bool = True) -> DaemonStatus:
    pidfile, _, metafile = _paths(data_dir)
    if not pidfile.is_file():
        return DaemonStatus(running=False)
    try:
        pid = int(pidfile.read_text().strip())
    except ValueError:
        return DaemonStatus(running=False, stale_pidfile=True)
    if not _pid_alive(pid):
        return DaemonStatus(running=False, pid=pid, stale_pidfile=True)
    meta: dict = {}
    if metafile.is_file():
        try:
            meta = json.loads(metafile.read_text())
        except json.JSONDecodeError:
            pass
    st = DaemonStatus(running=True, pid=pid, port=meta.get("port"),
                      started_at=meta.get("started_at"))
    if probe and st.port:
        st.healthy = _probe(st.port)
    return st


def _probe_pid(port: int, timeout: float = 2.0) -> "int | None":
    """The pid the /health responder reports, or None when unreachable.
    Lets start() distinguish 'our server came up' from 'a stranger already
    owns this port' · found live: a stale daemon on the port made start()
    report success while the new process had died on bind."""
    import json as _json
    import urllib.request

    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(f"http://127.0.0.1:{port}/health", timeout=timeout) as r:
            return int(_json.loads(r.read().decode()).get("pid", -1))
    except Exception:
        return None


def _probe(port: int, timeout: float = 2.0) -> bool:
    import urllib.request

    # ProxyHandler({}) bypasses HTTP(S)_PROXY env vars: this is a loopback
    # probe, and corporate/proxy environments would otherwise route
    # 127.0.0.1 through a proxy that can't reach it · found live, not in
    # theory: the daemon looked dead while uvicorn was up.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(f"http://127.0.0.1:{port}/health", timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


def clean_stale(data_dir: Path) -> None:
    pidfile, _, metafile = _paths(data_dir)
    pidfile.unlink(missing_ok=True)
    metafile.unlink(missing_ok=True)


def start(data_dir: Path, vault: Path | None, port: int = 8377,
          wait_seconds: float = 30.0) -> DaemonStatus:
    """Spawn `lemory serve` detached, logging to daemon.log, and wait until
    /health answers (or the process dies · in which case the log tail is in
    the raised error, because "it didn't start, go find the log yourself" is
    not a product)."""
    st = read_status(data_dir, probe=False)
    if st.running:
        raise RuntimeError(f"already running (pid {st.pid})")
    if st.stale_pidfile:
        clean_stale(data_dir)

    data_dir.mkdir(parents=True, exist_ok=True)
    pidfile, logfile, metafile = _paths(data_dir)

    cmd = [sys.executable, "-m", "lemory", "serve", "--port", str(port)]
    if vault:
        cmd += ["--vault", str(vault)]
    with open(logfile, "ab") as lf:
        lf.write(f"\n--- daemon start {time.strftime('%F %T')} ---\n".encode())
        proc = subprocess.Popen(
            cmd, stdout=lf, stderr=lf, stdin=subprocess.DEVNULL,
            start_new_session=True,  # survives the CLI's terminal closing
        )
    pidfile.write_text(str(proc.pid))
    metafile.write_text(json.dumps(
        {"port": port, "started_at": time.time(), "vault": str(vault or "")}))

    deadline = time.time() + wait_seconds
    while time.time() < deadline:
        if proc.poll() is not None:  # died during startup
            tail = _tail(logfile, 12)
            clean_stale(data_dir)
            raise RuntimeError(
                f"server exited during startup (code {proc.returncode}).\n{tail}")
        got = _probe_pid(port)
        if got is not None:
            if got != proc.pid:
                # someone else answers on this port · our process is (or will
                # be) dead on bind. Fail loudly instead of adopting a stranger.
                try:
                    proc.terminate()
                except OSError:
                    pass
                clean_stale(data_dir)
                raise RuntimeError(
                    f"port {port} is already in use by another process "
                    f"(pid {got}). Stop it or pick another port "
                    f"(lemory daemon start --port <n>).")
            return DaemonStatus(running=True, pid=proc.pid, port=port,
                                started_at=time.time(), healthy=True)
        time.sleep(0.5)
    # alive but not answering yet (huge first index): report, don't kill
    return DaemonStatus(running=True, pid=proc.pid, port=port,
                        started_at=time.time(), healthy=False)


def stop(data_dir: Path, wait_seconds: float = 15.0) -> bool:
    """SIGTERM, wait for exit, escalate to SIGKILL only past the deadline.
    Returns True if a process was stopped."""
    st = read_status(data_dir, probe=False)
    if not st.running:
        if st.stale_pidfile:
            clean_stale(data_dir)
        return False
    assert st.pid is not None
    os.kill(st.pid, signal.SIGTERM)
    deadline = time.time() + wait_seconds
    while time.time() < deadline:
        if not _pid_alive(st.pid):
            clean_stale(data_dir)
            return True
        time.sleep(0.3)
    os.kill(st.pid, signal.SIGKILL)  # last resort · WAL keeps the DB safe
    clean_stale(data_dir)
    return True


def _tail(logfile: Path, n: int) -> str:
    try:
        lines = logfile.read_text(encoding="utf-8", errors="replace").splitlines()
        return "\n".join(lines[-n:])
    except OSError:
        return "(no log)"


def logs(data_dir: Path, n: int = 50) -> str:
    _, logfile, _ = _paths(data_dir)
    return _tail(logfile, n)

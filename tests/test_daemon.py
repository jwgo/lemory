"""Daemon lifecycle: pidfile hygiene, status, stop semantics (offline)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time

import pytest

from lemory import daemon as dmn


def test_no_pidfile_means_not_running(tmp_path):
    st = dmn.read_status(tmp_path, probe=False)
    assert not st.running and not st.stale_pidfile


def test_stale_pidfile_is_detected_not_trusted(tmp_path):
    """A pidfile surviving a crash/reboot must read as stale, never as
    running · trusting it would make `daemon start` refuse forever."""
    (tmp_path / "daemon.pid").write_text("999999999")
    st = dmn.read_status(tmp_path, probe=False)
    assert not st.running and st.stale_pidfile

    (tmp_path / "daemon.pid").write_text("not-a-pid")
    st = dmn.read_status(tmp_path, probe=False)
    assert not st.running and st.stale_pidfile

    dmn.clean_stale(tmp_path)
    assert not (tmp_path / "daemon.pid").exists()


def test_live_pid_reads_as_running(tmp_path):
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        (tmp_path / "daemon.pid").write_text(str(proc.pid))
        (tmp_path / "daemon.json").write_text(json.dumps({"port": 1}))
        st = dmn.read_status(tmp_path, probe=False)
        assert st.running and st.pid == proc.pid and st.port == 1
    finally:
        proc.kill()
        proc.wait()


def test_stop_terminates_and_cleans(tmp_path):
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    (tmp_path / "daemon.pid").write_text(str(proc.pid))
    assert dmn.stop(tmp_path) is True
    proc.wait(timeout=5)
    assert not (tmp_path / "daemon.pid").exists()
    assert dmn.stop(tmp_path) is False          # second stop: nothing to do


def test_start_surfaces_startup_failure_with_log_tail(tmp_path, monkeypatch):
    """A server that dies during startup must raise with the log tail in the
    message · 'go find the log yourself' is not a product."""
    real_popen = subprocess.Popen

    def fake_popen(cmd, **kw):
        return real_popen([sys.executable, "-c",
                           "import sys; print('boom: vault missing'); sys.exit(3)"],
                          **kw)

    monkeypatch.setattr(dmn.subprocess, "Popen", fake_popen)
    with pytest.raises(RuntimeError) as e:
        dmn.start(tmp_path, vault=None, port=59999, wait_seconds=10)
    assert "boom: vault missing" in str(e.value)
    assert not (tmp_path / "daemon.pid").exists()   # no corpse left behind

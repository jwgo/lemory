"""Layer boundaries, enforced (docs/ARCHITECTURE.md).

Rules become real only when a violation fails CI. These tests grep the
source; they are deliberately dumb so that a clever import can't sneak by
a clever checker.
"""
from __future__ import annotations

import re
from pathlib import Path

SRC = Path(__file__).parent.parent / "src" / "lemory"

# interfaces may depend on the engine facade, config, assistant service,
# daemon module, providers (transport-level model wiring for STT/TTS/Gemma
# streams) and storage types · never on ingestion/retrieval internals.
_FORBIDDEN_IN_INTERFACES = re.compile(
    r"from\s+(?:lemory|\.\.)\.?(ingestion|retrieval)\b|import\s+lemory\.(ingestion|retrieval)\b"
)


def _py_files(folder: Path):
    return sorted(p for p in folder.rglob("*.py") if "__pycache__" not in p.parts)


def test_interfaces_only_call_the_engine_facade():
    offenders = []
    for f in _py_files(SRC / "interfaces"):
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if _FORBIDDEN_IN_INTERFACES.search(line):
                offenders.append(f"{f.name}:{i}: {line.strip()}")
    assert not offenders, (
        "interface layer reached into domain modules · add an Engine facade "
        "verb instead:\n" + "\n".join(offenders))


def test_engine_side_never_imports_interfaces():
    offenders = []
    for folder in ("ingestion", "retrieval", "storage", "providers"):
        for f in _py_files(SRC / folder):
            for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
                if re.search(r"\binterfaces\b", line) and "import" in line:
                    offenders.append(f"{folder}/{f.name}:{i}: {line.strip()}")
    for name in ("engine.py", "assistant.py", "config.py", "daemon.py"):
        f = SRC / name
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"\binterfaces\b", line) and "import" in line:
                offenders.append(f"{name}:{i}: {line.strip()}")
    assert not offenders, (
        "engine layer imported an interface (dependency must point inward):\n"
        + "\n".join(offenders))


def test_daemon_module_stays_process_level():
    """daemon.py manages a process; it must not import the engine or domain
    modules · it talks to the server over HTTP like any other client."""
    body = (SRC / "daemon.py").read_text(encoding="utf-8")
    assert not re.search(r"from\s+\.(engine|ingestion|retrieval|storage)\b", body)
    assert "import lemory.engine" not in body


def test_private_helpers_stay_private():
    """No interface file may import an underscore-private name from another
    module · the facade exists so this never becomes necessary again
    (the old offender: `from ..ingestion.memory import _safe_target`)."""
    offenders = []
    for f in _py_files(SRC / "interfaces"):
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"from\s+[.\w]+\s+import\s+.*\b_[a-z]\w*", line) \
                    and "import _" in line.replace(", ", " import _"):
                if re.search(r"import\s+_", line):
                    offenders.append(f"{f.name}:{i}: {line.strip()}")
    assert not offenders, "\n".join(offenders)

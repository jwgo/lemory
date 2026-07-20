"""On-device speech-to-text via faster-whisper (CTranslate2, no torch, no
cloud), so the assistant's voice input is transcribed locally · the browser's
mic audio never leaves the machine, unlike the browser Web Speech API. The
model auto-downloads once and is cached; loaded lazily."""
from __future__ import annotations

import os
import tempfile
import threading

DEFAULT_SIZE = "small"  # ~470MB int8, solid Korean; "base" is lighter/faster

_MODEL = None
_LOCK = threading.Lock()


def available() -> tuple[bool, str]:
    try:
        import faster_whisper  # noqa: F401
        return True, ""
    except ImportError:
        return False, 'STT(faster-whisper)가 없습니다: pip install "lemory[assistant]"'


def _model(size: str):
    global _MODEL
    with _LOCK:
        if _MODEL is None:
            from faster_whisper import WhisperModel
            _MODEL = WhisperModel(size, device="cpu", compute_type="int8")
        return _MODEL


def transcribe(audio: bytes, lang: str = "ko", size: str = DEFAULT_SIZE) -> str:
    """Transcribe an audio clip (any ffmpeg-decodable container: webm/opus, wav,
    mp4…) to text. `lang=None` lets Whisper auto-detect."""
    fd, path = tempfile.mkstemp(suffix=".audio")
    os.write(fd, audio)
    os.close(fd)
    try:
        segments, _info = _model(size).transcribe(path, language=lang, beam_size=1)
        return "".join(s.text for s in segments).strip()
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass

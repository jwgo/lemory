"""On-device neural TTS via Supertonic (ONNX, ~99M, 31 languages incl. Korean),
so the console assistant speaks its answers locally · no cloud, no torch. The
model auto-downloads on first use; the Engine + voice styles are cached.

    pip install "lemory[assistant]"
"""
from __future__ import annotations

import io
import threading

VOICES = ("f1", "f2", "f3", "f4", "f5", "m1", "m2", "m3", "m4", "m5")
SAMPLE_RATE = 44100

_TTS = None
_STYLES: dict = {}
_LOCK = threading.Lock()


def available() -> tuple[bool, str]:
    try:
        import supertonic  # noqa: F401
        return True, ""
    except ImportError:
        return False, '음성 TTS(Supertonic)가 없습니다: pip install "lemory[assistant]"'


def _tts():
    global _TTS
    if _TTS is None:
        import supertonic
        _TTS = supertonic.TTS()
    return _TTS


def _style(voice: str):
    s = _STYLES.get(voice)
    if s is None:
        s = _tts().get_voice_style(voice if voice in VOICES else "f1")
        _STYLES[voice] = s
    return s


def _has_hangul(text: str) -> bool:
    return any("가" <= c <= "힣" for c in text)


def synth_wav(text: str, voice: str = "f1", lang: str | None = None,
              pitch: float = 0.0) -> bytes:
    """Synthesize `text` to a WAV byte string. Auto-picks Korean for Hangul.
    `pitch` shifts by that many semitones (tempo preserved) for a cuter/lower
    tone; +3 ≈ a bright, cute register."""
    import numpy as np
    import soundfile as sf

    lang = lang or ("ko" if _has_hangul(text) else None)
    with _LOCK:  # one ONNX session; serialize synthesis for a local single user
        tts = _tts()
        audio, _sr = tts.synthesize(text, voice_style=_style(voice), lang=lang)
    wav = np.asarray(audio, dtype=np.float32).flatten()
    if pitch:
        try:
            import librosa
            wav = librosa.effects.pitch_shift(y=wav, sr=SAMPLE_RATE, n_steps=float(pitch))
        except Exception:
            pass  # librosa missing → ship the un-shifted voice rather than fail
    buf = io.BytesIO()
    sf.write(buf, wav, SAMPLE_RATE, format="WAV")
    return buf.getvalue()

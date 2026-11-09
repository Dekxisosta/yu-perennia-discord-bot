"""Local Kokoro-82M text-to-speech (ONNX Runtime, CPU only).

The model is loaded lazily and kept in memory. Model files live in models/kokoro/ (override the
folder with KOKORO_MODEL_DIR) and are downloaded once. Run this file directly to fetch them:

    python src/utils/kokoro_engine.py

A voice spec looks like  af_heart  |  af_heart@1.1 (speed)  |  af_heart+af_bella@1.05 (blend)
|  af_heart@1.05^1.2 (pitch: 1.2 = 20% higher, same tempo)
|  jf_alpha:0.5+af_heart:0.25+af_bella:0.25 (weighted blend; weights default to equal).
"""
import os
import shutil
import sys
import tempfile
import threading
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODEL_DIR = Path(os.getenv("KOKORO_MODEL_DIR") or ROOT / "models" / "kokoro")
# The int8 model is the smallest (~88 MB). Use kokoro-v1.0.fp16.onnx for better quality, more RAM.
MODEL_FILE = os.getenv("KOKORO_MODEL_FILE") or "kokoro-v1.0.int8.onnx"
VOICES_FILE = "voices-v1.0.bin"
BASE_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/"

_lock = threading.Lock()  # one synthesis at a time keeps CPU and memory use predictable
_kokoro = None


def _say(message: str, ok: bool = True) -> None:
    try:
        from utils.console_logger import log

        log(message, module_name="KOKORO", success=ok)
    except Exception:
        print(("[+] " if ok else "[!] ") + "KOKORO: " + message)


def _parse(spec: str) -> tuple[list[tuple[str, float]], float, float]:
    speed = pitch = 1.0
    if "^" in spec:
        spec, raw = spec.rsplit("^", 1)
        try:
            pitch = min(max(float(raw), 0.7), 1.6)
        except ValueError:
            pass
    if "@" in spec:
        spec, raw = spec.rsplit("@", 1)
        try:
            speed = min(max(float(raw), 0.5), 2.0)
        except ValueError:
            pass
    pairs = []
    for token in spec.split("+"):
        name, _, raw = token.strip().partition(":")
        if not name.strip():
            continue
        try:
            weight = float(raw) if raw else 1.0
        except ValueError:
            weight = 1.0
        pairs.append((name.strip(), weight if weight > 0 else 1.0))
    return pairs or [("af_heart", 1.0)], speed, pitch


def parse_voice_full(spec: str) -> tuple[list[str], float, float]:
    """'af_heart+af_bella@1.1^1.2' -> (['af_heart', 'af_bella'], speed 1.1, pitch 1.2)"""
    pairs, speed, pitch = _parse(spec)
    return [name for name, _ in pairs], speed, pitch


def parse_voice(spec: str) -> tuple[list[str], float]:
    names, speed, _ = parse_voice_full(spec)
    return names, speed


def ensure_models() -> bool:
    """Download the model and voices once. Returns False if they are still missing."""
    import urllib.request

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    for name in (MODEL_FILE, VOICES_FILE):
        dest = MODEL_DIR / name
        if dest.exists() and dest.stat().st_size > 1_000_000:
            continue
        _say(f"Downloading {name} (one time)...")
        part = dest.with_name(dest.name + ".part")
        try:
            with urllib.request.urlopen(BASE_URL + name, timeout=60) as resp, open(part, "wb") as out:
                shutil.copyfileobj(resp, out)
            part.replace(dest)
        except Exception as e:
            _say(f"Could not download {name}: {e}", False)
            try:
                part.unlink()
            except OSError:
                pass
            return False
    return True


def _load():
    global _kokoro
    if _kokoro is None:
        from kokoro_onnx import Kokoro

        if not ensure_models():
            raise RuntimeError("Kokoro model files are missing")
        _kokoro = Kokoro(str(MODEL_DIR / MODEL_FILE), str(MODEL_DIR / VOICES_FILE))
        _say(f"Loaded {MODEL_FILE}")
    return _kokoro


def preload() -> None:
    """Load the model now (blocking) so the first spoken message isn't slow."""
    try:
        with _lock:
            _load()
    except Exception as e:
        _say(f"Preload failed, edge-tts will be used instead: {e}", False)


def _style(kokoro, pairs: list[tuple[str, float]]):
    if len(pairs) == 1:
        return pairs[0][0]
    import numpy as np

    styles = [kokoro.get_voice_style(name) for name, _ in pairs]
    return np.average(styles, axis=0, weights=[w for _, w in pairs])


def synthesize_to_file(text: str, spec: str) -> str:
    """Render `text` to a 16-bit mono WAV in the temp folder and return its path (blocking)."""
    import numpy as np

    pairs, speed, pitch = _parse(spec)
    lang = "en-gb" if pairs[0][0].startswith("b") else "en-us"
    # Kokoro has no pitch control. Speak slower by the pitch factor, then label the audio with a
    # sample rate that much higher: pitch goes up by `pitch`, and the tempo ends up at `speed`.
    synth_speed = min(max(speed / pitch, 0.5), 2.0)
    with _lock:
        kokoro = _load()
        samples, rate = kokoro.create(text, voice=_style(kokoro, pairs), speed=synth_speed, lang=lang)
    rate = int(rate * pitch)
    pcm = (np.clip(np.asarray(samples, dtype="float32"), -1.0, 1.0) * 32767).astype("<i2")
    if pcm.size == 0:
        raise RuntimeError("Kokoro returned no audio")

    fd, path = tempfile.mkstemp(suffix=".wav", prefix="yu_tts_")
    os.close(fd)
    try:
        with wave.open(path, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(rate)
            w.writeframes(pcm.tobytes())
    except BaseException:
        try:
            os.remove(path)
        except OSError:
            pass
        raise
    return path


if __name__ == "__main__":
    ensure_models()  # never fail the build; the bot retries at runtime and falls back to edge-tts

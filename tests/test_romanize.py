import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from services.commands import tts_service as ts  # noqa: E402
from utils import romanize as rz  # noqa: E402


@pytest.fixture(autouse=True)
def fake_libs(monkeypatch):
    """Stand-ins for pykakasi and anyascii so the tests don't need them installed."""
    class Kakasi:
        def convert(self, text):
            table = {"田中": "tanaka", "さん": "san", "ゆう": "yuu"}
            out, i = [], 0
            while i < len(text):
                for k, v in table.items():
                    if text.startswith(k, i):
                        out.append({"hepburn": v})
                        i += len(k)
                        break
                else:
                    out.append({"hepburn": "?"})
                    i += 1
            return out

    monkeypatch.setitem(sys.modules, "pykakasi", types.SimpleNamespace(kakasi=Kakasi))
    monkeypatch.setitem(sys.modules, "anyascii", types.SimpleNamespace(anyascii=lambda t: {"Привет": "Privet"}.get(t, "x")))
    monkeypatch.setattr(rz, "_kakasi", None)


def test_latin_text_is_untouched():
    assert rz.romanize("hello café") == "hello café"
    assert not rz.has_non_latin("hello café ñ")


def test_japanese_uses_kakasi_and_other_scripts_use_anyascii():
    assert rz.romanize("田中さん") == "tanaka san"
    assert rz.romanize("Привет") == "Privet"
    assert rz.romanize("hi 田中") == "hi tanaka"


def test_cjk_punctuation_becomes_ascii():
    assert rz.romanize("ゆう。") == "yuu."


def test_missing_libraries_drop_the_foreign_text(monkeypatch):
    monkeypatch.setitem(sys.modules, "pykakasi", None)
    monkeypatch.setitem(sys.modules, "anyascii", None)
    assert rz.romanize("hello 田中") == "hello"


class User:
    def __init__(self, display, name="fallback"):
        self.display_name, self.name = display, name


def test_speaker_name_romanizes_japanese_names():
    assert ts.speaker_name(User("田中さん")) == "Tanaka San"
    assert ts.speaker_name(User("✨Dekxi✨ | Dev")) == "Dekxi Dev"  # Latin names are unchanged


def test_speaker_name_pipeline():
    # 1. plain-letter display name wins over the username
    assert ts.speaker_name(User("Dekxi", name="rroquxii")) == "Dekxi"
    # fancy fonts fold to plain letters
    assert ts.speaker_name(User("𝓓𝓮𝓴𝔁𝓲", name="rroquxii")) == "Dekxi"
    assert ts.speaker_name(User("Ｄｅｋｘｉ", name="rroquxii")) == "Dekxi"
    # 2. Japanese display names are romanized, not replaced by the username
    assert ts.speaker_name(User("田中さん", name="tanaka123")) == "Tanaka San"
    # 3. other scripts / emoji-only fall back to the username
    assert ts.speaker_name(User("🔥🔥", name="rroquxii")) == "rroquxii"
    assert ts.speaker_name(User("مرحبا", name="sleepy_cat")) == "sleepy cat"
    # 4. nothing readable at all: romanize what we can, else "Someone"
    assert ts.speaker_name(User("Привет", name="🔥")) == "Privet"
    assert ts.speaker_name(User("🔥", name="🔥")) == "Someone"


@pytest.mark.parametrize("text, expected", [
    ("デクシ", "dekushi"), ("でくし", "dekushi"), ("ガッコウ", "gakkou"), ("ラーメン", "raamen"),
    ("キョウ", "kyou"), ("まっちゃ", "matcha"), ("ミユアッチ", "miyuatchi"), ("ファイト", "faito"),
])
def test_kana_names_work_with_no_libraries_installed(monkeypatch, text, expected):
    monkeypatch.setitem(sys.modules, "pykakasi", None)
    monkeypatch.setitem(sys.modules, "anyascii", None)
    monkeypatch.setattr(rz, "_kakasi", None)
    assert rz.romanize(text) == expected


def test_katakana_display_name_beats_username_even_without_libraries(monkeypatch):
    monkeypatch.setitem(sys.modules, "pykakasi", None)
    monkeypatch.setitem(sys.modules, "anyascii", None)
    monkeypatch.setattr(rz, "_kakasi", None)
    assert ts.speaker_name(User("デクシ", name="miyuacchiii")) == "Dekushi"

import asyncio
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from utils import kokoro_engine as ke  # noqa: E402


def test_parse_plain_voice():
    assert ke.parse_voice("af_heart") == (["af_heart"], 1.0)


def test_parse_speed_and_blend():
    assert ke.parse_voice("af_heart+af_bella@1.08") == (["af_heart", "af_bella"], 1.08)


def test_parse_pitch():
    assert ke.parse_voice_full("af_heart+af_bella@1.08^1.2") == (["af_heart", "af_bella"], 1.08, 1.2)
    assert ke.parse_voice_full("af_heart^1.3") == (["af_heart"], 1.0, 1.3)
    assert ke.parse_voice_full("af_heart^9")[2] == 1.6
    assert ke.parse_voice_full("af_heart^high")[2] == 1.0


def test_parse_weighted_blend():
    spec = "jf_alpha:0.5+af_heart:0.25+af_bella:0.25@1.05^1.15"
    assert ke._parse(spec) == ([("jf_alpha", 0.5), ("af_heart", 0.25), ("af_bella", 0.25)], 1.05, 1.15)
    assert ke.parse_voice_full(spec)[0] == ["jf_alpha", "af_heart", "af_bella"]
    assert ke._parse("a+b:oops") == ([("a", 1.0), ("b", 1.0)], 1.0, 1.0)


def test_parse_clamps_speed_and_ignores_garbage():
    assert ke.parse_voice("af_heart@9")[1] == 2.0
    assert ke.parse_voice("af_heart@fast") == (["af_heart"], 1.0)


@pytest.mark.asyncio
async def test_kokoro_failure_falls_back_to_edge(monkeypatch):
    from services.commands import tts_service as ts

    def boom(text, spec):
        raise RuntimeError("no model")

    used = []

    async def fake_edge(text, voice_id, timeout):
        used.append(voice_id)
        return "x.mp3"

    monkeypatch.setattr(ke, "synthesize_to_file", boom)
    monkeypatch.setattr(ts, "_synthesize_edge", fake_edge)
    assert await ts.synthesize("hi", "kokoro:af_heart", 5) == "x.mp3"
    assert used == [ts.FALLBACK_VOICE_ID]


@pytest.mark.asyncio
async def test_edge_voice_skips_kokoro(monkeypatch):
    from services.commands import tts_service as ts

    def boom(text, spec):
        raise AssertionError("kokoro must not be used")

    async def fake_edge(text, voice_id, timeout):
        return voice_id

    monkeypatch.setattr(ke, "synthesize_to_file", boom)
    monkeypatch.setattr(ts, "_synthesize_edge", fake_edge)
    assert await ts.synthesize("hi", "en-US-GuyNeural", 5) == "en-US-GuyNeural"

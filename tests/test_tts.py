import asyncio
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from services.commands import tts_service as ts  # noqa: E402

PRON = {"gg": "good game", "ggs": "good games", "lol": "L O L", "btw": "by the way"}


def test_pronunciations_whole_word_and_case_insensitive():
    assert ts.apply_pronunciations("GG that was fun", PRON) == "good game that was fun"
    assert ts.apply_pronunciations("lol btw", PRON) == "L O L by the way"


def test_pronunciations_do_not_touch_inside_words():
    assert ts.apply_pronunciations("eggs and a logger", PRON) == "eggs and a logger"


def test_longest_key_wins():
    assert ts.apply_pronunciations("ggs", PRON) == "good games"


def test_clean_strips_links_code_and_emoji():
    text = "check https://example.com `x = 1` <:pog:123456> ```\ncode\n``` hi"
    assert ts.clean_for_speech(text) == "check link x = 1 hi"


def test_clean_only_symbols_is_silent():
    assert ts.clean_for_speech("!!! ???") == ""
    assert ts.clean_for_speech("<:pog:123456>") == ""


def test_clean_collapses_repeated_letters():
    assert ts.clean_for_speech("nooooooooo") == "nooo"


def test_spoilers_are_not_read():
    assert ts.clean_for_speech("||secret ending|| wow") == "spoiler wow"


def test_truncate_at_word_boundary():
    out = ts.clean_for_speech("word " * 100, max_chars=22)
    assert len(out) <= 23 and out.endswith("…")
    assert "wor…" not in out


def test_voice_lookup_and_fallbacks():
    cfg = {"settings": {"default-voice": "b"}, "voices": {"a": {"id": "A"}, "b": {"id": "B"}}}
    assert ts.voice_id_for(cfg, "a") == "A"
    assert ts.voice_id_for(cfg, None) == "B"
    assert ts.voice_id_for(cfg, "missing") == "B"
    assert ts.voice_id_for({}, None) == ts.FALLBACK_VOICE_ID


def test_should_announce():
    s = ts.Session(guild_id=1, text_channel_id=2)
    s.last_speaker, s.last_spoken_at = 10, 100.0
    assert not ts.should_announce(s, 10, 120.0, 45)   # same speaker, soon
    assert ts.should_announce(s, 11, 120.0, 45)       # different speaker
    assert ts.should_announce(s, 10, 200.0, 45)       # same speaker, long gap


def test_queue_drops_when_full():
    mgr = ts.TTSManager(bot=None, get_cfg=lambda: {})
    s = ts.Session(guild_id=1, text_channel_id=2, queue=asyncio.Queue(maxsize=1))
    assert mgr.enqueue(s, ts.QueueItem("a", "v"))
    assert not mgr.enqueue(s, ts.QueueItem("b", "v"))


class _User:
    def __init__(self, display_name, name="x"):
        self.display_name, self.name = display_name, name


def test_speaker_name_strips_symbols():
    assert ts.speaker_name(_User("✨Dekxi✨ | Dev")) == "Dekxi Dev"
    assert ts.speaker_name(_User("🔥🔥", name="fallback")) == "fallback"


@pytest.mark.asyncio
async def test_worker_synthesizes_plays_and_cleans_up(monkeypatch, tmp_path):
    played, removed = [], []

    async def fake_synth(text, voice_id, timeout):
        f = tmp_path / "a.mp3"
        f.write_bytes(b"x")
        return str(f)

    class FakeVC:
        def is_connected(self):
            return True

    class FakeGuild:
        voice_client = FakeVC()

    class FakeBot:
        def get_guild(self, _):
            return FakeGuild()

    async def fake_play(vc, path):
        played.append(path)

    monkeypatch.setattr(ts, "synthesize", fake_synth)
    monkeypatch.setattr(ts, "_remove", lambda p: removed.append(p))
    mgr = ts.TTSManager(FakeBot(), lambda: {})
    monkeypatch.setattr(mgr, "_play", fake_play)

    s = ts.Session(guild_id=1, text_channel_id=2)
    task = asyncio.create_task(mgr._worker(s))
    s.queue.put_nowait(ts.QueueItem("hello", "v"))
    for _ in range(50):
        if removed:
            break
        await asyncio.sleep(0.01)
    task.cancel()
    assert len(played) == 1 and removed == played


@pytest.mark.asyncio
async def test_worker_survives_synthesis_failure(monkeypatch):
    calls = []

    async def flaky(text, voice_id, timeout):
        calls.append(text)
        raise RuntimeError("boom")

    class FakeGuild:
        voice_client = object()

    class FakeBot:
        def get_guild(self, _):
            return FakeGuild()

    monkeypatch.setattr(ts, "synthesize", flaky)
    mgr = ts.TTSManager(FakeBot(), lambda: {})
    s = ts.Session(guild_id=1, text_channel_id=2)
    task = asyncio.create_task(mgr._worker(s))
    s.queue.put_nowait(ts.QueueItem("one", "v"))
    s.queue.put_nowait(ts.QueueItem("two", "v"))
    for _ in range(50):
        if len(calls) == 2:
            break
        await asyncio.sleep(0.01)
    task.cancel()
    assert calls == ["one", "two"]


def test_ensure_opus_uses_discord_default_loader(monkeypatch):
    """On Windows find_library('opus') finds nothing, but discord.py bundles a DLL."""
    import discord

    state = {"loaded": False}
    monkeypatch.setattr(discord.opus, "is_loaded", lambda: state["loaded"])

    def fake_default():
        state["loaded"] = True
        return True

    monkeypatch.setattr(discord.opus, "_load_default", fake_default)
    monkeypatch.setattr(ts.ctypes.util, "find_library", lambda name: None)
    assert ts.ensure_opus() is True


def test_ensure_opus_false_when_nothing_loads(monkeypatch):
    import discord

    monkeypatch.setattr(discord.opus, "is_loaded", lambda: False)
    monkeypatch.setattr(discord.opus, "_load_default", lambda: False)
    monkeypatch.setattr(discord.opus, "load_opus", lambda name: (_ for _ in ()).throw(OSError("no")))
    monkeypatch.setattr(ts.ctypes.util, "find_library", lambda name: None)
    assert ts.ensure_opus() is False

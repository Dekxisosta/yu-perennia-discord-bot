import asyncio
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from services.commands import tts_service as ts  # noqa: E402
from utils.text_splicer import splice  # noqa: E402


# ---------------------------------------------------------------- splicer
def test_short_text_is_one_chunk():
    assert splice("Hello there.") == ["Hello there."]


def test_empty_text_has_no_chunks():
    assert splice("") == [] and splice("   ") == []


def test_cuts_at_sentences_and_keeps_abbreviations_and_decimals():
    assert splice("Dr. Smith paid 3.5 dollars. Then he left... Really?! Yes.", 40) == [
        "Dr. Smith paid 3.5 dollars.",
        "Then he left... Really?! Yes.",
    ]


def test_long_sentence_is_cut_at_commas_then_spaces():
    text = "I went to the store, bought some milk, and then came home because it was raining very hard"
    chunks = splice(text, 40)
    assert all(len(c) <= 40 for c in chunks)
    assert chunks[0] == "I went to the store, bought some milk,"
    assert " ".join(chunks) == text


def test_first_chunk_can_be_shorter():
    chunks = splice("Nel says. " + "word " * 40, 120, 30)
    assert chunks[0] == "Nel says. word word word word" or len(chunks[0]) <= 30


def test_unbroken_text_is_hard_cut_and_cjk_sentences_split():
    assert splice("a" * 50, 20) == ["a" * 20, "a" * 20, "a" * 10]
    assert splice("これは長い文章です。次の文です、そして続きます。", 15) == ["これは長い文章です。", "次の文です、そして続きます。"]


def test_no_chunk_exceeds_limit_and_no_text_is_lost():
    text = "word " * 100
    chunks = splice(text, 120, 60)
    assert all(len(c) <= 120 for c in chunks)
    assert " ".join(chunks).split() == text.split()


# ---------------------------------------------------------------- pipeline
class FakeVC:
    pass


class FakeGuild:
    def __init__(self):
        self.voice_client = FakeVC()


def make(monkeypatch, settings=None):
    events = []
    guild = FakeGuild()

    class Bot:
        def get_guild(self, _):
            return guild

    mgr = ts.TTSManager(Bot(), lambda: {"settings": {"chunk-chars": 20, "chunk-first-chars": 20, **(settings or {})}})
    session = ts.Session(guild_id=1, text_channel_id=2)
    mgr.sessions[1] = session
    removed = []
    monkeypatch.setattr(ts, "_remove", lambda p: removed.append(p))
    return mgr, session, guild, events, removed


@pytest.mark.asyncio
async def test_chunks_play_in_order_and_next_is_synthesized_during_playback(monkeypatch):
    mgr, session, guild, events, removed = make(monkeypatch)

    async def fake_synth(text, voice, timeout):
        events.append(("synth", text))
        return f"{text}.mp3"

    async def fake_play(vc, path):
        events.append(("play-start", path))
        await asyncio.sleep(0.05)
        events.append(("play-end", path))

    monkeypatch.setattr(ts, "synthesize", fake_synth)
    monkeypatch.setattr(ts.TTSManager, "_play", staticmethod(fake_play))
    await mgr._speak(session, guild, ts.QueueItem("One two three. Four five six. Seven eight nine.", "v"))
    played = [p for kind, p in events if kind == "play-start"]
    assert played == ["One two three..mp3", "Four five six..mp3", "Seven eight nine..mp3"]
    # the 2nd clip was synthesized before the 1st finished playing
    assert events.index(("synth", "Four five six.")) < events.index(("play-end", "One two three..mp3"))
    assert removed == played


@pytest.mark.asyncio
async def test_failed_chunk_is_skipped_not_fatal(monkeypatch):
    mgr, session, guild, events, removed = make(monkeypatch)

    async def fake_synth(text, voice, timeout):
        if text.startswith("Four"):
            raise RuntimeError("boom")
        return f"{text}.mp3"

    async def fake_play(vc, path):
        events.append(path)

    monkeypatch.setattr(ts, "synthesize", fake_synth)
    monkeypatch.setattr(ts.TTSManager, "_play", staticmethod(fake_play))
    await mgr._speak(session, guild, ts.QueueItem("One two three. Four five six. Seven eight nine.", "v"))
    assert events == ["One two three..mp3", "Seven eight nine..mp3"]


@pytest.mark.asyncio
async def test_skip_drops_the_rest_of_the_message(monkeypatch):
    mgr, session, guild, events, removed = make(monkeypatch)

    async def fake_synth(text, voice, timeout):
        return f"{text}.mp3"

    async def fake_play(vc, path):
        events.append(path)
        await asyncio.sleep(0.05)  # the next clip finishes synthesizing while this one plays
        session.skip_gen += 1  # /skip pressed while the first chunk plays

    monkeypatch.setattr(ts, "synthesize", fake_synth)
    monkeypatch.setattr(ts.TTSManager, "_play", staticmethod(fake_play))
    await mgr._speak(session, guild, ts.QueueItem("One two three. Four five six. Seven eight nine.", "v"))
    assert events == ["One two three..mp3"]
    assert "Four five six..mp3" in removed  # the prefetched clip was cleaned up, not leaked

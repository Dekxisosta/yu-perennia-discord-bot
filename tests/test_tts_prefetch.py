import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from services.commands import tts_service as ts  # noqa: E402


def setup(tmp_path, monkeypatch, texts):
    events = []

    async def fake_synthesize(text, voice_id, timeout):
        events.append(("synth", text))
        await asyncio.sleep(0.02)
        path = tmp_path / f"clip{len(events)}.mp3"
        path.write_bytes(b"x")
        return str(path)

    async def fake_play(vc, path):
        events.append(("play-start", Path(path).name))
        await asyncio.sleep(0.1)
        events.append(("play-end", Path(path).name))

    monkeypatch.setattr(ts, "synthesize", fake_synthesize)
    monkeypatch.setattr(ts.TTSManager, "_play", staticmethod(fake_play))
    guild = SimpleNamespace(id=1, voice_client=SimpleNamespace())
    bot = SimpleNamespace(get_guild=lambda gid: guild)
    mgr = ts.TTSManager(bot, lambda: {"settings": {}})
    session = ts.Session(guild_id=1, text_channel_id=50)
    session.queue = asyncio.Queue(maxsize=15)
    mgr.sessions[1] = session
    for text in texts:
        session.queue.put_nowait(ts.QueueItem(text, "voice"))
    return mgr, session, events


async def run_worker(mgr, session, seconds):
    session.task = asyncio.create_task(mgr._worker(session))
    await asyncio.sleep(seconds)
    session.task.cancel()
    await asyncio.gather(session.task, return_exceptions=True)


@pytest.mark.asyncio
async def test_next_message_is_synthesized_while_the_last_chunk_of_the_current_one_plays(tmp_path, monkeypatch):
    mgr, session, events = setup(tmp_path, monkeypatch, ["Hello there", "Second message"])
    await run_worker(mgr, session, 0.5)
    synths = [e for e in events if e[0] == "synth"]
    assert synths == [("synth", "Hello there"), ("synth", "Second message")]  # each synthesized exactly once
    first_end = next(i for i, e in enumerate(events) if e[0] == "play-end")
    assert events.index(("synth", "Second message")) < first_end  # ...and the second began before the first ended
    assert [e[0] for e in events].count("play-end") == 2 and session.prefetch is None


@pytest.mark.asyncio
async def test_long_messages_prefetch_only_at_their_last_chunk(tmp_path, monkeypatch):
    long = "One two three four five. " * 8  # several chunks
    mgr, session, events = setup(tmp_path, monkeypatch, [long, "Next one"])
    await run_worker(mgr, session, 1.5)
    synths = [e[1] for e in events if e[0] == "synth"]
    assert synths.count("Next one") == 1 and synths[-1] == "Next one"  # prefetched after all of the long one's chunks
    assert len(synths) > 3 and [e[0] for e in events].count("play-end") == len(synths)


@pytest.mark.asyncio
async def test_leaving_discards_the_prefetched_clip(tmp_path, monkeypatch):
    mgr, session, events = setup(tmp_path, monkeypatch, ["Hello there", "Second message"])
    session.task = asyncio.create_task(mgr._worker(session))
    await asyncio.sleep(0.06)  # first clip is playing and the second is being prefetched
    assert session.prefetch is not None
    await mgr._cleanup(1)
    await asyncio.sleep(0.05)
    assert session.prefetch is None
    assert not [e for e in events if e[0] == "play-start" and e[1] != "clip1.mp3"]  # the second never plays

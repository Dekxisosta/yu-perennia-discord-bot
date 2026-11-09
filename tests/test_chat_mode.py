import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from cogs.commands import cog_ask  # noqa: E402
from services.commands import ask_service as asks  # noqa: E402


class FakeGemini:
    """Stands in for GeminiClient: records every request and answers from a script."""

    def __init__(self, answers=("Sure, happy to help!",), delay=0.0, configured=True):
        self.answers, self.delay, self.configured = list(answers), delay, configured
        self.calls = []

    async def ask(self, question, **kwargs):
        self.calls.append((question, kwargs))
        if self.delay:
            await asyncio.sleep(self.delay)
        answer = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if isinstance(answer, Exception):
            raise answer
        return answer

    async def close(self):
        pass


class FakeManager:
    def __init__(self):
        self.said = []

    async def say_text(self, guild, member, text, use_member_voice=True):
        self.said.append((text, use_member_voice))
        return True


class FakeMessage:
    def __init__(self, author_id, name, text, channel_id=50):
        self.author = SimpleNamespace(id=author_id, display_name=name, bot=False)
        self.guild = SimpleNamespace(id=1)
        self.channel = SimpleNamespace(id=channel_id)
        self.clean_content = text
        self.attachments = []
        self.replies = []

    async def reply(self, text, **kwargs):
        self.replies.append(text)


def make_cog(gemini=None):
    cog = cog_ask.Ask(SimpleNamespace())
    cog.gemini = gemini or FakeGemini()
    return cog


@pytest.mark.asyncio
async def test_a_message_is_asked_with_the_channel_memory_then_spoken_and_typed():
    cog, mgr = make_cog(), FakeManager()
    first = FakeMessage(1, "Nel", "Yu, what is a black hole?")
    await cog._chat(mgr, first)
    question, kwargs = cog.gemini.calls[0]
    assert "<conversation>\nNel: Yu, what is a black hole?\n</conversation>" in question
    assert question.endswith("<reply_to>Nel</reply_to>")
    assert "<memory>" in kwargs["system"] and "<output_format>" in kwargs["system"]
    assert kwargs["max_output_tokens"] == 160
    assert mgr.said == [("Sure, happy to help!", False)]  # spoken in the steady server voice
    assert first.replies == ["Sure, happy to help!"]  # and typed
    assert [(t.name, t.text) for t in cog.memory.recent(50)] == [
        ("Nel", "Yu, what is a black hole?"), ("Yu", "Sure, happy to help!")
    ]

    second = FakeMessage(2, "Dex", "and what is a white hole?")  # another person, same channel: she remembers
    await cog._chat(mgr, second)
    assert "Nel: Yu, what is a black hole?\nYu: Sure, happy to help!\nDex: and what is a white hole?" in cog.gemini.calls[1][0]


@pytest.mark.asyncio
async def test_memory_is_per_channel():
    cog, mgr = make_cog(), FakeManager()
    await cog._chat(mgr, FakeMessage(1, "Nel", "secret plan", channel_id=50))
    await cog._chat(mgr, FakeMessage(2, "Dex", "hello there", channel_id=60))
    assert "secret plan" not in cog.gemini.calls[1][0]
    assert [t.text for t in cog.memory.recent(60)][0] == "hello there"


@pytest.mark.asyncio
async def test_silent_reply_says_and_types_nothing_and_is_not_remembered_as_speech():
    cog, mgr = make_cog(FakeGemini(["[[SILENT]]"])), FakeManager()
    msg = FakeMessage(1, "Nel", "lol same")
    await cog._chat(mgr, msg)
    assert mgr.said == [] and msg.replies == []
    assert [t.role for t in cog.memory.recent(50)] == ["user"]  # the message is remembered, no Yu turn


@pytest.mark.asyncio
async def test_cooldown_still_remembers_but_does_not_ask_again():
    cog, mgr = make_cog(), FakeManager()
    await cog._chat(mgr, FakeMessage(1, "Nel", "first"))
    await cog._chat(mgr, FakeMessage(1, "Nel", "second right away"))
    assert len(cog.gemini.calls) == 1
    assert [t.text for t in cog.memory.recent(50)] == ["first", "Sure, happy to help!", "second right away"]


@pytest.mark.asyncio
async def test_only_the_newest_waiting_message_is_answered():
    cog, mgr = make_cog(FakeGemini(delay=0.05)), FakeManager()
    msgs = [FakeMessage(i, f"U{i}", f"message {i}") for i in (1, 2, 3)]
    await asyncio.gather(*(cog._chat(mgr, m) for m in msgs))
    assert len(cog.gemini.calls) == 2  # the first runs at once; the middle one is skipped
    assert all(f"U{i}: message {i}" in cog.gemini.calls[1][0] for i in (1, 2, 3))  # the last sees everything
    assert len(mgr.said) == 2


@pytest.mark.asyncio
async def test_without_a_key_messages_are_remembered_but_nothing_is_asked():
    cog, mgr = make_cog(FakeGemini(configured=False)), FakeManager()
    await cog._chat(mgr, FakeMessage(1, "Nel", "hello?"))
    assert cog.gemini.calls == [] and mgr.said == [] and len(cog.memory.recent(50)) == 1


@pytest.mark.asyncio
async def test_dead_quota_pauses_chat_instead_of_hammering_gemini():
    cog, mgr = make_cog(FakeGemini([asks.AskError("quota")])), FakeManager()
    await cog._chat(mgr, FakeMessage(1, "Nel", "hi"))
    await cog._chat(mgr, FakeMessage(2, "Dex", "hi"))
    assert len(cog.gemini.calls) == 1 and mgr.said == []


@pytest.mark.asyncio
async def test_empty_and_attachment_only_messages():
    cog, mgr = make_cog(), FakeManager()
    await cog._chat(mgr, FakeMessage(1, "Nel", "   "))
    assert cog.gemini.calls == [] and cog.memory.recent(50) == []
    pic = FakeMessage(1, "Nel", "")
    pic.attachments = [object()]
    await cog._chat(mgr, pic)
    assert "Nel: [sent an attachment]" in cog.gemini.calls[0][0]

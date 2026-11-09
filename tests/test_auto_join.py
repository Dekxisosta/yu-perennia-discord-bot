import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import discord
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from services.commands import tts_service as ts  # noqa: E402
from services.commands.server_settings_service import ServerSettings  # noqa: E402


class FakeVoiceChannel(discord.VoiceChannel):
    def __init__(self, cid, members=()):
        self.id, self.name, self._members = cid, f"vc{cid}", list(members)

    @property
    def members(self):
        return self._members

    def __eq__(self, other):
        return self is other

    def __hash__(self):
        return id(self)


def human(i):
    return SimpleNamespace(id=i, bot=False)


class FakeVC:
    def __init__(self, channel):
        self.channel = channel

    def is_connected(self):
        return True


class FakeGuild:
    def __init__(self, bot):
        self.id, self.name, self.afk_channel = 1, "g", None
        self.voice_client = None
        self.text = SimpleNamespace(id=50, mention="<#50>")
        self.left = 0

    def get_channel(self, cid):
        return self.text if cid == 50 else None


def make(tmp_path, auto_join=True, channels=(10, 11, 12)):
    bot = SimpleNamespace(user=SimpleNamespace(id=999))
    guild = FakeGuild(bot)
    settings = ServerSettings(tmp_path / "s.json")
    if auto_join:
        settings.set(1, auto_join_channels=[str(c) for c in channels])
    mgr = ts.TTSManager(bot, lambda: {}, settings)

    async def fake_connect(g, target, text_id, mention=None):
        g.voice_client = FakeVC(target)
        mgr.sessions[g.id] = ts.Session(guild_id=g.id, text_channel_id=text_id)
        return "join-ok", {"voice": target.name, "text": mention}

    async def fake_leave(g):
        g.voice_client = None
        mgr.sessions.pop(g.id, None)
        g.left += 1
        return True

    mgr.connect, mgr.leave = fake_connect, fake_leave
    return mgr, guild


def state(channel):
    return SimpleNamespace(channel=channel)


@pytest.mark.asyncio
async def test_auto_join_when_someone_enters(tmp_path):
    mgr, guild = make(tmp_path)
    room = FakeVoiceChannel(10)
    u = human(1)
    room._members = [u]
    member = SimpleNamespace(id=1, bot=False, guild=guild)
    events = await mgr.handle_voice_state(member, state(None), state(room))
    assert [e[0] for e in events] == ["auto-join-ok"]
    assert events[0][1] == room.id  # reads the voice channel's own chat
    assert guild.voice_client.channel is room


@pytest.mark.asyncio
async def test_no_auto_join_when_disabled_or_already_connected(tmp_path):
    mgr, guild = make(tmp_path, auto_join=False)
    room = FakeVoiceChannel(10, [human(1)])
    member = SimpleNamespace(id=1, bot=False, guild=guild)
    assert await mgr.handle_voice_state(member, state(None), state(room)) == []
    assert guild.voice_client is None

    mgr.server_settings.set_auto_join_channel(1, 10, True)
    guild.voice_client = FakeVC(FakeVoiceChannel(11, [human(2)]))
    assert await mgr.handle_voice_state(member, state(None), state(room)) == []


@pytest.mark.asyncio
async def test_leaves_immediately_when_last_person_leaves(tmp_path):
    mgr, guild = make(tmp_path)
    room = FakeVoiceChannel(10, [])  # last human just left
    guild.voice_client = FakeVC(room)
    mgr.sessions[1] = ts.Session(guild_id=1, text_channel_id=50)
    member = SimpleNamespace(id=1, bot=False, guild=guild)
    events = await mgr.handle_voice_state(member, state(room), state(None))
    assert [e[0] for e in events] == ["auto-left"] and guild.left == 1


@pytest.mark.asyncio
async def test_stays_while_someone_is_left(tmp_path):
    mgr, guild = make(tmp_path)
    room = FakeVoiceChannel(10, [human(2)])
    guild.voice_client = FakeVC(room)
    mgr.sessions[1] = ts.Session(guild_id=1, text_channel_id=50)
    member = SimpleNamespace(id=1, bot=False, guild=guild)
    assert await mgr.handle_voice_state(member, state(room), state(None)) == []
    assert guild.left == 0


@pytest.mark.asyncio
async def test_follows_person_who_moves_rooms(tmp_path):
    mgr, guild = make(tmp_path)
    a, b = FakeVoiceChannel(10, []), FakeVoiceChannel(11, [human(1)])
    guild.voice_client = FakeVC(a)
    mgr.sessions[1] = ts.Session(guild_id=1, text_channel_id=50)
    member = SimpleNamespace(id=1, bot=False, guild=guild)
    events = await mgr.handle_voice_state(member, state(a), state(b))
    assert [e[0] for e in events] == ["auto-left", "auto-join-ok"]
    assert guild.voice_client.channel is b


@pytest.mark.asyncio
async def test_leaves_if_moved_into_empty_room(tmp_path):
    mgr, guild = make(tmp_path)
    empty = FakeVoiceChannel(12, [])
    guild.voice_client = FakeVC(empty)
    mgr.sessions[1] = ts.Session(guild_id=1, text_channel_id=50)
    me = SimpleNamespace(id=999, bot=True, guild=guild)
    events = await mgr.handle_voice_state(me, state(FakeVoiceChannel(10)), state(empty))
    assert [e[0] for e in events] == ["auto-left"]


@pytest.mark.asyncio
async def test_bots_do_not_trigger_auto_join(tmp_path):
    mgr, guild = make(tmp_path)
    room = FakeVoiceChannel(10, [SimpleNamespace(id=5, bot=True)])
    member = SimpleNamespace(id=5, bot=True, guild=guild)
    assert await mgr.handle_voice_state(member, state(None), state(room)) == []


@pytest.mark.asyncio
async def test_auto_join_only_for_listed_voice_channels(tmp_path):
    mgr, guild = make(tmp_path, channels=(10,))
    member = SimpleNamespace(id=1, bot=False, guild=guild)
    other = FakeVoiceChannel(11, [human(1)])  # auto-join is on elsewhere, but not for this channel
    assert await mgr.handle_voice_state(member, state(None), state(other)) == []
    assert guild.voice_client is None
    listed = FakeVoiceChannel(10, [human(1)])
    events = await mgr.handle_voice_state(member, state(None), state(listed))
    assert [e[0] for e in events] == ["auto-join-ok"] and guild.voice_client.channel is listed


@pytest.mark.asyncio
async def test_toggling_a_channel_off_stops_auto_join(tmp_path):
    mgr, guild = make(tmp_path, channels=(10,))
    assert mgr.server_settings.set_auto_join_channel(1, 10, False) is True
    assert mgr.server_settings.set_auto_join_channel(1, 10, False) is False  # nothing changed
    member = SimpleNamespace(id=1, bot=False, guild=guild)
    room = FakeVoiceChannel(10, [human(1)])
    assert await mgr.handle_voice_state(member, state(None), state(room)) == []


@pytest.mark.asyncio
async def test_startup_rejoin_only_considers_listed_channels(tmp_path):
    mgr, guild = make(tmp_path, channels=(11,))
    busy_unlisted = FakeVoiceChannel(10, [human(1), human(2), human(3)])
    listed = FakeVoiceChannel(11, [human(4)])
    guild.voice_channels = [busy_unlisted, listed]
    mgr.bot.get_guild = lambda gid: guild if gid == 1 else None
    await mgr.auto_join_on_start()
    assert guild.voice_client.channel is listed


def test_server_settings_persist(tmp_path):
    path = tmp_path / "s.json"
    s = ServerSettings(path)
    assert s.get(7) == {"auto_join_channels": [], "chat_mode_channels": [], "voice": None, "vc_greet": False,
                      "vc_enabled": True, "vc_sayname": True, "vc_translate": True, "translate_api": "deepl"}
    s.set(7, auto_join_channels=["30", "20"], voice="heart", vc_greet=True, vc_enabled=False, vc_sayname=False,
          vc_translate=False, translate_api="google")
    again = ServerSettings(path)
    assert again.get(7) == {"auto_join_channels": ["20", "30"], "chat_mode_channels": [], "voice": "heart", "vc_greet": True, "vc_enabled": False, "vc_sayname": False,
                              "vc_translate": False, "translate_api": "google"}
    assert again.auto_join_guilds() == [7]


# ---------------------------------------------------------------- /vctoggle + voices + pipeline
from services.commands.server_settings_service import UserSettings  # noqa: E402


def test_user_settings_default_on_and_persist(tmp_path):
    path = tmp_path / "u.json"
    u = UserSettings(path)
    assert u.is_enabled(5) is True and u.get_enabled(5) is None
    u.set_enabled(5, False)
    assert UserSettings(path).is_enabled(5) is False
    u.set_enabled(5, True)
    assert UserSettings(path).is_enabled(5) is True


class FakeMessage:
    def __init__(self, author_id=1, channel_id=50, content="hello there", vc_channel=None, guild=None):
        self.author = SimpleNamespace(
            id=author_id, bot=False, display_name="Dekxi", name="dekxi",
            voice=SimpleNamespace(channel=vc_channel),
        )
        self.guild = guild
        self.channel = SimpleNamespace(id=channel_id)
        self.content = content
        self.clean_content = content
        self.attachments = []


def pipeline_setup(tmp_path):
    bot = SimpleNamespace(user=SimpleNamespace(id=999))
    room = FakeVoiceChannel(10, [human(1)])
    guild = FakeGuild(bot)
    guild.voice_client = FakeVC(room)
    users = UserSettings(tmp_path / "u.json")
    mgr = ts.TTSManager(bot, lambda: {}, None, users)
    mgr.sessions[1] = ts.Session(guild_id=1, text_channel_id=50)
    return mgr, guild, room, users


@pytest.mark.asyncio
async def test_pipeline_queues_message_for_enabled_user(tmp_path):
    mgr, guild, room, users = pipeline_setup(tmp_path)
    await mgr.handle_message(FakeMessage(vc_channel=room, guild=guild), "yp!")
    item = mgr.sessions[1].queue.get_nowait()
    assert item.text == "Dekxi says. hello there"


@pytest.mark.asyncio
async def test_pipeline_skips_user_who_disabled_tts(tmp_path):
    mgr, guild, room, users = pipeline_setup(tmp_path)
    users.set_enabled(1, False)
    await mgr.handle_message(FakeMessage(vc_channel=room, guild=guild), "yp!")
    assert mgr.sessions[1].queue.empty()
    users.set_enabled(1, True)
    await mgr.handle_message(FakeMessage(vc_channel=room, guild=guild), "yp!")
    assert not mgr.sessions[1].queue.empty()


@pytest.mark.asyncio
async def test_pipeline_ignores_wrong_channel_commands_and_non_listeners(tmp_path):
    mgr, guild, room, users = pipeline_setup(tmp_path)
    await mgr.handle_message(FakeMessage(channel_id=51, vc_channel=room, guild=guild), "yp!")
    await mgr.handle_message(FakeMessage(content="yp!join", vc_channel=room, guild=guild), "yp!")
    await mgr.handle_message(FakeMessage(vc_channel=None, guild=guild), "yp!")
    assert mgr.sessions[1].queue.empty()


def test_user_settings_voice_persists_and_reads_old_format(tmp_path):
    path = tmp_path / "u.json"
    u = UserSettings(path)
    assert u.get_voice(5) is None
    u.set_voice(5, "heart")
    u.set_enabled(5, False)
    again = UserSettings(path)
    assert again.get_voice(5) == "heart" and again.is_enabled(5) is False
    path.write_text('{"9": false}', encoding="utf-8")  # file written before voices existed
    old = UserSettings(path)
    assert old.is_enabled(9) is False and old.get_voice(9) is None


CFG = {"voices": {"a": {"id": "en-US-AriaNeural"}, "b": {"id": "en-US-GuyNeural"}}, "settings": {"default-voice": "a"}}


def test_voice_precedence_user_then_server_then_default():
    assert ts.resolve_voice_key(CFG, "b", "a") == "b"
    assert ts.resolve_voice_key(CFG, None, "b") == "b"
    assert ts.resolve_voice_key(CFG, "gone", "b") == "b"  # removed personal voice falls to the server's
    assert ts.resolve_voice_key(CFG, None, None) is None
    assert ts.voice_id_for(CFG, None) == "en-US-AriaNeural"


@pytest.mark.asyncio
async def test_pipeline_uses_personal_voice_over_server_voice(tmp_path):
    mgr, guild, room, users = pipeline_setup(tmp_path)
    mgr.get_cfg = lambda: CFG
    mgr.server_settings = ServerSettings(tmp_path / "s.json")
    mgr.server_settings.set(1, voice="b")
    await mgr.handle_message(FakeMessage(vc_channel=room, guild=guild), "yp!")
    assert mgr.sessions[1].queue.get_nowait().voice_id == "en-US-GuyNeural"  # server voice
    users.set_voice(1, "a")
    await mgr.handle_message(FakeMessage(vc_channel=room, guild=guild), "yp!")
    assert mgr.sessions[1].queue.get_nowait().voice_id == "en-US-AriaNeural"  # personal wins


# ---------------------------------------------------------------- greetings
def person(i, name="Dekxi", guild=None):
    return SimpleNamespace(id=i, bot=False, guild=guild, display_name=name, name=name.lower())


def spoken(mgr):
    out = []
    q = mgr.sessions[1].queue
    while not q.empty():
        out.append(q.get_nowait().text)
    return out


@pytest.mark.asyncio
async def test_greets_on_join_and_leave_when_enabled(tmp_path):
    mgr, guild = make(tmp_path, auto_join=False)
    mgr.server_settings.set(1, vc_greet=True)
    room = FakeVoiceChannel(10, [human(2), human(1)])
    guild.voice_client = FakeVC(room)
    mgr.sessions[1] = ts.Session(guild_id=1, text_channel_id=10)
    me = person(1, "Dekxi", guild)
    await mgr.handle_voice_state(me, state(None), state(room))
    room._members = [human(2)]
    await mgr.handle_voice_state(me, state(room), state(None))
    assert spoken(mgr) == ["Welcome, Dekxi!", "Goodbye, Dekxi!"]


@pytest.mark.asyncio
async def test_no_greeting_when_disabled(tmp_path):
    mgr, guild = make(tmp_path, auto_join=False)
    room = FakeVoiceChannel(10, [human(2), human(1)])
    guild.voice_client = FakeVC(room)
    mgr.sessions[1] = ts.Session(guild_id=1, text_channel_id=10)
    await mgr.handle_voice_state(person(1, guild=guild), state(None), state(room))
    assert spoken(mgr) == []


@pytest.mark.asyncio
async def test_auto_join_greets_the_person_who_triggered_it(tmp_path):
    mgr, guild = make(tmp_path)
    mgr.server_settings.set(1, vc_greet=True)
    room = FakeVoiceChannel(10, [human(1)])
    await mgr.handle_voice_state(person(1, "Nel", guild), state(None), state(room))
    assert spoken(mgr) == ["Welcome, Nel!"]


@pytest.mark.asyncio
async def test_no_goodbye_to_last_person_and_vctoggle_off_is_respected(tmp_path):
    mgr, guild = make(tmp_path, auto_join=False)
    mgr.server_settings.set(1, vc_greet=True)
    mgr.user_settings = UserSettings(tmp_path / "u.json")
    room = FakeVoiceChannel(10, [])  # last person just left, Yu clocks out
    guild.voice_client = FakeVC(room)
    mgr.sessions[1] = ts.Session(guild_id=1, text_channel_id=10)
    events = await mgr.handle_voice_state(person(1, guild=guild), state(room), state(None))
    assert [e[0] for e in events] == ["auto-left"] and 1 not in mgr.sessions

    mgr.sessions[1] = ts.Session(guild_id=1, text_channel_id=10)
    guild.voice_client = FakeVC(room)
    room._members = [human(2), human(3)]
    mgr.user_settings.set_enabled(3, False)
    await mgr.handle_voice_state(person(3, guild=guild), state(None), state(room))
    assert spoken(mgr) == []


# ---------------------------------------------------------------- /vctoggle: user beats server
@pytest.mark.asyncio
async def test_server_vctoggle_off_silences_everyone_except_people_who_opted_in(tmp_path):
    mgr, guild, room, users = pipeline_setup(tmp_path)
    mgr.server_settings = ServerSettings(tmp_path / "s.json")
    mgr.server_settings.set(1, vc_enabled=False)
    await mgr.handle_message(FakeMessage(vc_channel=room, guild=guild), "yp!")
    assert mgr.sessions[1].queue.empty()  # server off, person never chose

    users.set_enabled(1, True)  # personal "on" beats the server's "off"
    await mgr.handle_message(FakeMessage(vc_channel=room, guild=guild), "yp!")
    assert not mgr.sessions[1].queue.empty()


@pytest.mark.asyncio
async def test_personal_off_beats_server_on_and_reset_follows_server(tmp_path):
    mgr, guild, room, users = pipeline_setup(tmp_path)
    mgr.server_settings = ServerSettings(tmp_path / "s.json")  # server on by default
    users.set_enabled(1, False)
    await mgr.handle_message(FakeMessage(vc_channel=room, guild=guild), "yp!")
    assert mgr.sessions[1].queue.empty()

    users.set_enabled(1, None)  # reset -> server decides again
    await mgr.handle_message(FakeMessage(vc_channel=room, guild=guild), "yp!")
    assert not mgr.sessions[1].queue.empty()


def test_old_user_settings_file_true_means_unset(tmp_path):
    path = tmp_path / "u.json"
    path.write_text('{"1": true, "2": false}', encoding="utf-8")
    u = UserSettings(path)
    assert u.get_enabled(1) is None and u.get_enabled(2) is False


# ---------------------------------------------------------------- /vcsayname: user beats server
@pytest.mark.asyncio
async def test_vcsayname_server_off_user_on_and_reset(tmp_path):
    mgr, guild, room, users = pipeline_setup(tmp_path)
    mgr.server_settings = ServerSettings(tmp_path / "s.json")

    async def said(*, wait_gap=True):
        await mgr.handle_message(FakeMessage(vc_channel=room, guild=guild), "yp!")
        text = mgr.sessions[1].queue.get_nowait().text
        mgr.sessions[1].last_speaker = None  # next message announces again if names are on
        return text

    assert await said() == "Dekxi says. hello there"      # on by default
    mgr.server_settings.set(1, vc_sayname=False)
    assert await said() == "hello there"                   # server off
    users.set_sayname(1, True)
    assert await said() == "Dekxi says. hello there"      # personal on beats server off
    users.set_sayname(1, None)
    assert await said() == "hello there"                   # reset -> server decides
    mgr.server_settings.set(1, vc_sayname=True)
    users.set_sayname(1, False)
    assert await said() == "hello there"                   # personal off beats server on


def test_user_sayname_persists_and_defaults_to_unset(tmp_path):
    path = tmp_path / "u.json"
    u = UserSettings(path)
    assert u.get_sayname(5) is None and u.is_sayname(5) is True
    u.set_sayname(5, False)
    assert UserSettings(path).get_sayname(5) is False

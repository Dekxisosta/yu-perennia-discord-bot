import asyncio
import ctypes.util
import importlib.metadata
import inspect
import os
import re
import shutil
import tempfile
import time
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache

import discord
from discord.ext import commands

from utils import kokoro_engine
from utils.romanize import JAPANESE, has_non_latin, romanize
from utils.speech_language import needs_translation
from utils.text_splicer import splice
from utils.console_logger import log

MODULE = "TTS"

DEFAULT_SETTINGS = {
    "default-voice": "aria",
    "max-chars": 400,
    "chunk-chars": 120,
    "chunk-first-chars": 60,
    "max-queue": 15,
    "announce-gap": 45,
    "synth-timeout": 20,
    "translate": True,
    "translate-timeout": 6,
}
FALLBACK_VOICE_ID = "en-US-AriaNeural"
KOKORO_PREFIX = "kokoro:"  # a voice id like "kokoro:af_heart" is rendered locally, not by edge-tts

# Used when the loaded tts config (e.g. an older dashboard copy) lacks these keys
DEFAULT_RESPONSES = {
    "auto-join-ok": "Yu joined **{voice}** and will read out its chat! 🍵",
    "auto-join-added": "Auto-join is **on** for **{voice}**! Yu will hop in when someone joins it and read out its chat. Other voice channels are unaffected. 🍵",
    "auto-join-already": "Auto-join is already **on** for **{voice}**.",
    "auto-join-removed": "Auto-join is **off** for **{voice}**. Yu will wait to be called there with `/vcjoin`! 🛎️",
    "auto-join-not-listed": "Auto-join was already **off** for **{voice}**.",
    "auto-join-status-on": "Auto-join is **on** for **{voice}**.",
    "auto-join-status-off": "Auto-join is **off** for **{voice}**. Use `/server-settings auto-join toggle enabled:True` while you're in it, or `/server-settings auto-join add`!",
    "auto-join-list": "Yu auto-joins these voice channels: {channels}",
    "auto-join-list-empty": "No voice channels are set to auto-join. Use `/server-settings auto-join toggle` while you're in one, or `/server-settings auto-join add`!",
    "auto-join-need-channel": "Join the voice channel you want first, or use `/server-settings auto-join add` to pick one!",
    "auto-join-usage": "Try `/server-settings auto-join toggle`, `/server-settings auto-join add`, `/server-settings auto-join remove` or `/server-settings auto-join list`!",
    "auto-join-no-permission": "Only people with **Manage Server** can change this!",
    "vc-translate-on": "Translation is **on**! Yu will translate other languages to English before reading them out in this server. 🌐",
    "vc-translate-off": "Translation is **off**. Yu will read messages exactly as they were written in this server.",
    "vc-translate-status-on": "Translation is **on** for this server.",
    "vc-translate-status-off": "Translation is **off** for this server. Use `/server-settings vctranslatetoggle on` to turn it on!",
    "translate-api-set": "Done! Yu will use **{api}** to translate messages in voice channels! 🌐",
    "translate-api-status": "Yu translates voice channel messages with **{api}**.",
    "translate-api-missing-key": "Heads up: **{api}** isn't set up on this bot yet (no `{env}` in its environment), so Yu will read messages as they are until it is.",
    "vc-sayname-on": "Done! Yu will say your name before reading your messages! 🎙️",
    "vc-sayname-off": "Okay! Yu won't say your name before your messages anymore. Use `/user-settings vcsayname on` to turn it back on!",
    "vc-sayname-reset": "Done! Yu will follow the server's setting for saying your name again! 🎙️",
    "server-vc-sayname-on": "Yu will say the speaker's name before reading messages in this server, unless people turned it off for themselves. 🎙️",
    "server-vc-sayname-off": "Yu won't say speakers' names before messages in this server, unless people turned it on for themselves with `/user-settings vcsayname on`.",
    "server-vc-sayname-status-on": "Saying names is **on** for this server.",
    "server-vc-sayname-status-off": "Saying names is **off** for this server. Use `/server-settings vcsayname on` to turn it on!",
    "vc-toggle-reset": "Done! Yu will follow the server's setting for your messages again! 🎙️",
    "server-vc-toggle-on": "Voice reading is **on** for this server! Yu reads people's messages in voice channels, unless they turned it off for themselves. 🎙️",
    "server-vc-toggle-off": "Voice reading is **off** for this server. Yu only reads people who turned it on for themselves with `/user-settings vctoggle on`.",
    "server-vc-toggle-status-on": "Voice reading is **on** for this server.",
    "server-vc-toggle-status-off": "Voice reading is **off** for this server. Use `/server-settings vctoggle on` to turn it on!",
    "vc-toggle-on": "Done! Yu will read your messages in voice channels again! 🎙️",
    "vc-toggle-off": "Okay! Yu won't read your messages in voice channels anymore. Use `/user-settings vctoggle on` to turn it back on!",
    "voice-set": "Done! Yu will read your messages in **{voice}** from now on! 🎙️",
    "vc-greet-on": "Greetings are **on**! Yu will welcome people who join her voice channel and say goodbye when they leave! 👋",
    "vc-greet-off": "Greetings are **off**. Yu won't greet people anymore.",
    "vc-greet-status-on": "Greetings are **on**. Yu welcomes people who join and says goodbye when they leave.",
    "vc-greet-status-off": "Greetings are **off**. Use `/server-settings vcgreettoggle on` to turn them on!",
    "greet-join": "Welcome, {name}!",
    "greet-leave": "Goodbye, {name}!",
    "voice-reset": "Done! Yu will use the server's voice for your messages again! 🎙️",
    "server-voice-set": "Done! Yu's default voice in this server is **{voice}**! Personal voices still win. 🎙️",
    "server-voice-reset": "Done! Yu's default voice in this server is back to normal! 🎙️",
    "unknown-voice": "Sorry, that voice isn't on the menu!",
    "vc-chatmode-on": "Chat mode is **on** for {channel}! Yu won't read messages out loud there anymore. She listens to the conversation and joins in out loud instead. 💬",
    "vc-chatmode-off": "Chat mode is **off** for {channel}. Yu goes back to reading messages out loud. 🎙️",
    "vc-chatmode-missing-key": "Heads up: this bot has no `GEMINI_API_KEY`, so Yu can't join the conversation until the bot owner adds one.",
}

CODE_BLOCK = re.compile(r"```[\s\S]*?```")
INLINE_CODE = re.compile(r"`([^`]*)`")
URL = re.compile(r"https?://\S+")
CUSTOM_EMOJI = re.compile(r"<a?:\w+:\d+>")
SPOILER = re.compile(r"\|\|[\s\S]*?\|\|")
MARKDOWN = re.compile(r"[*_~>#]+")
REPEATS = re.compile(r"(.)\1{3,}")
SPACES = re.compile(r"\s+")


# ------------------------------------------------------------------ config
def get_settings(cfg: dict | None) -> dict:
    return {**DEFAULT_SETTINGS, **((cfg or {}).get("settings") or {})}


def get_voices(cfg: dict | None) -> dict[str, dict]:
    voices = (cfg or {}).get("voices") or {}
    if not voices:
        voices = {"aria": {"label": "Aria (US, female)", "id": FALLBACK_VOICE_ID}}
    return voices


def resolve_voice_key(cfg: dict | None, *keys: str | None) -> str | None:
    """First key that is still a configured voice. Pass them highest precedence first
    (user voice, then server voice); None means the config default applies."""
    voices = get_voices(cfg)
    for key in keys:
        if key and key in voices:
            return key
    return None


def voice_id_for(cfg: dict | None, key: str | None) -> str:
    voices = get_voices(cfg)
    default = get_settings(cfg)["default-voice"]
    entry = voices.get(key or "") or voices.get(default) or next(iter(voices.values()))
    return entry.get("id", FALLBACK_VOICE_ID)


# ------------------------------------------------------------- text cleanup
@lru_cache(maxsize=8)
def _compile_pronunciations(items: tuple[tuple[str, str], ...]):
    if not items:
        return None, {}
    lookup = {k.lower(): v for k, v in items}
    # Longest first so "ggs" wins over "gg"
    keys = sorted(lookup, key=len, reverse=True)
    pattern = re.compile(
        r"(?<!\w)(" + "|".join(re.escape(k) for k in keys) + r")(?!\w)",
        re.IGNORECASE,
    )
    return pattern, lookup


def apply_pronunciations(text: str, pronunciations: dict | None) -> str:
    items = tuple(sorted((str(k), str(v)) for k, v in (pronunciations or {}).items()))
    pattern, lookup = _compile_pronunciations(items)
    if pattern is None:
        return text
    return pattern.sub(lambda m: lookup[m.group(1).lower()], text)


def truncate(text: str, limit: int) -> str:
    if limit <= 0 or len(text) <= limit:
        return text
    cut = text[:limit]
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut.rstrip(" ,.;:") + "…"


def clean_for_speech(
    text: str,
    pronunciations: dict | None = None,
    max_chars: int = 220,
) -> str:
    """Turn a Discord message into something a voice can read. Empty string = say nothing."""
    text = CODE_BLOCK.sub(" ", text)
    text = INLINE_CODE.sub(r"\1", text)
    text = SPOILER.sub(" spoiler ", text)
    text = URL.sub(" link ", text)
    text = CUSTOM_EMOJI.sub(" ", text)
    text = MARKDOWN.sub(" ", text)
    text = REPEATS.sub(r"\1\1\1", text)
    text = SPACES.sub(" ", text).strip()
    if not any(ch.isalnum() for ch in text):
        return ""
    text = apply_pronunciations(text, pronunciations)
    return truncate(text, max_chars)


def _clean_name(name: str | None) -> str:
    """Fancy fonts (𝓓𝓮𝓴𝔁𝓲, Ｄｅｋｘｉ) fold to plain letters, then symbols/emoji/underscores go."""
    name = unicodedata.normalize("NFKC", name or "")
    name = re.sub(r"[^\w\s'-]|_", " ", name)
    return SPACES.sub(" ", name).strip()


def _speakable(name: str) -> bool:
    return any(ch.isalnum() for ch in name) and not has_non_latin(name)


def speaker_name(member: discord.abc.User) -> str:
    """How Yu says someone's name:

    1. Display name, if it reads as plain letters (after folding fancy fonts and dropping symbols).
    2. Display name, romanized, if it contains Japanese (kana/kanji) - pykakasi readings.
    3. Otherwise (other scripts, emoji-only, empty) the username, if that reads as plain letters.
    4. Otherwise whatever romanizes: the display name, then the username.
    5. "Someone".
    """
    display = _clean_name(getattr(member, "display_name", None))
    username = _clean_name(getattr(member, "name", None))

    if _speakable(display):
        return display
    if JAPANESE.search(display):
        spoken = romanize(display).title()
        if spoken:
            return spoken
    if _speakable(username):
        return username
    for candidate in (display, username):
        spoken = romanize(candidate).title() if candidate else ""
        if any(ch.isalnum() for ch in spoken):
            return spoken
    return "Someone"


# ------------------------------------------------------- environment checks
def ffmpeg_executable() -> str | None:
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def ensure_opus() -> bool:
    if discord.opus.is_loaded():
        return True
    # discord.py ships its own libopus for Windows, so try its default loader first
    try:
        if discord.opus._load_default():
            return True
    except Exception:
        pass
    candidates = (
        ctypes.util.find_library("opus"),
        "libopus.so.0",
        "libopus.so",
        "libopus.0.dylib",
        "/opt/homebrew/lib/libopus.dylib",  # macOS, Apple Silicon (brew install opus)
        "/usr/local/lib/libopus.dylib",     # macOS, Intel
    )
    for name in candidates:
        if not name:
            continue
        try:
            discord.opus.load_opus(name)
            return True
        except Exception:
            continue
    return False


def voice_versions() -> str:
    """Library versions that matter for voice (logged at startup)."""
    def ver(name: str) -> str:
        try:
            return importlib.metadata.version(name)
        except Exception:
            return "not installed"

    return (
        f"discord.py={getattr(discord, '__version__', '?')}, davey={ver('davey')}, "
        f"PyNaCl={ver('PyNaCl')}, edge-tts={ver('edge-tts')}, "
        f"pykakasi={ver('pykakasi')}, anyascii={ver('anyascii')}"
    )


def voice_report(guild: discord.Guild, vc) -> str:
    """One line describing everything on Discord's side that can make Yu inaudible."""
    parts = [f"channel={getattr(vc.channel, 'name', '?')} ({type(vc.channel).__name__})"]
    state = getattr(guild.me, "voice", None)
    if state is not None:
        parts.append(
            f"server_muted={state.mute} suppressed={state.suppress} self_muted={state.self_mute}"
        )
    dave = getattr(getattr(vc, "_connection", None), "dave_session", None)
    if dave is None:
        parts.append("dave=off")
    else:
        parts.append(f"dave_ready={getattr(dave, 'ready', '?')}")
    return ", ".join(parts)


async def _wait_can_encrypt(conn, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if getattr(conn, "can_encrypt", True):
            return True
        await asyncio.sleep(0.25)
    return bool(getattr(conn, "can_encrypt", True))


async def ensure_dave_ready(vc) -> bool:
    """Make sure the voice connection can encrypt before we play.

    Discord calls now use end-to-end encryption (DAVE). If the library's encryption session never
    became ready, everything we send is dropped by listeners, so Yu looks like she is speaking but
    nobody hears her. When that happens, ask the library to rebuild its session once and wait.
    """
    conn = getattr(vc, "_connection", None)
    if conn is None or not getattr(conn, "dave_protocol_version", 0):
        return True  # not an end-to-end encrypted call
    if await _wait_can_encrypt(conn, 2.0):
        return True
    log("DAVE session is not ready to encrypt; rebuilding it.", module_name=MODULE, success=False)
    try:
        result = conn.reinit_dave_session()
        if inspect.isawaitable(result):
            await result
    except Exception as e:
        log(f"Could not rebuild the DAVE session: {e}", module_name=MODULE, success=False)
        return False
    if await _wait_can_encrypt(conn, 6.0):
        log("DAVE session is ready after the rebuild.", module_name=MODULE)
        return True
    log("DAVE session still cannot encrypt, so listeners will hear nothing. Update discord.py and "
        "davey, or report this to the discord.py issue tracker.", module_name=MODULE, success=False)
    return False


class MeteredPCMAudio(discord.FFmpegPCMAudio):
    """FFmpegPCMAudio that remembers the loudest sample it handed to Discord.

    A peak of 0 means the clip itself was silent; a healthy voice clip peaks in the thousands.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.peak = 0
        self.bytes_read = 0

    def read(self) -> bytes:
        data = super().read()
        if data:
            self.bytes_read += len(data)
            try:
                samples = memoryview(data[: len(data) // 2 * 2]).cast("h")
                if len(samples):
                    self.peak = max(self.peak, max(samples), -min(samples))
            except Exception:
                pass
        return data


# ----------------------------------------------------------------- sessions
@dataclass
class QueueItem:
    text: str  # lead + the message itself
    voice_id: str
    lead: str = ""  # "Name says. " when the speaker is announced; never translated


@dataclass
class Session:
    guild_id: int
    text_channel_id: int
    queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    task: asyncio.Task | None = None
    last_speaker: int | None = None
    last_spoken_at: float = 0.0
    skip_gen: int = 0  # bumped by /skip so the rest of a spliced message is dropped
    order_lock: asyncio.Lock = field(default_factory=asyncio.Lock)  # keeps spoken order while translating
    # (next queued item, its first chunk's text, the task synthesizing that chunk): started while the current
    # message's last chunk is playing, so the next message begins without waiting for synthesis
    prefetch: tuple[QueueItem, str, asyncio.Task] | None = None


def _peek(queue: asyncio.Queue):
    """The item the worker will take next, without removing it (None when the queue is empty)."""
    waiting = getattr(queue, "_queue", None)
    return waiting[0] if waiting else None


def should_announce(session: Session, author_id: int, now: float, gap: float) -> bool:
    """Say the speaker's name when the speaker changes or the room has been quiet."""
    return session.last_speaker != author_id or (now - session.last_spoken_at) > gap


async def _synthesize_edge(text: str, voice_id: str, timeout: float) -> str:
    """Render text to an mp3 with edge-tts and return the temp file path."""
    import edge_tts

    fd, path = tempfile.mkstemp(suffix=".mp3", prefix="yu_tts_")
    os.close(fd)
    try:
        await asyncio.wait_for(edge_tts.Communicate(text, voice_id).save(path), timeout)
        if os.path.getsize(path) == 0:
            raise RuntimeError("voice service returned empty audio")
    except BaseException:
        _remove(path)
        raise
    return path


async def synthesize(text: str, voice_id: str, timeout: float) -> str:
    """Render text to an audio file and return its path. Kokoro voices run locally and fall back
    to edge-tts if Kokoro is unavailable, so Yu never goes silent."""
    if voice_id.startswith(KOKORO_PREFIX):
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(kokoro_engine.synthesize_to_file, text, voice_id[len(KOKORO_PREFIX):]),
                max(timeout, 30),  # the very first call also loads the model
            )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log(f"Kokoro failed ({type(e).__name__}: {e}); using edge-tts instead.",
                module_name=MODULE, success=False)
            voice_id = FALLBACK_VOICE_ID
    return await _synthesize_edge(text, voice_id, timeout)


def _remove(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


def _discard(task: asyncio.Task | None) -> None:
    """Throw away a synthesis task that will no longer be played, and its audio file."""
    if task is None:
        return
    if task.done():
        if not task.cancelled() and task.exception() is None:
            _remove(task.result())
    else:
        task.cancel()


class TTSManager:
    """Per-server voice sessions: one queue and one worker task each."""

    def __init__(
        self, bot: commands.Bot, get_cfg, server_settings=None, user_settings=None, translator=None,
        google_translator=None,
    ):
        self.bot = bot
        self.translator = translator  # DeepL Translator | None: non-English messages are read in English
        self.google_translator = google_translator  # GoogleTranslator | None (/server-settings translate-api)
        self._translate_paused_until: dict[str, float] = {}  # api name -> monotonic time to retry
        self.user_settings = user_settings  # UserSettings | None (/user-settings vctoggle, personal voice)
        self.get_cfg = get_cfg  # returns the current tts config dict (reloads are picked up)
        self.server_settings = server_settings  # ServerSettings | None (auto-join)
        self._join_locks: dict[int, asyncio.Lock] = {}
        self.sessions: dict[int, Session] = {}

    # ---- join / leave
    async def join(self, ctx: commands.Context) -> tuple[str, dict]:
        """Returns (response key from tts_config.yaml `responses`, format values for it)."""
        guild = ctx.guild
        voice = getattr(ctx.author, "voice", None)
        if guild is None:
            return "server-only", {}
        if voice is None or voice.channel is None:
            return "not-in-voice", {}
        return await self.connect(guild, voice.channel, ctx.channel.id, ctx.channel.mention)

    async def connect(
        self, guild: discord.Guild, target, text_channel_id: int, text_mention: str | None = None
    ) -> tuple[str, dict]:
        """Join (or move to) `target` and start reading `text_channel_id`."""
        cfg = self.get_cfg()
        if ffmpeg_executable() is None:
            return "no-ffmpeg", {}
        if not ensure_opus():
            return "no-opus", {}

        perms = target.permissions_for(guild.me)
        if not (perms.connect and perms.speak):
            return "no-permission", {}

        existing = guild.voice_client
        moved = False
        try:
            if existing and existing.is_connected():
                if existing.channel != target:
                    await existing.move_to(target)
                    moved = True
            else:
                await target.connect(self_deaf=False)
        except Exception as e:
            log(f"Could not join voice: {e}", module_name=MODULE, success=False)
            return "failed", {}

        # In a Stage channel the bot is muted ("suppressed") until it asks to speak
        if isinstance(target, discord.StageChannel):
            try:
                await guild.me.edit(suppress=False)
            except Exception as e:
                log(f"Could not become a speaker in the stage: {e}", module_name=MODULE, success=False)

        if guild.voice_client is not None:
            log(f"Joined voice: {voice_report(guild, guild.voice_client)}", module_name=MODULE)

        session = self.sessions.get(guild.id)
        if session is None:
            session = Session(guild_id=guild.id, text_channel_id=text_channel_id)
            session.queue = asyncio.Queue(maxsize=get_settings(cfg)["max-queue"])
            self.sessions[guild.id] = session
            session.task = asyncio.create_task(self._worker(session))
        else:
            session.text_channel_id = text_channel_id

        info = {"voice": target.name, "text": text_mention or f"<#{text_channel_id}>"}
        return ("join-moved" if moved else "join-ok"), info

    async def leave(self, guild: discord.Guild) -> bool:
        had = guild.id in self.sessions or guild.voice_client is not None
        await self._cleanup(guild.id)
        if guild.voice_client is not None:
            try:
                await guild.voice_client.disconnect(force=True)
            except Exception as e:
                log(f"Disconnect error: {e}", module_name=MODULE, success=False)
        return had

    async def _cleanup(self, guild_id: int) -> None:
        session = self.sessions.pop(guild_id, None)
        if session and session.prefetch is not None:
            _discard(session.prefetch[2])
            session.prefetch = None
        if session and session.task and not session.task.done():
            session.task.cancel()
            try:
                await session.task
            except (asyncio.CancelledError, Exception):
                pass

    # ---- queue
    def skip(self, guild: discord.Guild) -> bool:
        vc = guild.voice_client
        if vc is not None and vc.is_playing():
            session = self.sessions.get(guild.id)
            if session is not None:
                session.skip_gen += 1  # drop the remaining chunks of this message too
            vc.stop()
            return True
        return False

    def enqueue(self, session: Session, item: QueueItem) -> bool:
        try:
            session.queue.put_nowait(item)
            return True
        except asyncio.QueueFull:
            log("Queue full, dropping a message.", module_name=MODULE, success=False)
            return False

    # ---- playback
    async def _worker(self, session: Session) -> None:
        guild = self.bot.get_guild(session.guild_id)
        while True:
            item: QueueItem = await session.queue.get()
            first = None  # this item's first chunk, if it was already being synthesized
            if session.prefetch is not None:
                if session.prefetch[0] is item:
                    first = session.prefetch
                else:
                    _discard(session.prefetch[2])
                session.prefetch = None
            try:
                if guild is None or guild.voice_client is None:
                    _discard(first[2] if first else None)
                    continue
                await self._speak(session, guild, item, first)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log(f"Could not read a message aloud: {e}", module_name=MODULE, success=False)

    def _prefetch_next(self, session: Session, settings: dict) -> None:
        """Start synthesizing the first chunk of the next queued message, so it is ready the moment the
        current one ends."""
        if session.prefetch is not None:
            return
        nxt = _peek(session.queue)
        if nxt is None:
            return
        chunks = splice(nxt.text, settings["chunk-chars"], settings["chunk-first-chars"])
        if chunks:
            task = asyncio.create_task(synthesize(chunks[0], nxt.voice_id, settings["synth-timeout"]))
            session.prefetch = (nxt, chunks[0], task)

    async def _speak(
        self, session: Session, guild: discord.Guild, item: QueueItem, first: tuple | None = None
    ) -> None:
        """Splice the message at its punctuation and play it chunk by chunk. The next chunk is
        synthesized while the current one is playing, so there are no long gaps. While the last chunk plays,
        the next queued message's first chunk is synthesized too (`first` is that head start, if any)."""
        settings = get_settings(self.get_cfg())
        chunks = splice(item.text, settings["chunk-chars"], settings["chunk-first-chars"])
        if not chunks:
            _discard(first[2] if first else None)
            return
        timeout = settings["synth-timeout"]
        gen = session.skip_gen

        def start(index: int) -> asyncio.Task:
            return asyncio.create_task(synthesize(chunks[index], item.voice_id, timeout))

        if first is not None and first[1] == chunks[0]:
            pending: asyncio.Task | None = first[2]
        else:
            _discard(first[2] if first else None)
            pending = start(0)
        try:
            for index in range(len(chunks)):
                try:
                    path = await pending
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    log(f"Could not synthesize part {index + 1}/{len(chunks)}: {e}", module_name=MODULE, success=False)
                    path = None
                if index + 1 < len(chunks):
                    pending = start(index + 1)
                else:
                    pending = None
                    self._prefetch_next(session, settings)  # the last chunk is about to play
                if path is not None:
                    try:
                        if session.skip_gen == gen and guild.voice_client is not None:
                            await self._play(guild.voice_client, path)
                    finally:
                        _remove(path)
                if session.skip_gen != gen or guild.voice_client is None:
                    break
        finally:
            _discard(pending)

    @staticmethod
    async def _play(vc: discord.VoiceClient, path: str) -> None:
        if not vc.is_connected():
            return
        loop = asyncio.get_running_loop()
        done = loop.create_future()

        def after(err: Exception | None) -> None:
            def finish():
                if not done.done():
                    done.set_result(err)

            loop.call_soon_threadsafe(finish)

        await ensure_dave_ready(vc)
        if not vc.is_connected():
            return
        source = MeteredPCMAudio(
            path,
            executable=ffmpeg_executable() or "ffmpeg",
            options="-loglevel error",  # hide ffmpeg's harmless info lines, keep real errors
        )
        started = time.monotonic()
        vc.play(source, after=after)
        err = await done
        elapsed = time.monotonic() - started
        if err:
            log(f"Playback error: {err}", module_name=MODULE, success=False)
        elif elapsed < 0.4:
            log(f"Playback ended after {elapsed:.2f}s, which is too short to be heard "
                f"(connected={vc.is_connected()}).", module_name=MODULE, success=False)
        elif source.peak < 200:
            log(f"Played {elapsed:.1f}s but the audio itself is silent (peak={source.peak}). "
                f"The voice clip is the problem, not Discord.", module_name=MODULE, success=False)
        else:
            log(f"Played {elapsed:.1f}s of audio (peak={source.peak}/32767).", module_name=MODULE, success=True)

    # ---- message -> speech pipeline
    #   1. eligible()   which session, if any, should hear this message (chat_eligible() is the same check for
    #                   channels in /vcchatmodetoggle mode, where the Ask cog answers the message instead)
    #   2. prepare()    clean the text, add the speaker's name, pick the voice
    #      (then _maybe_translate(): non-English text is translated to English with DeepL)
    #   3. enqueue()    per-server queue (dropped when full)
    #   4. _worker()    synthesize with edge-tts, then play through the voice client
    def vc_enabled_for(self, guild: discord.Guild, user_id: int) -> bool:
        """Does Yu read/greet this person? Their own /user-settings vctoggle wins; if they never set it, the
        server's /server-settings vctoggle decides (on by default)."""
        server = self.server_settings.get(guild.id)["vc_enabled"] if self.server_settings is not None else True
        if self.user_settings is None:
            return server
        return self.user_settings.is_enabled(user_id, default=server)

    def sayname_for(self, guild: discord.Guild, user_id: int) -> bool:
        """Does Yu say this person's name before their messages? Their own /user-settings vcsayname wins; if they
        never set it, the server's /server-settings vcsayname decides (on by default)."""
        server = self.server_settings.get(guild.id)["vc_sayname"] if self.server_settings is not None else True
        if self.user_settings is None:
            return server
        return self.user_settings.is_sayname(user_id, default=server)

    def chat_mode_on(self, guild_id: int, channel_id: int) -> bool:
        """Is /vcchatmodetoggle on for this text channel?"""
        return self.server_settings is not None and self.server_settings.is_chat_mode_channel(guild_id, channel_id)

    def eligible(self, message: discord.Message, prefix: str) -> Session | None:
        """The session that should read this message aloud (None in chat mode channels: Yu answers those)."""
        session = self._listening(message, prefix)
        if session is None or self.chat_mode_on(message.guild.id, message.channel.id):
            return None
        return session

    def chat_eligible(self, message: discord.Message, prefix: str) -> Session | None:
        """The session whose conversation this message belongs to, only in chat mode channels."""
        session = self._listening(message, prefix)
        if session is None or not self.chat_mode_on(message.guild.id, message.channel.id):
            return None
        return session

    def _listening(self, message: discord.Message, prefix: str) -> Session | None:
        guild = message.guild
        if message.author.bot or guild is None:
            return None
        session = self.sessions.get(guild.id)
        if session is None or message.channel.id != session.text_channel_id:
            return None
        if message.content.startswith(prefix):
            return None
        if not self.vc_enabled_for(guild, message.author.id):
            return None  # switched off by /user-settings vctoggle (the person's own choice beats the server's)

        vc = guild.voice_client
        author_voice = getattr(message.author, "voice", None)
        # Only read people who are actually listening in Yu's voice channel
        if vc is None or author_voice is None or author_voice.channel != vc.channel:
            return None
        return session

    def prepare(self, message: discord.Message, session: Session, now: float | None = None) -> QueueItem | None:
        cfg = self.get_cfg()
        settings = get_settings(cfg)
        text = clean_for_speech(
            message.clean_content,
            pronunciations=cfg.get("pronunciations"),
            max_chars=settings["max-chars"],
        )
        if not text and message.attachments:
            text = "sent an attachment"
        if not text:
            return None

        now = time.monotonic() if now is None else now
        lead = ""
        if self.sayname_for(message.guild, message.author.id) and should_announce(
            session, message.author.id, now, settings["announce-gap"]
        ):
            lead = f"{speaker_name(message.author)} says. "
        session.last_speaker = message.author.id
        session.last_spoken_at = now

        # Voice precedence: the person's own /user-settings vcsetvoice, then the server's /server-settings vcsetvoice
        user_key = self.user_settings.get_voice(message.author.id) if self.user_settings is not None else None
        server_key = None
        if self.server_settings is not None and message.guild is not None:
            server_key = self.server_settings.get(message.guild.id)["voice"]
        voice_key = resolve_voice_key(cfg, user_key, server_key)
        return QueueItem(text=lead + text, voice_id=voice_id_for(cfg, voice_key), lead=lead)

    def translator_for(self, guild_id: int | None) -> tuple[str, object | None]:
        """(api name, client) this server translates with: /server-settings translate-api."""
        api = "deepl"
        if self.server_settings is not None and guild_id is not None:
            api = self.server_settings.get(guild_id)["translate_api"]
        return api, (self.google_translator if api == "google" else self.translator)

    async def _maybe_translate(self, item: QueueItem, guild_id: int | None = None) -> QueueItem:
        """Replace a non-English message body with its English translation (DeepL or Google, per
        server). On any problem the original text is read as before."""
        settings = get_settings(self.get_cfg())
        if self.server_settings is not None and guild_id is not None:
            if not self.server_settings.get(guild_id)["vc_translate"]:
                return item  # /server-settings vctranslatetoggle off
        api, tr = self.translator_for(guild_id)
        if not settings["translate"] or tr is None or not tr.configured:
            return item
        if time.monotonic() < self._translate_paused_until.get(api, 0.0):
            return item
        body = item.text[len(item.lead):]
        if not needs_translation(body):
            return item
        try:
            result = await asyncio.wait_for(tr.translate(body, "EN-US"), settings["translate-timeout"])
        except asyncio.CancelledError:
            raise
        except Exception as e:
            if getattr(e, "kind", "") in ("quota", "auth", "not_configured"):
                self._translate_paused_until[api] = time.monotonic() + 600  # don't hammer a dead key
                log(f"{api} translation paused for 10 minutes ({e}).", module_name=MODULE, success=False)
            else:
                log(f"Could not translate a message with {api} ({type(e).__name__}: {e}).", module_name=MODULE, success=False)
            return item
        if result.source and result.source != "EN" and result.text.strip():
            item.text = item.lead + truncate(result.text.strip(), settings["max-chars"])
        return item

    async def handle_message(self, message: discord.Message, prefix: str) -> None:
        session = self.eligible(message, prefix)
        if session is None:
            return
        item = self.prepare(message, session)
        if item is None:
            return
        async with session.order_lock:  # FIFO: a slow translation can't let later messages jump ahead
            item = await self._maybe_translate(item, message.guild.id if message.guild else None)
            item = self._romanize_item(item)
            if item is not None:
                self.enqueue(session, item)

    async def say_text(self, guild: discord.Guild, member, text: str, use_member_voice: bool = True) -> bool | None:
        """Have Yu say `text` in her voice channel (used by /vcask), in the voice `member` has picked.
        With use_member_voice=False (chat mode) she keeps one steady voice: the server's, then the default.

        Returns True when it was queued, False when the queue is full, None when there is nothing
        to say or Yu has no voice session here."""
        session = self.sessions.get(guild.id)
        if session is None:
            return None
        cfg = self.get_cfg()
        body = clean_for_speech(
            text, pronunciations=cfg.get("pronunciations"), max_chars=get_settings(cfg)["max-chars"]
        )
        user_key = None
        if use_member_voice and self.user_settings is not None:
            user_key = self.user_settings.get_voice(member.id)
        server_key = self.server_settings.get(guild.id)["voice"] if self.server_settings is not None else None
        voice_key = resolve_voice_key(cfg, user_key, server_key)
        item = QueueItem(text=body, voice_id=voice_id_for(cfg, voice_key))
        async with session.order_lock:  # same FIFO as read-aloud messages
            item = self._romanize_item(item) if body else None
            if item is None:
                return None
            return self.enqueue(session, item)

    def _romanize_item(self, item: QueueItem) -> QueueItem | None:
        """Whatever is still in a foreign script (translation off or failed) is spelled out in
        Latin letters so the voice reads it instead of saying "Japanese letter"."""
        body = item.text[len(item.lead):]
        if not has_non_latin(body):
            return item
        body = truncate(romanize(body), get_settings(self.get_cfg())["max-chars"])
        if not any(ch.isalnum() for ch in body):
            return None
        item.text = item.lead + body
        return item

    @staticmethod
    def humans_in(channel) -> list:
        return [m for m in getattr(channel, "members", []) if not m.bot]

    async def handle_voice_state(
        self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState
    ) -> list[tuple[str, int, dict]]:
        """Keeps Yu's voice presence in step with who is in the room.

        - Yu leaves immediately when no people are left with her.
        - With vcgreettoggle on, Yu welcomes people who join her room and says goodbye when they leave
          (no goodbye to the last person: Yu clocks out as soon as the room is empty).
        - With auto-join on for that voice channel, Yu joins when someone enters it and she isn't in one, and
          reads that voice channel's own text chat.

        Returns [(response key, text_channel_id, format values)] for the cog to post.
        """
        guild = member.guild
        events: list[tuple[str, int, dict]] = []

        if member.id == self.bot.user.id:
            session = self.sessions.get(guild.id)
            if session is None:
                return events
            if after.channel is None:  # disconnected or kicked
                await self._cleanup(guild.id)
            elif not self.humans_in(after.channel):  # moved into an empty room
                await self.leave(guild)
                events.append(("auto-left", session.text_channel_id, {}))
            return events

        if member.bot:
            return events

        # Someone left Yu's room: clock out if nobody is left
        session = self.sessions.get(guild.id)
        vc = guild.voice_client
        if (
            session is not None
            and vc is not None
            and vc.channel is not None
            and before.channel == vc.channel
            and not self.humans_in(vc.channel)
        ):
            await self.leave(guild)
            events.append(("auto-left", session.text_channel_id, {}))

        # Someone left Yu's room and people are still there: say goodbye
        session = self.sessions.get(guild.id)
        vc = guild.voice_client
        if (
            session is not None
            and vc is not None
            and vc.channel is not None
            and before.channel == vc.channel
            and after.channel != vc.channel
        ):
            self._greet(guild, session, member, "greet-leave")

        # Someone entered a voice channel: maybe follow them in
        if after.channel is not None and after.channel != before.channel:
            joined = await self._maybe_auto_join(guild, after.channel)
            if joined:
                events.append(joined)

        # Someone is now in Yu's room (they walked in, or Yu just auto-joined for them): welcome them
        session = self.sessions.get(guild.id)
        vc = guild.voice_client
        if (
            session is not None
            and vc is not None
            and vc.channel is not None
            and after.channel == vc.channel
            and before.channel != vc.channel
        ):
            self._greet(guild, session, member, "greet-join")
        return events

    def _greet(self, guild: discord.Guild, session: Session, member, key: str) -> None:
        """Speak "Welcome, <name>!" / "Goodbye, <name>!" when /server-settings vcgreettoggle is on."""
        if self.server_settings is None:
            return
        conf = self.server_settings.get(guild.id)
        if not conf["vc_greet"]:
            return
        if not self.vc_enabled_for(guild, member.id):
            return  # Yu doesn't read this person (/user-settings vctoggle)
        cfg = self.get_cfg()
        template = (cfg.get("responses") or {}).get(key) or DEFAULT_RESPONSES[key]
        try:
            text = template.format(name=speaker_name(member))
        except (KeyError, IndexError):
            text = DEFAULT_RESPONSES[key].format(name=speaker_name(member))
        user_key = self.user_settings.get_voice(member.id) if self.user_settings is not None else None
        voice_key = resolve_voice_key(cfg, user_key, conf["voice"])
        self.enqueue(session, QueueItem(text=text, voice_id=voice_id_for(cfg, voice_key)))

    async def _maybe_auto_join(self, guild: discord.Guild, channel) -> tuple[str, int, dict] | None:
        if self.server_settings is None:
            return None
        # Only voice channels on the server's auto-join list (toggled or added with /server-settings auto-join)
        if not self.server_settings.is_auto_join_channel(guild.id, channel.id):
            return None
        if not isinstance(channel, discord.VoiceChannel) or channel == guild.afk_channel:
            return None
        # Yu reads the voice channel's own text chat, so the text channel is the room itself
        text = channel

        lock = self._join_locks.setdefault(guild.id, asyncio.Lock())
        async with lock:
            if guild.voice_client is not None:  # already somewhere in this server
                return None
            key, info = await self.connect(guild, channel, text.id, text.mention)
            if key != "join-ok":
                log(f"Auto-join skipped in {guild.name}: {key}", module_name=MODULE, success=False)
                return None
            if not self.humans_in(channel):  # they left again while Yu was connecting
                await self.leave(guild)
                return None
        return "auto-join-ok", channel.id, info

    async def auto_join_on_start(self) -> None:
        """After a restart, rejoin the busiest auto-join voice channel that has people in it."""
        if self.server_settings is None:
            return
        for guild_id in self.server_settings.auto_join_guilds():
            guild = self.bot.get_guild(guild_id)
            if guild is None or guild.voice_client is not None:
                continue
            listed = set(self.server_settings.auto_join_channel_ids(guild_id))
            rooms = [
                c for c in guild.voice_channels
                if c.id in listed and c != guild.afk_channel and self.humans_in(c)
            ]
            if rooms:
                busiest = max(rooms, key=lambda c: len(self.humans_in(c)))
                await self._maybe_auto_join(guild, busiest)

    async def shutdown(self) -> None:
        for guild_id in list(self.sessions):
            await self._cleanup(guild_id)

import asyncio
import time

import discord
from discord.ext import commands

from config.bot_defaults import DEFAULT_PREFIX
from datastore.static_data import config
from services.commands import ask_service as asks
from services.commands import tts_service as ts
from utils.channel_memory import ChannelMemory, Turn

MODULE = "ASK"


def _cfg() -> dict:
    # Read at call time so config reloads (Supabase / dashboard) take effect
    return config.get("ask") or {}


def _say(key: str, **fmt) -> str:
    text = (_cfg().get("responses") or {}).get(key) or asks.DEFAULT_RESPONSES.get(key) or key
    try:
        return text.format(**fmt)
    except (KeyError, IndexError):
        return text


def _say_tts(key: str, **fmt) -> str:
    """Join/leave messages live in the TTS config, so /vcask answers with those."""
    cfg = config.get("tts") or {}
    text = (cfg.get("responses") or {}).get(key) or ts.DEFAULT_RESPONSES.get(key) or key
    try:
        return text.format(**fmt)
    except (KeyError, IndexError):
        return text


def _desc(name: str, fallback: str) -> str:
    try:
        return config["utility"]["commands"][name]["desc"]
    except (KeyError, TypeError):
        return fallback


ERROR_KEYS = {
    "not_configured": "ask-not-configured",
    "rate_limit": "ask-rate-limit",
    "quota": "ask-quota",
    "auth": "ask-auth",
    "blocked": "ask-blocked",
    "empty": "ask-empty-answer",
    "failed": "ask-failed",
}


class Ask(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.gemini = asks.GeminiClient()
        self._last_ask: dict[int, float] = {}  # user id -> monotonic time of their last question
        # Chat mode (/vcchatmodetoggle): short-term memory per channel, plus pacing so Gemini isn't flooded
        self.memory = ChannelMemory()
        self._last_chat: dict[int, float] = {}  # user id -> monotonic time Yu last answered them in chat mode
        self._chat_locks: dict[int, asyncio.Lock] = {}  # channel id -> one Gemini call at a time
        self._chat_seq: dict[int, int] = {}  # channel id -> number of the newest message waiting for an answer
        self._chat_paused_until = 0.0  # monotonic time; set when the key or quota is dead

    async def cog_unload(self):
        await self.gemini.close()

    # ---- shared checks
    def _precheck(self, user_id: int, question: str | None) -> tuple[str | None, str]:
        """(error message, cleaned question). A message means: stop here and show it (privately)."""
        settings = asks.get_settings(_cfg())
        question = " ".join((question or "").split())
        if not question:
            return _say("ask-empty"), question
        if len(question) > settings["max-question-chars"]:
            return _say("ask-too-long", limit=settings["max-question-chars"]), question
        if not self.gemini.configured:
            return _say("ask-not-configured"), question
        wait = settings["cooldown"] - (time.monotonic() - self._last_ask.get(user_id, -1e9))
        if wait > 0:
            return _say("ask-cooldown", seconds=int(wait) + 1), question
        return None, question

    async def _gemini_answer(self, user_id: int, question: str, *, voice: bool) -> str:
        """Ask Gemini. Raises AskError."""
        cfg = _cfg()
        settings = asks.get_settings(cfg)
        self._last_ask[user_id] = time.monotonic()
        try:
            return await self.gemini.ask(
                asks.build_question_prompt(question),
                system=asks.build_system_prompt(cfg, voice),
                max_output_tokens=settings["voice-max-tokens" if voice else "text-max-tokens"],
                temperature=settings["temperature"],
                timeout=settings["timeout"],
                model=settings["model"] if settings["model"] != asks.DEFAULT_MODEL else None,
            )
        except asks.AskError as e:
            asks.log_error(e)
            if e.code in ("not_configured", "auth"):
                self._last_ask.pop(user_id, None)  # nothing was asked, so no cooldown
            raise

    async def _gemini_chat(self, turns: list[Turn]) -> str:
        """Ask Gemini to answer (or stay silent on) the newest message of a channel's remembered conversation."""
        cfg = _cfg()
        settings = asks.get_settings(cfg)
        return await self.gemini.ask(
            asks.build_chat_prompt(turns),
            system=asks.build_system_prompt(cfg, chat=True),
            max_output_tokens=settings["chat-max-tokens"],
            temperature=settings["temperature"],
            timeout=settings["timeout"],
            model=settings["model"] if settings["model"] != asks.DEFAULT_MODEL else None,
        )

    @staticmethod
    def _quote(question: str) -> str:
        return "> " + (question if len(question) <= 200 else question[:199].rstrip() + "…")

    # ---- /ask
    @commands.hybrid_command(
        name="ask",
        description=_desc("ask", "Ask Yu a question and she answers in this channel."),
    )
    @discord.app_commands.describe(question="What do you want to ask Yu?")
    async def ask(self, ctx: commands.Context, *, question: str = ""):
        error, question = self._precheck(ctx.author.id, question)
        if error:
            await ctx.send(error, ephemeral=True)
            return
        await ctx.defer()
        try:
            answer = await self._gemini_answer(ctx.author.id, question, voice=False)
        except asks.AskError as e:
            await ctx.send(_say(ERROR_KEYS.get(e.code, "ask-failed")), ephemeral=True)
            return
        answer = ts.truncate(answer, asks.get_settings(_cfg())["max-answer-chars"])
        await ctx.send(
            f"{self._quote(question)}\n{answer}",
            allowed_mentions=discord.AllowedMentions.none(),
        )

    # ---- /vcask
    @commands.hybrid_command(
        name="vcask",
        description=_desc("vcask", "Ask Yu a question and she answers out loud in your voice channel."),
    )
    @discord.app_commands.describe(question="What do you want to ask Yu?")
    @commands.guild_only()
    async def vcask(self, ctx: commands.Context, *, question: str = ""):
        tts_cog = self.bot.get_cog("TTS")
        if tts_cog is None:
            await ctx.send(_say("ask-failed"), ephemeral=True)
            return
        manager = tts_cog.manager

        error, question = self._precheck(ctx.author.id, question)
        if error:
            await ctx.send(error, ephemeral=True)
            return
        voice = getattr(ctx.author, "voice", None)
        if voice is None or voice.channel is None:
            await ctx.send(_say_tts("not-in-voice"), ephemeral=True)
            return

        await ctx.defer()
        guild = ctx.guild
        vc = guild.voice_client
        if vc is None or vc.channel is None:
            # Yu isn't in a voice channel yet: join the asker's, reading this text channel like /vcjoin
            key, info = await manager.join(ctx)
            if key != "join-ok":
                await ctx.send(_say_tts(key, **info), allowed_mentions=discord.AllowedMentions.none())
                return
        elif vc.channel != voice.channel:
            await ctx.send(_say("vcask-wrong-channel"))
            return

        try:
            answer = await self._gemini_answer(ctx.author.id, question, voice=True)
        except asks.AskError as e:
            await ctx.send(_say(ERROR_KEYS.get(e.code, "ask-failed")))
            return

        queued = await manager.say_text(guild, ctx.author, answer)
        shown = ts.truncate(answer, asks.get_settings(_cfg())["max-answer-chars"])
        note = ""
        if queued is False:
            note = _say("vcask-queue-full") + "\n"
        elif queued is None:  # Yu left while she was thinking
            note = _say("vcask-no-session") + "\n"
        await ctx.send(
            f"{self._quote(question)}\n{note}{shown}",
            allowed_mentions=discord.AllowedMentions.none(),
        )

    # ---- chat mode: /vcchatmodetoggle channels. Yu doesn't read these messages aloud; she answers them.
    #   1. remember the message in the channel's short-term memory (even when she won't answer it)
    #   2. answer unless the person is on cooldown or a newer message is already waiting
    #   3. ask Gemini with the remembered conversation; speak the reply (and type it), and remember it too
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        tts_cog = self.bot.get_cog("TTS")
        if tts_cog is None or tts_cog.manager.chat_eligible(message, DEFAULT_PREFIX) is None:
            return
        await self._chat(tts_cog.manager, message)

    async def _chat(self, manager, message: discord.Message) -> None:
        settings = asks.get_settings(_cfg())
        self.memory.configure(
            settings["chat-memory-turns"], settings["chat-memory-minutes"] * 60, settings["chat-memory-message-chars"]
        )
        text = asks.clean_chat_text(message.clean_content, bool(message.attachments))
        if not text:
            return
        channel_id, author_id = message.channel.id, message.author.id
        self.memory.add(channel_id, "user", asks.chat_name(message.author), text)

        now = time.monotonic()
        if (
            not self.gemini.configured
            or now < self._chat_paused_until
            or now - self._last_chat.get(author_id, -1e9) < settings["chat-cooldown"]
        ):
            return  # remembered, but not answered
        self._last_chat[author_id] = now
        seq = self._chat_seq[channel_id] = self._chat_seq.get(channel_id, 0) + 1

        reply = ""
        queued = None
        async with self._chat_locks.setdefault(channel_id, asyncio.Lock()):
            if self._chat_seq.get(channel_id) != seq:
                return  # a newer message is waiting; its answer will see this one in the memory
            turns = self.memory.recent(channel_id)
            if not turns:
                return
            try:
                reply = asks.clean_chat_answer(await self._gemini_chat(turns))
            except asks.AskError as e:
                asks.log_error(e)
                if e.code in ("quota", "auth", "not_configured"):
                    self._chat_paused_until = time.monotonic() + 600  # don't hammer a dead key
                return
            if not reply:
                return  # Yu chose to stay quiet
            self.memory.add(channel_id, "model", "Yu", reply)
            queued = await manager.say_text(message.guild, message.author, reply, use_member_voice=False)

        if settings["chat-post-text"] and queued is not None:
            try:
                await message.reply(
                    ts.truncate(reply, settings["max-answer-chars"]),
                    mention_author=False,
                    allowed_mentions=discord.AllowedMentions.none(),
                )
            except discord.HTTPException:
                pass  # the message was deleted or she can't type here; she still spoke


async def setup(bot):
    await bot.add_cog(Ask(bot))

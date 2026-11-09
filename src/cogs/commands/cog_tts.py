import asyncio
from typing import Literal, Optional

import discord
from discord import app_commands
from discord.ext import commands

from config.bot_defaults import DEFAULT_PREFIX
from config.directories import SERVER_SETTINGS_FILE, TTS_USER_SETTINGS_FILE
from datastore.static_data import config
from services.commands import translate_service
from services.commands import tts_service as ts
from services.commands.server_settings_service import ServerSettings, UserSettings
from utils import kokoro_engine
from utils.console_logger import log

MODULE = "TTS"


def _cfg() -> dict:
    # Read at call time so config reloads (Supabase / dashboard) take effect
    return config.get("tts") or {}


def _say(key: str, **fmt) -> str:
    text = (_cfg().get("responses") or {}).get(key) or ts.DEFAULT_RESPONSES.get(key) or key
    try:
        return text.format(**fmt)
    except (KeyError, IndexError):
        return text


def _desc(name: str, fallback: str) -> str:
    try:
        return config["utility"]["commands"][name]["desc"]
    except (KeyError, TypeError):
        return fallback


API_LABELS = {"deepl": "DeepL", "google": "Google Translate"}

# Discord allows at most 25 choices
VOICE_CHOICES = [
    app_commands.Choice(name=v.get("label", k), value=k)
    for k, v in list(ts.get_voices(_cfg()).items())[:25]
]


class TTS(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.server_settings = ServerSettings(SERVER_SETTINGS_FILE)
        self.user_settings = UserSettings(TTS_USER_SETTINGS_FILE)
        self.translator = translate_service.Translator()  # reads DEEPL_API_KEY; unset = no translating
        self.google_translator = translate_service.GoogleTranslator()  # reads GOOGLE_TRANSLATE_API_KEY
        self.manager = ts.TTSManager(
            bot, _cfg, self.server_settings, self.user_settings, self.translator, self.google_translator
        )
        self._start_task: asyncio.Task | None = None
        self._preload_task: asyncio.Task | None = None

    async def _auto_join_after_ready(self):
        await self.bot.wait_until_ready()
        try:
            await self.manager.auto_join_on_start()
        except Exception as e:
            log(f"Startup auto-join failed: {e}", module_name=MODULE, success=False)

    async def cog_load(self):
        await asyncio.to_thread(self.server_settings.refresh)
        await asyncio.to_thread(self.user_settings.refresh)
        self._start_task = asyncio.create_task(self._auto_join_after_ready())
        if ts.voice_id_for(_cfg(), None).startswith(ts.KOKORO_PREFIX):
            # Load the model in the background so the first message isn't slow
            self._preload_task = asyncio.create_task(asyncio.to_thread(kokoro_engine.preload))
        log(
            f"Voice ready: ffmpeg={'yes' if ts.ffmpeg_executable() else 'NO'}, "
            f"opus={'yes' if ts.ensure_opus() else 'NO'}",
            module_name=MODULE,
            success=bool(ts.ffmpeg_executable()) and ts.ensure_opus(),
        )
        log(f"Voice libraries: {ts.voice_versions()}", module_name=MODULE)

    async def cog_unload(self):
        if self._start_task:
            self._start_task.cancel()
        await self.manager.shutdown()
        await self.translator.close()
        await self.google_translator.close()

    # ---- /vcjoin, /vcleave and /leave
    @commands.hybrid_command(
        name="vcjoin",
        description=_desc("vcjoin", "Yu joins your voice channel and reads messages from this channel."),
    )
    @commands.guild_only()
    async def vcjoin(self, ctx: commands.Context):
        await ctx.defer()
        key, info = await self.manager.join(ctx)
        await ctx.send(_say(key, **info), allowed_mentions=discord.AllowedMentions.none())

    async def _leave(self, ctx: commands.Context):
        had = await self.manager.leave(ctx.guild)
        await ctx.send(_say("leave-ok" if had else "no-session"))

    @commands.hybrid_command(
        name="vcleave",
        description=_desc("vcleave", "Yu leaves the voice channel and stops reading."),
    )
    @commands.guild_only()
    async def vcleave(self, ctx: commands.Context):
        await self._leave(ctx)

    @commands.hybrid_command(name="leave", description=_desc("leave", "Yu leaves the voice channel and stops reading."))
    @commands.guild_only()
    async def leave_voice(self, ctx: commands.Context):
        await self._leave(ctx)

    # ---- /vcchatmodetoggle: in this text channel Yu joins the conversation instead of reading it aloud
    @commands.hybrid_command(
        name="vcchatmodetoggle",
        description=_desc("vcchatmodetoggle", "Yu joins the conversation here instead of reading messages aloud."),
    )
    @app_commands.describe(state="on or off (leave empty to flip it for this channel)")
    @app_commands.default_permissions(manage_guild=True)
    @commands.guild_only()
    async def vcchatmodetoggle(self, ctx: commands.Context, state: Optional[Literal["on", "off"]] = None):
        if not ctx.author.guild_permissions.manage_guild:
            await ctx.send(_say("auto-join-no-permission"), ephemeral=True)
            return
        enabled = (
            not self.server_settings.is_chat_mode_channel(ctx.guild.id, ctx.channel.id)
            if state is None
            else state == "on"
        )
        self.server_settings.set_chat_mode_channel(ctx.guild.id, ctx.channel.id, enabled)
        ask = self.bot.get_cog("Ask")
        if ask is not None:
            ask.memory.clear(ctx.channel.id)  # each switch starts from a clean slate
        message = _say("vc-chatmode-on" if enabled else "vc-chatmode-off", channel=ctx.channel.mention)
        if enabled and (ask is None or not ask.gemini.configured):
            message += "\n" + _say("vc-chatmode-missing-key")
        await ctx.send(message, allowed_mentions=discord.AllowedMentions.none())

    # ---- /user-settings vctoggle on|off|reset: each person's own switch (beats the server's)
    async def _set_user_toggle(self, ctx: commands.Context, state: str):
        if state == "reset":
            self.user_settings.set_enabled(ctx.author.id, None)
            await ctx.send(_say("vc-toggle-reset"), ephemeral=True)
            return
        enabled = state == "on"
        self.user_settings.set_enabled(ctx.author.id, enabled)
        await ctx.send(_say("vc-toggle-on" if enabled else "vc-toggle-off"), ephemeral=True)

    # ---- /user-settings vcsayname on|off|reset: say the speaker's name before their messages (user beats server)
    async def _set_user_sayname(self, ctx: commands.Context, state: str):
        if state == "reset":
            self.user_settings.set_sayname(ctx.author.id, None)
            await ctx.send(_say("vc-sayname-reset"), ephemeral=True)
            return
        on = state == "on"
        self.user_settings.set_sayname(ctx.author.id, on)
        await ctx.send(_say("vc-sayname-on" if on else "vc-sayname-off"), ephemeral=True)

    # ---- voices
    async def _set_user_voice(self, ctx: commands.Context, voice: Optional[str]):
        voices = ts.get_voices(_cfg())
        if voice is None:
            self.user_settings.set_voice(ctx.author.id, None)
            await ctx.send(_say("voice-reset"), ephemeral=True)
            return
        if voice not in voices:
            await ctx.send(_say("unknown-voice"), ephemeral=True)
            return
        self.user_settings.set_voice(ctx.author.id, voice)
        await ctx.send(_say("voice-set", voice=voices[voice].get("label", voice)), ephemeral=True)

    # ---- /user-settings: personal toggles and voice (they beat the server's settings)
    @commands.hybrid_group(
        name="user-settings",
        description=_desc("user-settings", "Change how Yu treats you."),
        invoke_without_command=True,
    )
    async def user_settings_group(self, ctx: commands.Context):
        await ctx.send(_say("user-settings-usage"), ephemeral=True)

    @user_settings_group.command(
        name="vctoggle",
        description="Turn Yu reading your messages on or off. It wins over the server's setting.",
    )
    @app_commands.describe(state="on: Yu reads you. off: she stays quiet for you. reset: follow the server's setting.")
    async def user_vctoggle(self, ctx: commands.Context, state: Literal["on", "off", "reset"]):
        await self._set_user_toggle(ctx, state)

    @user_settings_group.command(
        name="vcsayname",
        description="Whether Yu says your name before your messages. It wins over the server's setting.",
    )
    @app_commands.describe(state="on: Yu says your name first. off: she just reads the message. reset: follow the server's setting.")
    async def user_vcsayname(self, ctx: commands.Context, state: Literal["on", "off", "reset"]):
        await self._set_user_sayname(ctx, state)

    @user_settings_group.command(
        name="vcsetvoice",
        description="Your own voice. It wins over the server's voice.",
    )
    @app_commands.describe(voice="The voice to read your messages with (leave empty to use the server's voice)")
    @app_commands.choices(voice=VOICE_CHOICES)
    async def user_setvoice(self, ctx: commands.Context, voice: Optional[str] = None):
        await self._set_user_voice(ctx, voice)

    # ---- /server-settings
    @commands.hybrid_group(
        name="server-settings",
        description=_desc("server-settings", "Change how Yu behaves in this server."),
        invoke_without_command=True,
    )
    @commands.guild_only()
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    async def server_settings_group(self, ctx: commands.Context):
        await ctx.send(_say("server-settings-usage"), ephemeral=True)

    # ---- /server-settings auto-join toggle | add | remove | list
    # Auto-join never covers the whole server: only voice channels toggled on (while you're in
    # them) or added by name.
    @server_settings_group.group(
        name="auto-join",
        description="Choose which voice channels Yu joins by herself when someone enters.",
        invoke_without_command=True,
    )
    @commands.guild_only()
    async def auto_join_group(self, ctx: commands.Context):
        await ctx.send(_say("auto-join-usage"), ephemeral=True)

    @auto_join_group.command(
        name="toggle",
        description="Turn auto-join on or off for the voice channel you're in right now.",
    )
    @app_commands.describe(enabled="True = auto-join this voice channel, False = stop (leave empty to flip it)")
    @commands.guild_only()
    async def auto_join_toggle(self, ctx: commands.Context, enabled: Optional[bool] = None):
        if not ctx.author.guild_permissions.manage_guild:
            await ctx.send(_say("auto-join-no-permission"), ephemeral=True)
            return
        voice = getattr(ctx.author, "voice", None)
        channel = voice.channel if voice is not None else None
        if not isinstance(channel, discord.VoiceChannel):
            await ctx.send(_say("auto-join-need-channel"), ephemeral=True)
            return
        if enabled is None:
            enabled = not self.server_settings.is_auto_join_channel(ctx.guild.id, channel.id)
        await self._set_auto_join_channel(ctx, channel, enabled)

    @auto_join_group.command(
        name="add",
        description="Make Yu auto-join a specific voice channel.",
    )
    @app_commands.describe(channel="The voice channel Yu should auto-join")
    @commands.guild_only()
    async def auto_join_add(self, ctx: commands.Context, channel: discord.VoiceChannel):
        if not ctx.author.guild_permissions.manage_guild:
            await ctx.send(_say("auto-join-no-permission"), ephemeral=True)
            return
        await self._set_auto_join_channel(ctx, channel, True)

    @auto_join_group.command(
        name="remove",
        description="Stop Yu auto-joining a specific voice channel.",
    )
    @app_commands.describe(channel="The voice channel Yu should stop auto-joining")
    @commands.guild_only()
    async def auto_join_remove(self, ctx: commands.Context, channel: discord.VoiceChannel):
        if not ctx.author.guild_permissions.manage_guild:
            await ctx.send(_say("auto-join-no-permission"), ephemeral=True)
            return
        await self._set_auto_join_channel(ctx, channel, False)

    @auto_join_group.command(
        name="list",
        description="Show the voice channels Yu auto-joins.",
    )
    @commands.guild_only()
    async def auto_join_list(self, ctx: commands.Context):
        ids = self.server_settings.auto_join_channel_ids(ctx.guild.id)
        if not ids:
            await ctx.send(_say("auto-join-list-empty"), ephemeral=True)
            return
        await ctx.send(
            _say("auto-join-list", channels=", ".join(f"<#{cid}>" for cid in ids)),
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    async def _set_auto_join_channel(self, ctx: commands.Context, channel: discord.VoiceChannel, enabled: bool):
        changed = self.server_settings.set_auto_join_channel(ctx.guild.id, channel.id, enabled)
        if enabled:
            key = "auto-join-added" if changed else "auto-join-already"
        else:
            key = "auto-join-removed" if changed else "auto-join-not-listed"
        await ctx.send(_say(key, voice=channel.name))

    @server_settings_group.command(
        name="vctoggle",
        description="Turn Yu reading messages in voice channels on or off for this server.",
    )
    @app_commands.describe(state="on or off (leave empty to see the current setting). People can override it for themselves.")
    @commands.guild_only()
    async def server_vctoggle(self, ctx: commands.Context, state: Optional[Literal["on", "off"]] = None):
        conf = self.server_settings.get(ctx.guild.id)
        if state is None:
            await ctx.send(_say("server-vc-toggle-status-on" if conf["vc_enabled"] else "server-vc-toggle-status-off"), ephemeral=True)
            return
        if not ctx.author.guild_permissions.manage_guild:
            await ctx.send(_say("auto-join-no-permission"), ephemeral=True)
            return
        self.server_settings.set(ctx.guild.id, vc_enabled=state == "on")
        await ctx.send(_say("server-vc-toggle-on" if state == "on" else "server-vc-toggle-off"))

    @server_settings_group.command(
        name="vcsayname",
        description="Whether Yu says the speaker's name before reading their messages in this server.",
    )
    @app_commands.describe(state="on or off (leave empty to see the current setting). People can override it for themselves.")
    @commands.guild_only()
    async def server_vcsayname(self, ctx: commands.Context, state: Optional[Literal["on", "off"]] = None):
        conf = self.server_settings.get(ctx.guild.id)
        if state is None:
            await ctx.send(_say("server-vc-sayname-status-on" if conf["vc_sayname"] else "server-vc-sayname-status-off"), ephemeral=True)
            return
        if not ctx.author.guild_permissions.manage_guild:
            await ctx.send(_say("auto-join-no-permission"), ephemeral=True)
            return
        self.server_settings.set(ctx.guild.id, vc_sayname=state == "on")
        await ctx.send(_say("server-vc-sayname-on" if state == "on" else "server-vc-sayname-off"))

    @server_settings_group.command(
        name="vctranslatetoggle",
        description="Yu translates other languages to English before reading them out in this server.",
    )
    @app_commands.describe(state="on or off (leave empty to see the current setting)")
    @commands.guild_only()
    async def vc_translate_toggle(self, ctx: commands.Context, state: Optional[Literal["on", "off"]] = None):
        conf = self.server_settings.get(ctx.guild.id)
        if state is None:
            await ctx.send(_say("vc-translate-status-on" if conf["vc_translate"] else "vc-translate-status-off"), ephemeral=True)
            return
        if not ctx.author.guild_permissions.manage_guild:
            await ctx.send(_say("auto-join-no-permission"), ephemeral=True)
            return
        self.server_settings.set(ctx.guild.id, vc_translate=state == "on")
        await ctx.send(_say("vc-translate-on" if state == "on" else "vc-translate-off"))

    @server_settings_group.command(
        name="translate-api",
        description="Which service Yu uses to translate voice channel messages: DeepL or Google Translate.",
    )
    @app_commands.describe(api="deepl or google (leave empty to see the current one)")
    @app_commands.choices(api=[
        app_commands.Choice(name="DeepL", value="deepl"),
        app_commands.Choice(name="Google Translate", value="google"),
    ])
    @commands.guild_only()
    async def translate_api(self, ctx: commands.Context, api: Optional[Literal["deepl", "google"]] = None):
        conf = self.server_settings.get(ctx.guild.id)
        if api is None:
            await ctx.send(_say("translate-api-status", api=API_LABELS[conf["translate_api"]]), ephemeral=True)
            return
        if not ctx.author.guild_permissions.manage_guild:
            await ctx.send(_say("auto-join-no-permission"), ephemeral=True)
            return
        self.server_settings.set(ctx.guild.id, translate_api=api)
        message = _say("translate-api-set", api=API_LABELS[api])
        client = self.google_translator if api == "google" else self.translator
        if not client.configured:
            env = "GOOGLE_TRANSLATE_API_KEY" if api == "google" else "DEEPL_API_KEY"
            message += "\n" + _say("translate-api-missing-key", api=API_LABELS[api], env=env)
        await ctx.send(message)

    @server_settings_group.command(
        name="vcgreettoggle",
        description="Yu welcomes people who join her voice channel and says goodbye when they leave.",
    )
    @app_commands.describe(state="on or off (leave empty to see the current setting)")
    @commands.guild_only()
    async def vc_greet_toggle(self, ctx: commands.Context, state: Optional[Literal["on", "off"]] = None):
        conf = self.server_settings.get(ctx.guild.id)
        if state is None:
            await ctx.send(_say("vc-greet-status-on" if conf["vc_greet"] else "vc-greet-status-off"), ephemeral=True)
            return
        if not ctx.author.guild_permissions.manage_guild:
            await ctx.send(_say("auto-join-no-permission"), ephemeral=True)
            return
        self.server_settings.set(ctx.guild.id, vc_greet=state == "on")
        await ctx.send(_say("vc-greet-on" if state == "on" else "vc-greet-off"))

    @server_settings_group.command(
        name="vcsetvoice",
        description="The voice Yu uses in this server for people who haven't picked their own.",
    )
    @app_commands.describe(voice="The server's default voice (leave empty to reset it)")
    @app_commands.choices(voice=VOICE_CHOICES)
    @commands.guild_only()
    async def server_setvoice(self, ctx: commands.Context, voice: Optional[str] = None):
        if not ctx.author.guild_permissions.manage_guild:
            await ctx.send(_say("auto-join-no-permission"), ephemeral=True)
            return
        voices = ts.get_voices(_cfg())
        if voice is None:
            self.server_settings.set(ctx.guild.id, voice=None)
            await ctx.send(_say("server-voice-reset"))
            return
        if voice not in voices:
            await ctx.send(_say("unknown-voice"), ephemeral=True)
            return
        self.server_settings.set(ctx.guild.id, voice=voice)
        await ctx.send(_say("server-voice-set", voice=voices[voice].get("label", voice)))

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        await self.manager.handle_message(message, DEFAULT_PREFIX)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        for key, channel_id, info in await self.manager.handle_voice_state(member, before, after):
            channel = self.bot.get_channel(channel_id)
            if channel is not None:
                try:
                    await channel.send(_say(key, **info), allowed_mentions=discord.AllowedMentions.none())
                except discord.HTTPException:
                    pass


async def setup(bot):
    await bot.add_cog(TTS(bot))

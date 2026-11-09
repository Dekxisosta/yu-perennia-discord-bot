import asyncio
import os
from typing import Optional

from discord import app_commands
from discord.ext import commands, tasks

from config.bot_defaults import DEFAULT_PREFIX
from config.directories import TRANSLATE_CHANNELS_FILE
from datastore.static_data import config
from services.commands import translate_service as ts
from utils.console_logger import log


class Translate(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.translator = ts.Translator()
        default_key = ts.resolve_language(os.getenv("TRANSLATE_DEFAULT_LANGUAGE")) or "zh"
        if default_key == "off":
            default_key = "zh"
        self.settings = ts.ChannelSettings(
            TRANSLATE_CHANNELS_FILE,
            seed_ids=ts.parse_channel_ids(os.getenv("TRANSLATE_CHANNEL_IDS")),
            default_key=default_key,
        )

    @tasks.loop(minutes=1)
    async def sync_settings(self):
        # Picks up channel changes made from the admin dashboard
        await asyncio.to_thread(self.settings.refresh)

    async def cog_load(self):
        self.sync_settings.start()
        if not self.translator.configured:
            log("DEEPL_API_KEY is not set; translation is disabled.",
                module_name="TRANSLATE", success=False)
        else:
            log(f"Auto-translate active in {self.settings.active_count} channel(s).",
                module_name="TRANSLATE", success=True)
        if self.settings.unsupported_count:
            log(f"{self.settings.unsupported_count} channel(s) use a language Yu no longer supports and are paused. "
                f"Supported: {ts.supported_names()}.", module_name="TRANSLATE", success=False)

    async def cog_unload(self):
        self.sync_settings.cancel()
        await self.translator.close()

    @commands.hybrid_command(
        name="translate",
        description=config["utility"]["commands"]["translate"]["desc"],
    )
    @app_commands.describe(
        language="Language to translate into, or Off to stop translating in this channel",
        text="Optional: translate this text once instead of changing the channel",
        source="Language of the input (default: auto-detect)",
    )
    @app_commands.rename(language="to", source="from")
    async def translate(
        self,
        ctx: commands.Context,
        language: str,
        *,
        text: Optional[str] = None,
        source: str = "auto",
    ):
        await ts.translate_command(
            ctx=ctx,
            translator=self.translator,
            settings=self.settings,
            language=language,
            text=text,
            cfg=config["translate"]["command"],
            source=source,
        )

    @translate.autocomplete("language")
    async def language_autocomplete(self, interaction, current: str):
        return [app_commands.Choice(name=n, value=k) for n, k in ts.language_options(current)]

    @translate.autocomplete("source")
    async def source_autocomplete(self, interaction, current: str):
        return [
            app_commands.Choice(name=n, value=k)
            for n, k in ts.language_options(current, extra=("Auto-detect", "auto"))
        ]

    @commands.Cog.listener()
    async def on_message(self, message):
        await ts.auto_translate(
            message=message,
            translator=self.translator,
            settings=self.settings,
            prefix=DEFAULT_PREFIX,
            cfg=config["translate"]["auto"],
        )


async def setup(bot):
    await bot.add_cog(Translate(bot))

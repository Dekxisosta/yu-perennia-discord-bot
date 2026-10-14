import os
from typing import Optional

from discord import app_commands
from discord.ext import commands

from config.bot_defaults import DEFAULT_PREFIX
from config.directories import TRANSLATE_CHANNELS_FILE
from datastore.static_data import config
from services.commands import translate_service as ts
from utils.console_logger import log

LANGUAGE_CHOICES = [
    app_commands.Choice(name="Chinese", value="zh"),
    app_commands.Choice(name="Japanese", value="ja"),
    app_commands.Choice(name="Off", value="off"),
]


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

    async def cog_load(self):
        if not self.translator.configured:
            log("DEEPL_API_KEY is not set; translation is disabled.",
                module_name="TRANSLATE", success=False)
        else:
            log(f"Auto-translate active in {self.settings.active_count} channel(s).",
                module_name="TRANSLATE", success=True)

    async def cog_unload(self):
        await self.translator.close()

    @commands.hybrid_command(
        name="translate",
        description=config["utility"]["commands"]["translate"]["desc"],
    )
    @app_commands.describe(
        language="Chinese or Japanese (paired with English), or Off to stop translating here",
        text="Optional: translate this text once instead of changing the channel",
    )
    @app_commands.choices(language=LANGUAGE_CHOICES)
    async def translate(self, ctx: commands.Context, language: str, *, text: Optional[str] = None):
        await ts.translate_command(
            ctx=ctx,
            translator=self.translator,
            settings=self.settings,
            language=language,
            text=text,
            cfg=config["translate"]["command"],
        )

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

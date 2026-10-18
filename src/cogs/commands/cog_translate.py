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

LANGUAGE_CHOICES = [
    app_commands.Choice(name="English", value="en"),
    app_commands.Choice(name="Filipino", value="fil"),
    app_commands.Choice(name="Chinese", value="zh"),
    app_commands.Choice(name="Chinese (Traditional)", value="zh-TW"),
    app_commands.Choice(name="Japanese", value="ja"),
    app_commands.Choice(name="Korean", value="ko"),
    app_commands.Choice(name="Spanish", value="es"),
    app_commands.Choice(name="French", value="fr"),
    app_commands.Choice(name="German", value="de"),
    app_commands.Choice(name="Portuguese", value="pt"),
    app_commands.Choice(name="Brazilian Portuguese", value="pt-BR"),
    app_commands.Choice(name="Russian", value="ru"),
    app_commands.Choice(name="Arabic", value="ar"),
    app_commands.Choice(name="Hindi", value="hi"),
    app_commands.Choice(name="Bengali", value="bn"),
    app_commands.Choice(name="Indonesian", value="id"),
    app_commands.Choice(name="Malay", value="ms"),
    app_commands.Choice(name="Thai", value="th"),
    app_commands.Choice(name="Vietnamese", value="vi"),
    app_commands.Choice(name="Turkish", value="tr"),
    app_commands.Choice(name="Italian", value="it"),
    app_commands.Choice(name="Dutch", value="nl"),
    app_commands.Choice(name="Polish", value="pl"),
    app_commands.Choice(name="Ukrainian", value="uk"),
    app_commands.Choice(name="Greek", value="el"),
    app_commands.Choice(name="Czech", value="cs"),
    app_commands.Choice(name="Swedish", value="sv"),
    app_commands.Choice(name="Danish", value="da"),
    app_commands.Choice(name="Finnish", value="fi"),
    app_commands.Choice(name="Norwegian", value="no"),
    app_commands.Choice(name="Romanian", value="ro"),
    app_commands.Choice(name="Hungarian", value="hu"),
    app_commands.Choice(name="Hebrew", value="he"),
    app_commands.Choice(name="Persian", value="fa"),
    app_commands.Choice(name="Tamil", value="ta"),
    app_commands.Choice(name="Urdu", value="ur"),
    app_commands.Choice(name="Swahili", value="sw"),
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

    async def cog_unload(self):
        self.sync_settings.cancel()
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

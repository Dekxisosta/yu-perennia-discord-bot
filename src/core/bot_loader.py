import os
import logging
import discord

from discord.ext import commands

from utils.console_logger import log
from config.bot_defaults import (
    DEFAULT_PREFIX,
    DEFAULT_TOKEN,
    DEFAULT_INTENTS,
)
from config.directories import (
    COMMANDS_FOLDER_PATH,
    EVENTS_FOLDER_PATH,
)


async def autoload_folder(
    bot: commands.Bot,
    folder_path: str,
    package_prefix: str,
) -> None:
    folder_abs = os.path.abspath(folder_path)
    success_count = 0
    failed_count = 0

    for filename in os.listdir(folder_abs):
        if filename.endswith(".py") and not filename.startswith("__"):
            module_name = filename[:-3]
            full_path = f"{package_prefix}.{module_name}"

            try:
                await bot.load_extension(full_path)

                log(
                    f"Loaded {full_path}",
                    module_name="AUTOLOADER",
                    success=True,
                )
                success_count += 1

            except Exception as e:
                log(
                    f"Failed to load {full_path}: {e}",
                    module_name="AUTOLOADER",
                    success=False,
                )
                failed_count += 1

    total_count = success_count + failed_count

    log(
        f"Successfully loaded {success_count}/{total_count} "
        f"cogs from {package_prefix}.",
        module_name="AUTOLOADER",
        success=failed_count == 0,
    )


bot = commands.Bot(
    command_prefix=DEFAULT_PREFIX,
    intents=DEFAULT_INTENTS,
    help_command=None,
)


@bot.event
async def setup_hook() -> None:
    await autoload_folder(
        bot,
        folder_path=COMMANDS_FOLDER_PATH,
        package_prefix="cogs.commands",
    )

    await autoload_folder(
        bot,
        folder_path=EVENTS_FOLDER_PATH,
        package_prefix="cogs.events",
    )


@bot.event
async def on_ready() -> None:
    await bot.change_presence(
        activity=discord.Game(
            name="Apologies, Masters... Under Maintenance"
        ),
        status=discord.Status.dnd,
    )

    log(
        f"Logged in as {bot.user}",
        module_name="BOT",
        success=True,
    )


def load() -> None:
    bot.run(
        DEFAULT_TOKEN,  # type: ignore[arg-type]
        log_handler=None,
        log_level=logging.DEBUG,
    )
import asyncio

from discord.ext import commands, tasks

from core import config_loader
from utils.console_logger import log

MODULE = "CONFIG_SYNC"
INTERVAL_HOURS = 6  # keep this low-frequency to save Supabase calls; the dashboard's "Refresh bot" is instant


class ConfigSync(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        self.sync_config.start()

    async def cog_unload(self):
        self.sync_config.cancel()

    @tasks.loop(hours=INTERVAL_HOURS)
    async def sync_config(self):
        if self.sync_config.current_loop == 0:
            return  # config was just loaded at startup
        ok = await asyncio.to_thread(config_loader.reload)
        log(f"Scheduled config check: {'applied' if ok else 'skipped'}.", module_name=MODULE, success=ok)

    @sync_config.before_loop
    async def _wait_ready(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(ConfigSync(bot))

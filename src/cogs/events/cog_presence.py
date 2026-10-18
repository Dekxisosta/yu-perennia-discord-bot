import asyncio

import discord
from discord.ext import commands, tasks

from core import config_loader
from utils.console_logger import log
from utils.supabase_client import get_client

MODULE = "PRESENCE"
TABLE = "bot_status"

# Used until a status is saved from the admin dashboard (or if Supabase is unreachable at startup).
DEFAULT = {"status": "dnd", "activity_type": "playing", "message": "Apologies, Masters... Under Maintenance"}

STATUSES = {
    "online": discord.Status.online,
    "idle": discord.Status.idle,
    "dnd": discord.Status.dnd,
    "invisible": discord.Status.invisible,
}
ACTIVITY_TYPES = {
    "listening": discord.ActivityType.listening,
    "watching": discord.ActivityType.watching,
    "competing": discord.ActivityType.competing,
}


def build_presence(cfg: dict) -> tuple[discord.BaseActivity | None, discord.Status]:
    """Turn a {status, activity_type, message} dict into discord.py presence arguments."""
    status = STATUSES.get(cfg.get("status"), discord.Status.online)
    kind = cfg.get("activity_type")
    text = (cfg.get("message") or "").strip()[:128]
    if not text or kind == "none":
        return None, status
    if kind == "custom":
        return discord.CustomActivity(name=text), status
    if kind in ACTIVITY_TYPES:
        return discord.Activity(type=ACTIVITY_TYPES[kind], name=text), status
    return discord.Game(name=text), status


_UNSET = object()
STATUS_KEYS = ("status", "activity_type", "message")


class Presence(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._applied: dict | None = None
        self._seen_refresh = _UNSET  # last refresh_requested_at we have handled

    async def cog_load(self):
        self.sync_presence.start()

    async def cog_unload(self):
        self.sync_presence.cancel()

    def _fetch(self) -> dict | None:
        """Blocking. Returns the saved status, DEFAULT if none is saved, None if Supabase failed."""
        client = get_client()
        if client is None:
            return DEFAULT
        try:
            rows = client.table(TABLE).select("status,activity_type,message,refresh_requested_at").eq("id", 1).limit(1).execute().data
        except Exception as e:
            log(f"Could not load status from Supabase: {e}", module_name=MODULE, success=False)
            return None
        return rows[0] if rows else DEFAULT

    async def _refresh(self):
        """Handle a "Refresh bot" request from the dashboard."""
        log("Refresh requested from the dashboard.", module_name=MODULE, success=True)
        await asyncio.to_thread(config_loader.reload)
        translate = self.bot.get_cog("Translate")
        if translate is not None:
            await asyncio.to_thread(translate.settings.refresh)

    @tasks.loop(seconds=30)
    async def sync_presence(self):
        row = await asyncio.to_thread(self._fetch)
        if row is not None:
            stamp = row.get("refresh_requested_at")
            if self._seen_refresh is _UNSET:
                self._seen_refresh = stamp  # first poll after start: config was just loaded anyway
            elif stamp and stamp != self._seen_refresh:
                self._seen_refresh = stamp
                await self._refresh()

        if row is None:
            if self._applied is not None:
                return  # Supabase failed; keep what is showing
            row = DEFAULT
        cfg = {k: row.get(k) for k in STATUS_KEYS}
        if cfg == self._applied:
            return
        activity, status = build_presence(cfg)
        await self.bot.change_presence(activity=activity, status=status)
        self._applied = cfg
        log(f"Status set to {cfg['status']} / {cfg['activity_type']}: {cfg.get('message')}",
            module_name=MODULE, success=True)

    @sync_presence.before_loop
    async def _wait_ready(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(Presence(bot))

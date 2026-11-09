import typing
from inspect import Parameter

from discord.ext import commands

from factories.help_group_factory import create_group as create_help_group
from ui.page_view import PageView

# Help Command : Shows every registered command, split into three pages.
#
# The list is built from the commands the bot has actually registered, so a new
# command or subcommand shows up here without editing any config. The YAML configs
# (general / utility / mod) are still used for descriptions, usage and long
# descriptions whenever they have an entry for the command.

DROPDOWN_LIMIT = 25      # Discord allows at most 25 options in a select menu
DESC_LIMIT = 100         # ...and 100 characters per option description

# Commands that only exist for admins / maintenance and don't belong in /help
HIDDEN_COMMANDS = {"sync"}

# Display order and wording of the three pages
PAGES = {
    "vc_user": {
        "heading": "VC User Settings",
        "desc": "Voice channel commands for everyone. Your own settings beat the server's!",
    },
    "vc_server": {
        "heading": "VC Server Settings",
        "desc": "Staff only (Manage Server). How Yu behaves in voice channels for the whole server.",
    },
    "main": {
        "heading": "Main Commands",
        "desc": "Everyday commands, translation and moderation.",
    },
}

SERVER_SETTINGS_GROUP = "server-settings"


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _category(full_name: str, cog_name: str | None) -> str:
    root = full_name.split(" ")[0]
    if root == SERVER_SETTINGS_GROUP:
        return "vc_server"
    if root == "user-settings" or cog_name == "TTS":
        return "vc_user"
    return "main"


def _walk(command: commands.Command, parent: str = ""):
    """Yield (full_name, command) for every runnable command, descending into groups."""
    full_name = f"{parent} {command.name}".strip()
    if isinstance(command, commands.Group):
        for sub in sorted(command.commands, key=lambda c: c.name):
            yield from _walk(sub, full_name)
    else:
        yield full_name, command


def _choices(annotation) -> list[str] | None:
    """Return the options of a Literal[...] (also inside Optional[...]) or None."""
    origin = typing.get_origin(annotation)
    if origin is typing.Literal:
        return [str(a) for a in typing.get_args(annotation)]
    if origin is typing.Union:
        for arg in typing.get_args(annotation):
            found = _choices(arg)
            if found:
                return found
    return None


def _param_hint(name: str, param: Parameter) -> str:
    label = "|".join(_choices(param.annotation) or []) or name
    return f"<{label}>" if param.default is Parameter.empty else f"[{label}]"


def _generated_usage(full_name: str, command: commands.Command, prefix: str) -> str:
    params = " ".join(_param_hint(n, p) for n, p in command.clean_params.items())
    tail = f" {params}" if params else ""
    return f"/{full_name}{tail} | {prefix}{full_name}{tail}"


def _param_details(command: commands.Command) -> str | None:
    """Option explanations written with @app_commands.describe(...)."""
    described = getattr(command.callback, "__discord_app_commands_param_description__", None) or {}
    if not described:
        return None
    return " ".join(f"**{name}**: {text}" for name, text in described.items())


def _config_entry(config: dict, full_name: str) -> dict:
    """Find the YAML entry for a command, if there is one."""
    parts = full_name.split(" ")
    try:
        if len(parts) == 1:
            for section in ("general", "utility"):
                entry = config[section]["commands"].get(parts[0])
                if entry:
                    return entry
        elif len(parts) == 2 and parts[0] == config["mod"]["prefix"]:
            return config["mod"]["commands"].get(parts[1]) or {}
    except (KeyError, TypeError, AttributeError):
        pass
    return {}


def _build_entry(full_name: str, command: commands.Command, config: dict, prefix: str) -> dict:
    entry = _config_entry(config, full_name)
    desc = entry.get("desc") or command.description or command.brief or command.short_doc or "No description provided."

    more_desc = entry.get("more-desc")
    if not more_desc:
        extra = _param_details(command)
        if full_name.startswith(f"{SERVER_SETTINGS_GROUP} "):
            note = "Changing this needs Manage Server."
            more_desc = f"{note} {extra}" if extra else note
        else:
            more_desc = extra

    return {
        "desc": _truncate(desc, DESC_LIMIT),
        "usage": entry.get("usage") or _generated_usage(full_name, command, prefix),
        "more-desc": more_desc,
    }


def collect_groups(bot: commands.Bot, config: dict, bot_prefix: str) -> dict[str, dict]:
    """Sort every registered command into the three help pages."""
    pages: dict[str, dict] = {key: {} for key in PAGES}
    for top in sorted(bot.commands, key=lambda c: c.name):
        if top.hidden or top.name in HIDDEN_COMMANDS:
            continue
        for full_name, command in _walk(top):
            if command.hidden:
                continue
            page = _category(full_name, command.cog_name)
            pages[page][full_name] = _build_entry(full_name, command, config, bot_prefix)
    return pages


async def help(ctx: commands.Context, bot_prefix: str, config: dict):
    collected = collect_groups(ctx.bot, config, bot_prefix)

    groups = [
        create_help_group(
            desc=PAGES[key]["desc"],
            commands=dict(list(cmds.items())[:DROPDOWN_LIMIT]),
            heading=PAGES[key]["heading"],
        )
        for key, cmds in collected.items()
        if cmds
    ]

    view = PageView(groups)

    if ctx.interaction is not None:
        await ctx.interaction.response.defer()
        await ctx.interaction.followup.send(embed=groups[0].embed, view=view, ephemeral=True)
    else:
        await ctx.send(embed=groups[0].embed, view=view)

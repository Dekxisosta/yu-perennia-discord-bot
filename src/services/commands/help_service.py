from factories.help_group_factory import create_group as create_help_group
from ui.page_view import PageView
from discord.ext import commands

# Help Command : Shows a list of available commands
async def help(ctx: commands.Context, bot_prefix: str, config: dict):
    groups = [
        create_help_group(
            desc=config["general"]["desc"],
            commands=config["general"]["commands"],
        ),
        create_help_group(
            desc=config["mod"]["desc"],
            commands=config["mod"]["commands"],
            group_prefix=config["mod"]["prefix"]
        ),
        create_help_group(
            desc=config["utility"]["desc"],
            commands=config["utility"]["commands"],
        )
    ]
    
    view = PageView(groups)

    if ctx.interaction is not None:
        await ctx.interaction.response.defer()
        await ctx.interaction.followup.send(embed=groups[0].embed, view=view, ephemeral=True)
    else:
        await ctx.send(embed=groups[0].embed, view=view)
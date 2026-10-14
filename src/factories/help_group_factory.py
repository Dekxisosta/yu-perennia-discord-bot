import discord
from model.help_model import CommandHelpGroup as HelpGroup

def create_group(desc: str, commands: dict,group_prefix: str | None = None):
    embed = discord.Embed(
        title="🌸 **Yu Perennia Bot Commands**",
        description="Here are all the things Yu can help you with!",
        color=discord.Color.dark_magenta()
    )
    if group_prefix is not None:
        embed.add_field(
            name=f"🪻Prefix Command Group: {group_prefix}",
            value=f"\"{desc}\"",
            inline=False
        )
    else:
        embed.add_field(
            name=f"🪻Set of Available Commands",
            value=f"\"{desc}\"",
            inline=False
        )

    for cmd_name, _ in commands.items():
        if cmd_name == "main":
            continue
        if group_prefix is None:
            embed.add_field(
                name = f"**/{cmd_name}**",
                value= commands[cmd_name]["desc"], 
                inline=True)
        else:
            embed.add_field(
                name = f"**/{group_prefix} {cmd_name}**",
                value=commands[cmd_name]["desc"], 
                inline=True)
            
        embed.set_footer(text="For more information about a command, use the dropdown provided below")

    return HelpGroup(embed=embed, commands=commands)
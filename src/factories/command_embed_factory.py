import discord

def create(
    cmd_name: str,
    desc: str,
    usage: str,
    more_desc: str | None = None,
    more_usage: str | None = None
) -> discord.Embed:
    
    embed = discord.Embed(
        title=f"Command: {cmd_name}",
        description=desc,
        color=discord.Color.purple()
    )
    embed.add_field(
        name="Usage",
        value=f"`{usage}`",
        inline=False
    )

    if more_desc:
        embed.add_field(
            name="Description",
            value=more_desc,
            inline=False
        )

    if more_usage:
        embed.add_field(
            name="Additional Usage",
            value=f"`{more_usage}`",
            inline=False
        )

    embed.set_footer(
        text="Yu Perennia Bot • General Commands"
    )

    return embed
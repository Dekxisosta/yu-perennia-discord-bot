from discord.ext import commands
# from data import session_data as db
# from resources.textlines.callouts import LINES
# from resources.hooks.greeting_hooks import HOOKS

class OnMessage(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # @commands.Cog.listener()
    # async def on_message(self, msg):
    #     if msg.author.bot:
    #         return
        
    #     content = msg.content.lower()
        
    #     if "yu perennia" in content and any(g in content for g in HOOKS):
    #         if db.callout_line_count >= len(LINES):
    #             db.callout_line_count=0

    #         await msg.channel.send(LINES[db.callout_line_count].format(user = msg.author.mention))

    #         db.callout_line_count += 1

async def setup(bot):
    await bot.add_cog(OnMessage(bot))
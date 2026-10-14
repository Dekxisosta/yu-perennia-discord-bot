from discord.ext import commands
from utils.message_sender import send_message
import random

# Greet Command : Randomly picks a greeting line
async def greet(ctx: commands.Context, greetings: list[str]):
    await send_message(ctx=ctx, msg=random.choice(greetings), delete_invoke=True)

# Ping Command : Shows Yu Perennia's response time
async def ping(bot, ctx: commands.Context, format: str):
    await send_message(ctx=ctx, msg=format.format(round(bot.latency*1000)), delete_invoke=True)

# Info Command : Tells information about the bot
async def info(ctx:commands.Context, info: str):
    await send_message(ctx=ctx, msg=info, delete_invoke=True)

# Quote Command : Randomly says whatever quote that is unique to Yu Perennia's traits
async def quote(ctx:commands.Context, quotes: list[str]):
    await send_message(ctx=ctx, msg=random.choice(quotes), delete_invoke=True)

# Umaline Command : Randomly says a Yu Perennia voiceline as text
async def umaline(ctx:commands.Context, textlines: list[str]):
    await send_message(ctx=ctx, msg=random.choice(textlines), delete_invoke=True)

# Say Command : Says the message the user wants Yu Perennia to say
async def say(ctx:commands.Context, msg: str):
    await send_message(ctx=ctx, msg=msg, delete_invoke=True)

# Coinflip Command : Chooses a number at random 1-2
async def coinflip(ctx:commands.Context, format: str):
    await send_message(ctx=ctx, msg=format.format(outcome = random.choice(["heads", "tails"])), delete_invoke=True)
        
# Roll Command : Chooses a number at random 1-6
async def roll(ctx:commands.Context, format: str):
    await send_message(ctx=ctx, msg=format.format(outcome = random.randint(1,6)), delete_invoke=True)

# 8ball Command : Determine fortune
async def eightBall(ctx:commands.Context, question: str, formatQuestion: str, formatResponse: str, responses: list):
    msg = formatResponse.format(random.choice(responses))
    if ctx.interaction is not None:
        msg = formatQuestion.format(question=question) + "\n" + msg
    await send_message(ctx=ctx, msg=msg, delete_invoke=True)

# Choose Command : Choose from a list of options
async def choose(ctx:commands.Context, input: str, format: str, fallback: str, usage: str):
    sep = "|" if "|" in input else ","
    choices = [opt.strip() for opt in input.split(sep) if opt.strip()]

    msg = ""
    if len(choices) < 2:
        msg = f"{fallback}\nExample: {usage}"
    else:
        msg = format.format(random.choice(choices))

    await send_message(ctx=ctx, msg=msg, delete_invoke=True)





    

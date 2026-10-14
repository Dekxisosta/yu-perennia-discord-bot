import os, discord
from dotenv import load_dotenv

def load_token():
    load_dotenv()
    return os.getenv("DISCORD_TOKEN")

def get_intents():
    intents = discord.Intents.default()
    intents.message_content = True
    intents.members = True
    return intents

DEFAULT_PREFIX = "yp!"
DEFAULT_TOKEN = load_token()
DEFAULT_INTENTS = get_intents()
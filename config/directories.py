from pathlib import Path

# This file is at config/directories.py
# parent = config/, parent.parent = project_root/
ROOT = Path(__file__).resolve().parent.parent

COMMANDS_FOLDER_PATH = str(ROOT / "src" / "cogs" / "commands")
EVENTS_FOLDER_PATH = str(ROOT / "src" / "cogs" / "events")
CONFIG_YAML_FOLDER_PATH = str(ROOT / "config" / "commands")
LOGGING = str(ROOT / "src" / "log" / "discord.log")
TRANSLATE_CHANNELS_FILE = str(ROOT / "data" / "translate_channels.json")



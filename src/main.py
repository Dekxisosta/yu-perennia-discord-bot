import sys
from pathlib import Path

# Add both src/ and project root to path for imports
src_dir = Path(__file__).resolve().parent
project_root = src_dir.parent

sys.path.insert(0, str(src_dir))
sys.path.insert(0, str(project_root))

from core import logger_loader, config_loader, bot_loader

logger_loader.load()
config_loader.load()
bot_loader.load()

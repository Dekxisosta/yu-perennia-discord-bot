import sys
import os
from datetime import datetime
from config.system_details import SYSTEM_NAME

# Set UTF-8 encoding for console output on Windows
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

def log(message: str, module_name: str = "N/A", success: bool = True):
    now = datetime.now()
    
    # Use simple ASCII symbols that work everywhere
    symbol = "[+]" if success else "[!]"
    level = "INFO" if success else "WARN"
    
    # Color codes for supported terminals
    color_start = "" if success else "\033[38;5;208m"
    color_end = "" if success else "\033[0m"
    
    print(f"{symbol} {now} | {level} | {SYSTEM_NAME}:{module_name} | {color_start}{message}{color_end}")



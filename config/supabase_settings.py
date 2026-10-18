import os
from dotenv import load_dotenv

load_dotenv()

# Project URL, e.g. https://xxxx.supabase.co
SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip()
# Service role / secret key. Server-side only: never put it in the website or commit it.
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "").strip()
# Table that holds one row per config file (see supabase/schema.sql).
SUPABASE_CONFIG_TABLE = os.getenv("SUPABASE_CONFIG_TABLE", "bot_config").strip()

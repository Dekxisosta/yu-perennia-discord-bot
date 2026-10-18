"""Shared, lazily created Supabase client (service role). Returns None when not configured."""
from config.supabase_settings import SUPABASE_URL, SUPABASE_SERVICE_KEY

_client = None
_failed = False


def get_client():
    global _client, _failed
    if _client is not None:
        return _client
    if _failed or not (SUPABASE_URL and SUPABASE_SERVICE_KEY):
        return None
    try:
        from supabase import create_client
        _client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
    except Exception:
        _failed = True
        return None
    return _client

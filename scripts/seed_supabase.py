"""Push the YAML files in config/commands/ to the Supabase bot_config table.

    python scripts/seed_supabase.py            # insert missing files only
    python scripts/seed_supabase.py --force    # overwrite what is already there
"""
import json, sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config.supabase_settings import SUPABASE_URL, SUPABASE_SERVICE_KEY, SUPABASE_CONFIG_TABLE  # noqa: E402
from config.directories import CONFIG_YAML_FOLDER_PATH  # noqa: E402


def main() -> int:
    if not (SUPABASE_URL and SUPABASE_SERVICE_KEY):
        print("Set SUPABASE_URL and SUPABASE_SERVICE_KEY in .env first.")
        return 1
    from supabase import create_client

    client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
    force = "--force" in sys.argv
    existing = {r["name"] for r in client.table(SUPABASE_CONFIG_TABLE).select("name").execute().data or []}

    for file in sorted(Path(CONFIG_YAML_FOLDER_PATH).glob("*_config.yaml")):
        name = file.name[: -len("_config.yaml")]
        if name in existing and not force:
            print(f"skip   {name} (already in Supabase, use --force to overwrite)")
            continue
        data = json.loads(json.dumps(yaml.safe_load(file.read_text(encoding="utf-8")), default=str))
        client.table(SUPABASE_CONFIG_TABLE).upsert({"name": name, "data": data}).execute()
        print(f"pushed {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

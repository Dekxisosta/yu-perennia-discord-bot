from datastore.static_data import config as datastore
from pathlib import Path
from utils.console_logger import log
from config.directories import CONFIG_YAML_FOLDER_PATH
from config.supabase_settings import SUPABASE_URL, SUPABASE_SERVICE_KEY, SUPABASE_CONFIG_TABLE
from utils.supabase_client import get_client
import os, yaml

file_suffix = "_config.yaml"
path = Path(CONFIG_YAML_FOLDER_PATH)


def _load_yaml():
    """Load the bundled YAML files. These are the defaults and the offline fallback."""
    success_count = 0
    failed_count = 0
    for file in os.listdir(path):
        if file.endswith(file_suffix):
            file_path = path / file
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    datastore[file[:-len(file_suffix)]] = yaml.safe_load(f)
                log(f"Loaded {file}", module_name="YAML_LOADER", success=True)
                success_count += 1
            except Exception as e:
                log(f"Failed to load {file}: {e}", module_name="YAML_LOADER", success=False)
                failed_count += 1
    log(
        f"Finished loading YAML files: {success_count} succeeded, {failed_count} failed.",
        module_name="YAML_LOADER",
        success=failed_count == 0
    )


def _load_supabase():
    """Overlay config rows from Supabase on top of the YAML defaults.

    Skipped when SUPABASE_URL / SUPABASE_SERVICE_KEY are not set. Any failure
    leaves the YAML values in place, so the bot always starts.
    """
    if not (SUPABASE_URL and SUPABASE_SERVICE_KEY):
        log("Supabase not configured, using local YAML only.", module_name="SUPABASE_LOADER", success=True)
        return
    try:
        client = get_client()
        if client is None:
            raise RuntimeError("could not create Supabase client")
        rows = client.table(SUPABASE_CONFIG_TABLE).select("name,data").execute().data or []
    except Exception as e:
        log(f"Could not reach Supabase, keeping YAML config: {e}", module_name="SUPABASE_LOADER", success=False)
        return

    applied = 0
    for row in rows:
        if isinstance(row.get("data"), dict):
            datastore[row["name"]] = row["data"]
            log(f"Loaded {row['name']} from Supabase", module_name="SUPABASE_LOADER", success=True)
            applied += 1
        else:
            log(f"Ignored {row.get('name')}: data is not an object", module_name="SUPABASE_LOADER", success=False)
    log(f"Finished loading Supabase config: {applied} applied.", module_name="SUPABASE_LOADER", success=True)


def load():
    _load_yaml()
    _load_supabase()

from datastore.static_data import config as datastore
from pathlib import Path
from utils.console_logger import log
from config.directories import CONFIG_YAML_FOLDER_PATH
from config.supabase_settings import SUPABASE_URL, SUPABASE_SERVICE_KEY, SUPABASE_CONFIG_TABLE
from utils.supabase_client import get_client
import os, yaml

file_suffix = "_config.yaml"
path = Path(CONFIG_YAML_FOLDER_PATH)


def _load_yaml(target=datastore):
    """Load the bundled YAML files. These are the defaults and the offline fallback."""
    success_count = 0
    failed_count = 0
    for file in os.listdir(path):
        if file.endswith(file_suffix):
            file_path = path / file
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    target[file[:-len(file_suffix)]] = yaml.safe_load(f)
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


def _load_supabase(target=datastore) -> bool:
    """Overlay config rows from Supabase on top of the YAML defaults.

    Skipped when SUPABASE_URL / SUPABASE_SERVICE_KEY are not set. Any failure
    leaves the YAML values in place, so the bot always starts.
    Returns False only when Supabase is configured but could not be read.
    """
    if not (SUPABASE_URL and SUPABASE_SERVICE_KEY):
        log("Supabase not configured, using local YAML only.", module_name="SUPABASE_LOADER", success=True)
        return True
    try:
        client = get_client()
        if client is None:
            raise RuntimeError("could not create Supabase client")
        rows = client.table(SUPABASE_CONFIG_TABLE).select("name,data").execute().data or []
    except Exception as e:
        log(f"Could not reach Supabase, keeping YAML config: {e}", module_name="SUPABASE_LOADER", success=False)
        return False

    applied = 0
    for row in rows:
        if isinstance(row.get("data"), dict):
            target[row["name"]] = row["data"]
            log(f"Loaded {row['name']} from Supabase", module_name="SUPABASE_LOADER", success=True)
            applied += 1
        else:
            log(f"Ignored {row.get('name')}: data is not an object", module_name="SUPABASE_LOADER", success=False)
    log(f"Finished loading Supabase config: {applied} applied.", module_name="SUPABASE_LOADER", success=True)
    return True


def load():
    _load_yaml()
    _load_supabase()


def reload() -> bool:
    """Re-read YAML + Supabase and swap the result into the datastore in one step (blocking).

    If Supabase is configured but unreachable, nothing changes, so dashboard edits are never
    replaced by the bundled YAML defaults. Returns True if the new config was applied.
    """
    fresh: dict = {}
    _load_yaml(fresh)
    if not _load_supabase(fresh):
        log("Config refresh skipped: Supabase is unreachable.", module_name="CONFIG_RELOAD", success=False)
        return False
    datastore.update(fresh)
    log(f"Config refreshed ({len(fresh)} file(s)).", module_name="CONFIG_RELOAD", success=True)
    return True

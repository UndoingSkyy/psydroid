import json

from . import paths, storage

DEFAULTS = {
    "selected": None,
    "check_updates": False,
    "auto_update": False,
    "reduce_motion": False,
    "skipped_version": "",
    "claude_access": False,
    "close_to_tray": False,
    "boss_key": "",
    "always_on_top": False,
}


def load():
    try:
        saved = json.loads(paths.SETTINGS.read_text())
    except (OSError, ValueError):
        saved = {}
    if not isinstance(saved, dict):
        saved = {}
    return {**DEFAULTS, **{key: value for key, value in saved.items() if key in DEFAULTS}}


def save(values, key=None):
    storage.write_json(paths.SETTINGS, {name: values[name] for name in DEFAULTS})

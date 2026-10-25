"""Saved instance hardware, offered when creating a new instance."""
import json

from . import paths, storage

NAME_LIMIT = 32
FIELDS = ("cores", "ram", "width", "height", "density", "api", "camera", "block_ads", "disk", "gpu")


def load():
    try:
        entries = json.loads(paths.PRESETS.read_text())
    except (OSError, ValueError):
        return []
    return [entry for entry in entries if isinstance(entry, dict) and entry.get("name")] \
        if isinstance(entries, list) else []


def save(name, instance):
    name = name.strip()[:NAME_LIMIT].strip()
    if not name:
        raise ValueError("Give the preset a name")
    values = {"name": name, **{key: getattr(instance, key) for key in FIELDS}}
    kept = [preset for preset in load() if preset["name"].lower() != name.lower()]
    storage.write_json(paths.PRESETS, [*kept, values])
    return name


def delete(name):
    storage.write_json(paths.PRESETS, [preset for preset in load() if preset["name"] != name])

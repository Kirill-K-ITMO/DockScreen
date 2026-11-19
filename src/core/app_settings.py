"""Shared executable settings for every docking entry point."""
import json
from pathlib import Path
from src.core.settings_paths import read_settings_path

def vina_path(root):
    path = read_settings_path(root, 'app_settings.json')
    data = json.loads(path.read_text(encoding='utf-8-sig')) if path.exists() else {}
    value = data.get('vina_executable', 'vina')
    if not isinstance(value, str) or not value.strip():
        raise ValueError('app_settings.json: vina_executable must be a nonempty string')
    candidate = Path(value).expanduser()
    if not candidate.is_absolute() and (len(candidate.parts) > 1 or (Path(root)/candidate).is_file()):
        candidate = Path(root) / candidate
    return str(candidate)

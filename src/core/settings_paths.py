"""Project settings in one directory, with explicit read-only legacy fallback."""
from pathlib import Path


def settings_dir(root):
    return Path(root) / 'settings'


def settings_path(root, name):
    return settings_dir(root) / name


def read_settings_path(root, name):
    preferred = settings_path(root, name)
    return preferred if preferred.exists() else Path(root) / name


def receptor_settings_dir(root):
    preferred = settings_path(root, 'receptors')
    return preferred if preferred.exists() else Path(root) / 'data/configs'


def run_settings_dir(run):
    return Path(run) / 'settings'


def editable_settings_path(root, name):
    path = read_settings_path(root, name)
    return path if path.exists() else settings_path(root, name)

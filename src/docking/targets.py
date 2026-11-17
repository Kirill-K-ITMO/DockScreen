"""Portable receptor/configuration identifiers without implicit profile selection."""
from pathlib import Path
import re

EXTENSIONS = ('.txt', '.conf', '.config')


def component(value):
    if (not isinstance(value, str) or not value or value in ('.', '..')
            or value[-1:] in (' ', '.') or any(ord(c) < 32 for c in value)
            or any(c in value for c in '@<>:"/\\|?*')):
        raise ValueError(f'Invalid target component: {value!r}')
    if re.fullmatch(r'(?i:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])', value.split('.')[0]):
        raise ValueError(f'Reserved Windows target component: {value!r}')
    return value


def split_target(target_id):
    if not isinstance(target_id, str) or target_id.count('@') > 1:
        raise ValueError('Target ID must be R or R@profile')
    parts = target_id.split('@')
    return component(parts[0]), component(parts[1]) if len(parts) == 2 else None


def resolve_target(root, target_id):
    root = Path(root).resolve()
    receptor, profile = split_target(target_id)
    stem = root / 'data/configs' / receptor
    if profile is not None:
        stem = stem / profile
    matches = [stem.with_name(stem.name + ext) for ext in EXTENSIONS
               if stem.with_name(stem.name + ext).is_file()]
    if len(matches) > 1:
        raise ValueError(f'Ambiguous configurations for {target_id}: {matches}')
    if not matches:
        raise FileNotFoundError(f'No configuration for target {target_id}')
    receptor_path = root / 'data/proteins' / (receptor + '.pdbqt')
    if not receptor_path.is_file():
        raise FileNotFoundError(f'No receptor for target {target_id}')
    return dict(id=target_id, receptor=receptor, config_id=profile or 'default',
                receptor_path=receptor_path, config_path=matches[0])


def get_targets(root):
    root = Path(root)
    ids = set()
    for receptor_path in sorted((root / 'data/proteins').glob('*.pdbqt')):
        receptor = component(receptor_path.stem)
        configs = root / 'data/configs'
        if any((configs / (receptor + ext)).is_file() for ext in EXTENSIONS):
            ids.add(receptor)
        for profile in (configs / receptor).glob('*'):
            if profile.is_file() and profile.suffix in EXTENSIONS:
                ids.add(receptor + '@' + component(profile.stem))
    return [resolve_target(root, target_id) for target_id in sorted(ids)]

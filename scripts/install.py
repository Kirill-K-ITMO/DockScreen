"""Install the groups in pyproject.toml into separate, project-local environments.

No package lists are duplicated here. ADMET uses a different verified RDKit and
must never be merged into the docking environment. --dry-run performs no writes.
"""
import argparse
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tomllib
import venv

ROOT = Path(__file__).resolve().parents[1]
CPU_TORCH_INDEX = 'https://download.pytorch.org/whl/cpu'


def dependency_groups(project=ROOT):
    with (Path(project) / 'pyproject.toml').open('rb') as stream:
        document = tomllib.load(stream)
    groups = document['project']['optional-dependencies']
    if set(groups) != {'docking', 'admet', 'test'}:
        raise ValueError('pyproject.toml must define docking, admet and test dependency groups')
    for name, values in groups.items():
        if not isinstance(values, list) or not values:
            raise ValueError(f'Empty dependency group: {name}')
        packages = []
        for value in values:
            if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*==[0-9][A-Za-z0-9_.+!-]*', value):
                raise ValueError(f'Dependency must be an exact package==version pin: {value!r}')
            packages.append(value.split('==')[0].lower().replace('_', '-'))
        if len(set(packages)) != len(packages):
            raise ValueError(f'Duplicate package in dependency group: {name}')
    return groups


def assert_local_environment(folder):
    """Reject every existing link/reparse point before touching an environment."""
    folder = Path(folder)
    for part in [*reversed(folder.parents), folder]:
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ValueError(
                f'Refusing to modify a shared/linked environment: {part}. '
                'If this copy already runs, keep using START.cmd. For a fresh '
                'installation use a clean project copy with local environments.')
    if folder.exists() and not folder.is_dir():
        raise ValueError(f'Environment path is not a directory: {folder}')
    executable = folder / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    # POSIX virtual environments normally use a Python executable symlink. Only
    # the environment directory/parents must be local; Windows reparse points
    # anywhere in the executable path are never an installer target.
    if os.name == 'nt':
        for part in [executable.parent, executable]:
            try:
                info = part.lstat()
            except FileNotFoundError:
                continue
            if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
                raise ValueError(f'Refusing to modify a linked environment interpreter: {part}')
    return executable


def command(arguments):
    print('  ' + subprocess.list2cmdline([str(a) for a in arguments]), flush=True)
    subprocess.run([str(a) for a in arguments], check=True)


def installed_pins_match(python, pins):
    # Read distribution metadata without importing native scientific libraries.
    script = (
        'import importlib.metadata as m,json,sys; '
        'pins=json.loads(sys.argv[1]); '
        'actual={d.metadata["Name"].lower().replace("_","-"):d.version for d in m.distributions()}; '
        'sys.exit(0 if all(actual.get(p.split("==")[0].lower().replace("_","-"),"").split("+")[0]'
        '==p.split("==")[1] for p in pins) else 1)'
    )
    return subprocess.run([str(python), '-B', '-c', script, json.dumps(pins)], check=False).returncode == 0


def install_environment(folder, pins, *, cpu_torch=False, dry_run=False, update_existing=False):
    python = assert_local_environment(folder)
    print(f'Environment: {folder}', flush=True)
    if dry_run:
        print('  Create a local environment if absent; verify existing exact pins.')
        if cpu_torch:
            print(f'  CPU PyTorch wheel source: {CPU_TORCH_INDEX}')
        print('  Exact pins: ' + ', '.join(pins))
        print('  Then run pip check. No files or packages changed.')
        return
    if folder.exists():
        if not python.is_file():
            raise ValueError(f'Incomplete environment: {folder}; inspect it before installing')
        if installed_pins_match(python, pins):
            command([python, '-m', 'pip', 'check'])
            print('  Existing environment matches the selected pins; retained.')
            return
        if not update_existing:
            raise ValueError(
                f'Existing environment differs from selected pins: {folder}. '
                'It was not modified. Use --update-existing only if you intend '
                'to update this local environment.')
    else:
        print('  Creating a project-local virtual environment.', flush=True)
        venv.EnvBuilder(with_pip=True).create(folder)
    if cpu_torch:
        torch = next(p for p in pins if p.lower().startswith('torch=='))
        command([python, '-m', 'pip', 'install', '--index-url', CPU_TORCH_INDEX, torch])
    command([python, '-m', 'pip', 'install', *pins])
    command([python, '-m', 'pip', 'check'])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--admet', action='store_true', help='Also install optional ADMET into .venv-admet (large download)')
    parser.add_argument('--test', action='store_true', help='Also add the test group to the docking environment')
    parser.add_argument('--interactive', action='store_true', help='Ask whether to include optional ADMET')
    parser.add_argument('--dry-run', action='store_true', help='Show exact groups and paths; do not install or write files')
    parser.add_argument('--update-existing', action='store_true', help='Allow updating existing LOCAL environments with different pins; links remain forbidden')
    args = parser.parse_args(argv)
    if sys.version_info[:2] != (3, 12):
        parser.error('Use Python 3.12: py -3.12 scripts/install.py on Windows')
    try:
        groups = dependency_groups()
        if args.interactive and not args.admet and not args.dry_run:
            answer = input('Install optional local ADMET too (large CPU download)? [y/N]: ').strip().lower()
            args.admet = answer in ('y', 'yes', 'да', 'д')
        plans = [(ROOT / '.venv', groups['docking'] + (groups['test'] if args.test else []), False)]
        if args.admet:
            plans.append((ROOT / '.venv-admet', groups['admet'], True))
        # Validate ALL destinations first, so a shared ADMET directory cannot
        # trigger an installation into the other environment before rejection.
        for folder, _, _ in plans:
            assert_local_environment(folder)
        print(f'Dependency source: {ROOT / "pyproject.toml"}', flush=True)
        for folder, pins, cpu in plans:
            install_environment(folder, pins, cpu_torch=cpu, dry_run=args.dry_run,
                                update_existing=args.update_existing)
        print('Dry run complete.' if args.dry_run else 'Installation complete. Run CHECK.cmd, then START.cmd.')
        return 0
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f'Installation stopped: {error}', file=sys.stderr)
        return 1
    except (KeyboardInterrupt, EOFError):
        print('Installation interrupted. Run the installer again after inspecting any incomplete local environment.', file=sys.stderr)
        return 130


if __name__ == '__main__':
    raise SystemExit(main())

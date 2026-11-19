"""Independent installer and release checks; no downloads or real environment changes."""
import hashlib
import importlib.util
from pathlib import Path
import stat
from types import SimpleNamespace
import zipfile

import pytest


ROOT = Path(__file__).resolve().parents[1]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def installer():
    return module('installer_independent_review', ROOT / 'scripts/install.py')


def test_single_dependency_source_preserves_incompatible_rdkit_groups_and_pytest_configuration():
    import tomllib
    install = installer()
    groups = install.dependency_groups(ROOT)
    assert 'rdkit==2026.3.6' in groups['docking']
    assert 'rdkit==2026.9.2' in groups['admet']
    assert groups['test'] == ['pytest==9.1.1']
    with (ROOT / 'pyproject.toml').open('rb') as stream:
        document = tomllib.load(stream)
    assert document['project']['dependencies'] == []
    assert document['tool']['pytest']['ini_options']['testpaths'] == ['tests']
    assert document['tool']['pytest']['ini_options']['addopts'] == '--strict-markers'


def test_installer_dry_run_cannot_create_environment_or_invoke_network(tmp_path, monkeypatch):
    install = installer()
    def prohibited(*args, **kwargs): raise AssertionError('dry run must not run commands or create environments')
    monkeypatch.setattr(install.subprocess, 'run', prohibited)
    monkeypatch.setattr(install.venv, 'EnvBuilder', prohibited)
    install.install_environment(tmp_path / '.venv', ['numpy==2.3.5'], dry_run=True)
    assert not (tmp_path / '.venv').exists()


def test_shared_admet_destination_rejects_entire_plan_before_other_environment_is_touched(tmp_path, monkeypatch):
    install = installer()
    original_lstat = Path.lstat
    shared = tmp_path / '.venv-admet'
    def simulated_reparse(path, *args, **kwargs):
        if path == shared:
            return SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=0x400)
        return original_lstat(path, *args, **kwargs)
    def prohibited(*args, **kwargs): raise AssertionError('no environment may be touched before all destinations are checked')
    monkeypatch.setattr(Path, 'lstat', simulated_reparse)
    monkeypatch.setattr(install, 'ROOT', tmp_path)
    monkeypatch.setattr(install, 'dependency_groups', lambda: {'docking': ['numpy==2.3.5'], 'admet': ['torch==2.15.0'], 'test': []})
    monkeypatch.setattr(install, 'install_environment', prohibited)
    assert install.main(['--admet']) == 1
    assert not (tmp_path / '.venv').exists()


def test_different_existing_local_environment_requires_explicit_update(tmp_path, monkeypatch):
    install = installer()
    folder = tmp_path / '.venv'
    python = folder / ('Scripts/python.exe' if install.os.name == 'nt' else 'bin/python')
    python.parent.mkdir(parents=True)
    python.write_bytes(b'not executed')
    monkeypatch.setattr(install, 'installed_pins_match', lambda *args: False)
    def prohibited(*args, **kwargs): raise AssertionError('existing mismatched environment was modified')
    monkeypatch.setattr(install, 'command', prohibited)
    with pytest.raises(ValueError, match='update-existing'):
        install.install_environment(folder, ['numpy==2.3.5'])
    assert python.read_bytes() == b'not executed'


def test_source_release_does_not_package_arbitrary_user_settings(tmp_path, monkeypatch):
    release = module('release_independent_review', ROOT / 'scripts/source_release.py')
    monkeypatch.setattr(release, 'ROOT', tmp_path)
    for field in ['FILES', 'DOCUMENTS', 'ASSETS', 'DATA']:
        monkeypatch.setattr(release, field, [])
    for name in ['app_settings.json', 'cpu_settings.json', 'PARETO_CRITERIA.csv',
                 'examples/ligand_import.json', 'receptors/JAK1_3EYG.txt', 'receptors/JAK2_6BBV.txt']:
        p = tmp_path / 'settings' / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text('reviewed fixture', encoding='utf-8')
    (tmp_path / 'docs').mkdir()
    (tmp_path / 'docs/example_checksums.json').write_text('{}', encoding='utf-8')
    (tmp_path / 'settings/private.json').write_text('{"private":"not a release input"}', encoding='utf-8')
    (tmp_path / 'settings/private.csv').write_text('private user data', encoding='utf-8')
    names = {p.relative_to(tmp_path).as_posix() for p in release.source_paths()}
    assert 'settings/PARETO_CRITERIA.csv' in names
    assert 'settings/private.json' not in names and 'settings/private.csv' not in names


def test_windows_bundle_preserves_both_guides_and_uses_settings_directory(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / 'scripts'))
    bundle = module('windows_bundle_independent_review', ROOT / 'scripts/windows_bundle.py')
    monkeypatch.setattr(bundle, 'ROOT', tmp_path)
    monkeypatch.setattr(bundle, '__version__', '0.3.0')
    vina = b'synthetic executable fixture; never run'
    (tmp_path / 'tools').mkdir()
    (tmp_path / 'tools/vina.exe').write_bytes(vina)
    monkeypatch.setattr(bundle, 'VINA_SHA256', hashlib.sha256(vina).hexdigest())
    files = {'README.md': b'English guide\n', 'README_RU.md': 'Русское руководство\n'.encode('utf-8'),
             'THIRD_PARTY_NOTICES.md': b'Preserve attribution\n',
             'settings/app_settings.json': b'{"vina_executable":"vina"}\n',
             'settings/cpu_settings.json': b'{"cpu_budget":4,"cpu_per_job":1}\n'}
    for name, content in files.items():
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content)
    monkeypatch.setattr(bundle, 'source_paths', lambda: [tmp_path / name for name in files])
    monkeypatch.setattr(bundle, 'source_bytes', lambda path: path.read_bytes())
    bundle.main()
    with zipfile.ZipFile(tmp_path / 'dist/DockScreen_0.3.0-Windows-with-Vina.zip') as archive:
        assert archive.read('DockScreen/README.md') == files['README.md']
        assert archive.read('DockScreen/README_RU.md') == files['README_RU.md']
        assert b'tools/vina.exe' in archive.read('DockScreen/settings/app_settings.json')
        assert 'DockScreen/app_settings.json' not in archive.namelist()
        assert 'DockScreen/tools/README.md' not in archive.namelist()

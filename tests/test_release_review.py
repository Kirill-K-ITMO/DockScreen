"""Publication layout and failure-path regressions, without fake docking claims."""
import csv
import json
from pathlib import Path
import shutil
import sys
from types import SimpleNamespace

import pytest


def test_optional_html_error_keeps_completed_calculations(tmp_path, monkeypatch):
    from src.screening import run_screen
    from src.reporting.docking import ReportGenerator
    def broken_report(self, *args, **kwargs):
        Path(kwargs['output_file']).write_text('incomplete', encoding='utf-8')
        raise OSError('test report write failure')
    monkeypatch.setattr(ReportGenerator, 'generate_html_report', broken_report)
    docker = SimpleNamespace(run_docking=lambda **kwargs: {'row_000001': {'R': {'affinity': -9}}},
        _save_results_json=lambda: None, seed=42, timeout=1, vina_version='Mock adapter',
        stats={}, last_batch_dir=None, cpu_pool=SimpleNamespace(snapshot=lambda: {}))
    report = run_screen(tmp_path, [('sample', 'CCO')], ['R'], docker)
    run = Path(report['run_dir'])
    assert report['successful_pairs'] == 1 and report['failed_pairs'] == 0
    assert json.loads((run/'summary.json').read_text(encoding='utf-8')) == report
    assert report['reporting_errors'] == [{'format':'html','error':'test report write failure'}]
    assert not (run/'report.html').exists() and not (run/'.report.html.part').exists()
    with (run/'scores.csv').open(encoding='utf-8', newline='') as stream:
        assert next(csv.DictReader(stream))['affinity_kcal_mol'] == '-9'


def test_profiles_without_default_require_explicit_selection(tmp_path, monkeypatch, capsys):
    import main
    from src.docking.vina import AutoDockVina
    (tmp_path/'data/proteins').mkdir(parents=True)
    (tmp_path/'data/configs/R').mkdir(parents=True)
    (tmp_path/'data/proteins/R.pdbqt').write_bytes(b'fixture; no calculation is started')
    (tmp_path/'data/configs/R/deep.txt').write_text('exhaustiveness=64\n', encoding='utf-8')
    (tmp_path/'data/ligands.csv').write_text('name,smiles\nsample,CCO\n', encoding='utf-8')
    def probe(docker):
        docker.vina_executable = sys.executable
        docker.vina_version = 'Mock adapter'
    monkeypatch.setattr(AutoDockVina, '_check_vina', probe)
    monkeypatch.setattr(sys, 'argv', ['main.py', '--check', '--project', str(tmp_path)])
    assert main.main() == 1
    assert 'Select the intended site/protocol with --targets: R@deep' in capsys.readouterr().out
    assert not (tmp_path/'output/runs').exists()


def test_ligand_alias_cleanup_does_not_report_false_success(tmp_path, monkeypatch):
    from src.preparation.ligands import LigandConverter
    converter = LigandConverter(tmp_path)
    path = converter.output_dir/'sample.pdbqt'
    path.write_bytes(b'test alias')
    original = Path.unlink
    def denied(self, *args, **kwargs):
        if self == path:
            raise PermissionError('test locked alias')
        return original(self, *args, **kwargs)
    monkeypatch.setattr(Path, 'unlink', denied)
    assert converter.clear_cache(confirm=True) is False
    assert path.exists()


def release_copy(tmp_path):
    import scripts.source_release as release
    root = release.ROOT
    for path in release.source_paths():
        target = tmp_path/path.relative_to(root)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    return release


def test_public_layout_ignores_local_history_and_unreviewed_data(tmp_path, monkeypatch):
    release = release_copy(tmp_path)
    for name in ('docs/.env', 'docs/local.db', 'docs/STATUS.md', 'docs/provenance/private.json',
                 'data/private_library.csv', 'assets/local.zip', 'scripts/__pycache__/local.py'):
        path = tmp_path/name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('private fixture', encoding='utf-8')
    monkeypatch.setattr(release, 'ROOT', tmp_path)
    names = {p.relative_to(tmp_path).as_posix() for p in release.source_paths()}
    assert not any(n.startswith('docs/provenance/') or n.endswith(('.db','.env','.zip')) for n in names)
    assert 'docs/STATUS.md' not in names and 'data/private_library.csv' not in names
    assert 'assets/dockscreen-logo.svg' in names
    assert 'data/receptor_sources.json' in names
    assert release.source_bytes(tmp_path/'app_settings.json') == b'{\n  "vina_executable": "vina"\n}\n'


def test_public_builder_rejects_modified_example_data(tmp_path, monkeypatch):
    release = release_copy(tmp_path)
    (tmp_path/'data/ligands.csv').write_text('name,smiles\nprivate,CCO\n', encoding='utf-8')
    monkeypatch.setattr(release, 'ROOT', tmp_path)
    with pytest.raises(ValueError, match='Example data changed'):
        release.source_paths()

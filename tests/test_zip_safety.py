"""Result ZIP publication must never replace scientific inputs or race winners."""
import json
import os
from pathlib import Path
from types import SimpleNamespace
import zipfile

import pytest

from src.core.project import ProjectUtils


def make_run(root, *, results=None, summary=None):
    run = root / 'output/runs/screening-test'
    run.mkdir(parents=True)
    (run / 'results.json').write_text(json.dumps(results or {}), encoding='utf-8')
    (run / 'summary.json').write_text(json.dumps(summary or {}), encoding='utf-8')
    return run


def old_zip(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('old.txt', b'previous archive')
    return path.read_bytes()


def test_relative_destination_uses_project_and_uppercase_suffix(tmp_path, monkeypatch):
    root = tmp_path / 'project'
    run = make_run(root)
    monkeypatch.chdir(tmp_path)
    destination = ProjectUtils(root).export_results_to_zip(Path('exports/result.ZIP'), run_dir=run)
    assert destination == root / 'exports/result.ZIP'
    assert zipfile.is_zipfile(destination)
    assert not (tmp_path / 'exports').exists()


@pytest.mark.parametrize('folder', ['data', 'src', 'docs', 'tests', 'scripts', 'assets',
    'licenses', '.git', '.venv', '.calculation_cache', 'output/runs', 'output/inputs',
    'output/prepared', 'output/docking_results', 'output/cache'])
def test_protected_directories_never_overwritten(tmp_path, folder):
    run = make_run(tmp_path)
    source = tmp_path / folder / 'scientific.zip'
    original = old_zip(source)
    with pytest.raises(ValueError, match='protected'):
        ProjectUtils(tmp_path).export_results_to_zip(source, run_dir=run, overwrite=True)
    assert source.read_bytes() == original


@pytest.mark.parametrize('suffix', ['.csv', '.pdbqt', '.json', ''])
def test_non_zip_destination_preserves_source(tmp_path, suffix):
    run = make_run(tmp_path)
    source = tmp_path / ('source' + suffix)
    source.write_bytes(b'unchanged')
    with pytest.raises(ValueError, match='suffix'):
        ProjectUtils(tmp_path).export_results_to_zip(source, run_dir=run, overwrite=True)
    assert source.read_bytes() == b'unchanged'


def test_existing_archive_requires_explicit_overwrite(tmp_path):
    run = make_run(tmp_path)
    destination = tmp_path / 'result.zip'
    original = old_zip(destination)
    with pytest.raises(FileExistsError):
        ProjectUtils(tmp_path).export_results_to_zip(destination, run_dir=run)
    assert destination.read_bytes() == original
    ProjectUtils(tmp_path).export_results_to_zip(destination, run_dir=run, overwrite=True)
    with zipfile.ZipFile(destination) as archive:
        assert 'PROVENANCE.json' in archive.namelist()
        assert 'old.txt' not in archive.namelist()


def test_explicit_overwrite_rejects_non_archive(tmp_path):
    run = make_run(tmp_path)
    destination = tmp_path / 'not-really.zip'
    destination.write_bytes(b'original scientific data')
    with pytest.raises(ValueError, match='regular ZIP'):
        ProjectUtils(tmp_path).export_results_to_zip(destination, run_dir=run, overwrite=True)
    assert destination.read_bytes() == b'original scientific data'


def test_bad_metadata_precedes_existing_destination_check(tmp_path):
    run = make_run(tmp_path)
    (run / 'results.json').write_text('{broken', encoding='utf-8')
    destination = tmp_path / 'result.zip'
    original = old_zip(destination)
    with pytest.raises(json.JSONDecodeError):
        ProjectUtils(tmp_path).export_results_to_zip(destination, run_dir=run)
    assert destination.read_bytes() == original


@pytest.mark.parametrize('reference', ['input_csv', 'output_file', 'input_files'])
def test_metadata_reference_collision_rejected_even_without_pose_export(tmp_path, reference):
    source = tmp_path / 'external-source.zip'
    original = old_zip(source)
    if reference == 'input_csv':
        run = make_run(tmp_path, summary={'input_csv': str(source)})
    else:
        row = {reference: {'ligand': str(source)} if reference == 'input_files' else str(source)}
        run = make_run(tmp_path, results={'L': {'R': row}})
    with pytest.raises(ValueError, match='collides'):
        ProjectUtils(tmp_path).export_results_to_zip(source, run_dir=run,
            include_docking_pdbqt=False, overwrite=True)
    assert source.read_bytes() == original


def test_default_publication_does_not_replace_concurrent_file(tmp_path, monkeypatch):
    run = make_run(tmp_path)
    destination = tmp_path / 'race.zip'
    link = os.link

    def competing_writer(source, target, **kwargs):
        destination.write_bytes(b'concurrent original')
        return link(source, target, **kwargs)

    monkeypatch.setattr(os, 'link', competing_writer)
    with pytest.raises(FileExistsError):
        ProjectUtils(tmp_path).export_results_to_zip(destination, run_dir=run)
    assert destination.read_bytes() == b'concurrent original'
    assert not list(tmp_path.glob('.archive-*.tmp'))


@pytest.mark.parametrize('parent_link', [False, True])
def test_destination_symlink_or_linked_parent_rejected(tmp_path, parent_link):
    root = tmp_path / 'project'
    run = make_run(root)
    external = tmp_path / 'external'
    external.mkdir()
    source = external / 'existing.zip'
    original = old_zip(source)
    link = root / ('linked-parent' if parent_link else 'linked.zip')
    try:
        link.symlink_to(external if parent_link else source, target_is_directory=parent_link)
    except (OSError, NotImplementedError):
        pytest.skip('Creating symlinks is unavailable to this test account')
    destination = link / 'existing.zip' if parent_link else link
    with pytest.raises(ValueError, match='symlinks or junctions'):
        ProjectUtils(root).export_results_to_zip(destination, run_dir=run, overwrite=True)
    assert source.read_bytes() == original


def test_windows_reparse_parent_rejected_without_following_it(tmp_path, monkeypatch):
    run = make_run(tmp_path)
    parent = tmp_path / 'junction'
    parent.mkdir()
    real_lstat = Path.lstat

    def reparse_lstat(path, *args, **kwargs):
        info = real_lstat(path, *args, **kwargs)
        if path == parent:
            return SimpleNamespace(st_mode=info.st_mode, st_file_attributes=0x400)
        return info

    monkeypatch.setattr(Path, 'lstat', reparse_lstat)
    with pytest.raises(ValueError, match='symlinks or junctions'):
        ProjectUtils(tmp_path).export_results_to_zip(parent / 'result.zip', run_dir=run)
    assert not (parent / 'result.zip').exists()

"""Shortlist math and compact ZIP contracts; these tests do not run docking."""
import csv
import hashlib
import json
import math
from pathlib import Path
import zipfile

import pytest

from src.core.project import ProjectUtils
from src.reporting.hits import export_hits


def record(score=-9, target='R@small', name='соединение, один', scoring='vina'):
    return dict(affinity=score, target_id=target, input_name=name, smiles='CCO',
        evaluation_id='eval', spec={'options': {'scoring': scoring, 'exhaustiveness': '12'},
        'receptor_sha': 'receptor-hash'}, config_sha256='config-hash')


def read_csv(path):
    with Path(path).open(encoding='utf-8', newline='') as stream:
        reader = csv.DictReader(stream)
        return reader.fieldnames, list(reader)


def test_hits_units_duplicates_and_empty_targets(tmp_path):
    data = {'row1': {'R@small': record()}, 'row2': {'R@small': record()},
            'weak': {'R@small': record(-7)}}
    exports = export_hits(data, tmp_path, targets=['R@small', 'R@empty'])
    fields, rows = read_csv(exports['R@small']['csv'])
    assert fields == ['name', 'smiles', 'dG', 'Ki']
    assert len(rows) == exports['R@small']['count'] == 2
    assert rows[0]['name'] == 'соединение, один'
    assert 0.2 < float(rows[0]['Ki']) < 0.3
    assert float(rows[0]['dG']) == -9
    assert read_csv(exports['R@empty']['csv'])[1] == []
    notes = json.loads(Path(exports['R@small']['notes']).read_text(encoding='utf-8'))
    assert notes['temperature_K'] == 298.15
    assert 'not experimental' in notes['interpretation']
    assert notes['provenance'][0]['config_sha256'] == 'config-hash'


def test_hits_threshold_uses_unrounded_values(tmp_path):
    factor = 8.314463 * 298.15 / 4184
    scores = [math.log(1e-6 * multiplier) * factor for multiplier in (0.999999, 1, 1.000001)]
    data = {str(i): {'R@small': record(score, name=str(i))} for i, score in enumerate(scores)}
    exported = export_hits(data, tmp_path)['R@small']
    assert [row['name'] for row in read_csv(exported['csv'])[1]] == ['0', '1']


def test_hits_invalid_scores_and_success_only(tmp_path):
    values = [None, float('nan'), float('inf'), -float('inf'), True, -1e8, 1e8]
    data = {str(i): {'R@small': record(score)} for i, score in enumerate(values)}
    failed = record(-9)
    failed['status'] = 'docking_failed'
    data['failed'] = {'R@small': failed}
    assert export_hits(data, tmp_path)['R@small']['count'] == 0


def test_hits_mixed_scoring_fails_before_publication(tmp_path):
    data = {'a': {'R@small': record()}, 'b': {'R@small': record(scoring='vinardo')}}
    with pytest.raises(ValueError, match='Mixed scoring'):
        export_hits(data, tmp_path, targets=['empty'])
    assert list(tmp_path.iterdir()) == []


def test_hits_unsafe_target_names_stay_inside_export(tmp_path):
    exports = export_hits({}, tmp_path, targets=['../R', 'R/a', 'R:a', 'Р@профиль'])
    names = [Path(item['csv']).name for item in exports.values()]
    assert len(names) == len(set(names)) == 4
    assert all(Path(item['csv']).parent == tmp_path for item in exports.values())


def make_run(root, name='screening-one', score=-9):
    run = root / 'output/runs' / name
    run.mkdir(parents=True)
    pose = root / 'output/docking_results/by_id/eval/pose.pdbqt'
    pose.parent.mkdir(parents=True, exist_ok=True)
    pose.write_bytes(b'POSE')
    data = record(score)
    data.update(output_file=str(pose), artifact_sha=hashlib.sha256(b'POSE').hexdigest())
    (run / 'results.json').write_text(json.dumps({'row': {'R@small': data}}), encoding='utf-8')
    (run / 'summary.json').write_text('{}')
    (run / 'preparation.json').write_text('[]')
    (run / 'scores.csv').write_text('name,score\na,-9\n')
    (run / 'input.csv').write_text('name,smiles\na,CCO\n')
    (run / 'report.html').write_text('<html>one</html>')
    export_hits({'row': {'R@small': data}}, run / 'hits')
    return run, pose


def test_zip_one_run_compact_provenance_and_manifest(tmp_path):
    run, pose = make_run(tmp_path)
    other = tmp_path / 'output/runs/screening-other'
    other.mkdir()
    (other / 'private.txt').write_text('unrelated')
    (tmp_path / 'output/experiments.db').write_bytes(b'NOT A DATABASE')
    for folder in ('.calculation_cache', 'output/inputs', 'output/prepared'):
        path = tmp_path / folder
        path.mkdir(parents=True, exist_ok=True)
        (path / 'secret').write_text('excluded')
    output = ProjectUtils(tmp_path).export_results_to_zip(run_dir=run)
    with zipfile.ZipFile(output) as archive:
        names = archive.namelist()
        assert 'run/results.json' in names and 'run/input.csv' in names
        assert any(n.startswith('run/hits/') and n.endswith('.csv') for n in names)
        assert sum(n.startswith('poses/') for n in names) == 1
        assert not any('experiments.db' in n or 'secret' in n or 'screening-other' in n for n in names)
        manifest = json.loads(archive.read('MANIFEST.json'))
        for name, entry in manifest['files'].items():
            assert hashlib.sha256(archive.read(name)).hexdigest() == entry['sha256']
        assert manifest['missing_artifacts'] == []
        assert json.loads(archive.read('PROVENANCE.json'))['results'][0]['config_sha256'] == 'config-hash'


def test_zip_flags_apply_within_runs_and_missing_pose_visible(tmp_path):
    run, pose = make_run(tmp_path)
    pose.unlink()
    output = ProjectUtils(tmp_path).export_results_to_zip(run_dir=run,
        include_reports=False, include_ligands_csv=False)
    with zipfile.ZipFile(output) as archive:
        names = archive.namelist()
        assert not any(n.endswith(('.csv', '.html', '.notes.json')) for n in names)
        assert json.loads(archive.read('MANIFEST.json'))['missing_artifacts'][0]['role'] == 'pose'


def test_zip_bad_json_does_not_replace_previous_archive(tmp_path):
    run, _ = make_run(tmp_path)
    (run / 'results.json').write_text('{bad')
    destination = tmp_path / 'previous.zip'
    destination.write_bytes(b'previous')
    with pytest.raises(json.JSONDecodeError):
        ProjectUtils(tmp_path).export_results_to_zip(destination, run_dir=run)
    assert destination.read_bytes() == b'previous'


def test_zip_legacy_reports_does_not_collect_unreferenced_poses(tmp_path):
    reports = tmp_path / 'output/reports'
    reports.mkdir(parents=True)
    (reports / 'old.csv').write_text('legacy')
    poses = tmp_path / 'output/docking_results'
    poses.mkdir()
    (poses / 'private.pdbqt').write_text('unreferenced')
    archive_path = ProjectUtils(tmp_path).export_results_to_zip()
    with zipfile.ZipFile(archive_path) as archive:
        assert 'reports/old.csv' in archive.namelist()
        assert not any(n.endswith('.pdbqt') for n in archive.namelist())

import json
from pathlib import Path

import pytest

from src.admet import pipeline
from src.admet.workflow import completed_run
from src.reporting.csv_safety import load_export_metadata


@pytest.fixture
def run(tmp_path):
    folder = tmp_path / 'output/runs/screening-test'
    folder.mkdir(parents=True)
    rows = [{'row_id': i, 'label': f'row_{i:06d}', 'name': name, 'smiles': smiles}
            for i, (name, smiles) in enumerate([('=1+1', 'CCO'), ('same', 'OCC'), ('same', 'CCN'),
                                               ('bad', 'not_smiles'), ('salt', 'CCO.[Na+]')], 1)]
    (folder / 'preparation.json').write_text(json.dumps(rows), encoding='utf-8')
    results = {row['label']: {'A@site': {'affinity': -i, 'spec': {'options': {'scoring': 'vina'}}}}
               for i, row in enumerate(rows[:3], 1)}
    (folder / 'results.json').write_text(json.dumps(results), encoding='utf-8')
    (folder / 'summary.json').write_text('{}', encoding='utf-8')
    return tmp_path, folder


def fake_worker(calls, version='2.0.1', model='hash1'):
    def invoke(python, request, timeout, work_dir):
        calls.append(request)
        provenance = {'metadata': {'version': version, 'model_files_sha256': {'model.pt': model}},
                      'endpoints': {'DILI': {'type': 'classification', 'units': '-'}}}
        if request['action'] == 'probe':
            return provenance
        return {**provenance, 'predictions': {smiles: {'status': 'success', 'values': {'DILI': 0.6}}
                                              for smiles in request['smiles']}}
    return invoke


def read(folder):
    return json.loads((folder / 'admet.json').read_text(encoding='utf-8'))


def test_duplicates_cache_versions_and_original_rows(run, monkeypatch):
    root, folder = run
    source = {name: (folder / name).read_bytes() for name in ('preparation.json', 'results.json', 'summary.json')}
    calls = []
    monkeypatch.setattr(pipeline, '_invoke', fake_worker(calls))
    stats = pipeline.enrich_run(root, folder)
    assert stats['new_predictions'] == 2
    assert stats['failed'] == 2
    assert len(calls[-1]['smiles']) == 2
    data = read(folder)
    assert [row['row_id'] for row in data['rows']] == [1, 2, 3, 4, 5]
    assert data['rows'][0]['structure_id'] == data['rows'][1]['structure_id']
    assert data['rows'][0]['name'] == '=1+1'
    assert data['rows'][1]['smiles'] == 'OCC'
    assert data['rows'][3]['status'] == 'invalid_structure'
    assert data['rows'][4]['status'] == 'invalid_structure'
    assert load_export_metadata(folder / 'admet.csv') is not None
    assert "'=1+1" in (folder / 'admet.csv').read_text(encoding='utf-8')
    calls.clear()
    assert pipeline.enrich_run(root, folder)['cache_hits'] == 2
    assert [r['action'] for r in calls] == ['probe']
    monkeypatch.setattr(pipeline, '_invoke', fake_worker(calls, model='hash2'))
    assert pipeline.enrich_run(root, folder)['new_predictions'] == 2
    monkeypatch.setattr(pipeline, '_invoke', fake_worker(calls, version='changed'))
    assert pipeline.enrich_run(root, folder)['new_predictions'] == 2
    assert all((folder / name).read_bytes() == content for name, content in source.items())


def test_corrupt_cache_recomputed(run, monkeypatch):
    root, folder = run
    calls = []
    monkeypatch.setattr(pipeline, '_invoke', fake_worker(calls))
    pipeline.enrich_run(root, folder)
    cache = next((root / '.calculation_cache/admet-v1').glob('*.json'))
    payload = json.loads(cache.read_text(encoding='utf-8'))
    payload['prediction']['values']['DILI'] = 0.111
    cache.write_text(json.dumps(payload), encoding='utf-8')
    assert pipeline.enrich_run(root, folder)['new_predictions'] == 1


def test_top_n_requires_target_maintains_row_selection(run, monkeypatch):
    root, folder = run
    calls = []
    monkeypatch.setattr(pipeline, '_invoke', fake_worker(calls))
    with pytest.raises(ValueError, match='explicit'):
        pipeline.enrich_run(root, folder, top_n=1)
    result = pipeline.enrich_run(root, folder, top_n=1, target='A@site')
    assert result['selected_rows'] == 1
    assert read(folder)['rows'][2]['status'] == 'success'
    assert read(folder)['rows'][0]['status'] == 'not_selected'


@pytest.mark.parametrize('error', [RuntimeError('module unavailable'), RuntimeError('timed out')])
def test_failure_keeps_docking_and_retries(run, monkeypatch, error):
    root, folder = run
    original = (folder / 'results.json').read_bytes()
    def fail(*args):
        raise error
    monkeypatch.setattr(pipeline, '_invoke', fail)
    stats = pipeline.enrich_run(root, folder)
    assert stats['failed'] == 5
    assert stats['error'] == str(error)
    assert read(folder)['rows'][0]['values'] == {}
    assert (folder / 'results.json').read_bytes() == original
    monkeypatch.setattr(pipeline, '_invoke', fake_worker([]))
    assert pipeline.enrich_run(root, folder)['new_predictions'] == 2


@pytest.mark.parametrize('values,valid', [({'x': 0.0}, True), ({'x': None, 'y': 1}, True),
    ({'x': None}, False), ({'x': float('nan')}, False), ({'x': '0.3'}, False), ({'x': True}, False)])
def test_prediction_numeric_validation(values, valid):
    assert pipeline._valid_prediction({'status': 'success', 'values': values}) is valid


def test_structure_identity_preserves_chemistry():
    from src.core.calculation_cache import molecule_identity
    identity = lambda s: molecule_identity(s)[1]
    assert identity('CCO') == identity('[CH3:1]CO')
    assert identity('N') != identity('[NH4+]')
    assert identity('CC(O)F') != identity('C[C@H](O)F')
    assert identity('C[C@H](O)F') != identity('C[C@@H](O)F')
    assert identity('CCO') != identity('CC=O')


def test_invalid_scope_parameters_and_empty(run, monkeypatch):
    root, folder = run
    assert completed_run(root, folder) == folder
    with pytest.raises(ValueError):
        completed_run(root, root)
    for kwargs in ({'batch_size': 0}, {'batch_size': 257}, {'timeout': float('nan')}):
        with pytest.raises(ValueError):
            pipeline.enrich_run(root, folder, **kwargs)
    (folder / 'preparation.json').write_text('[]', encoding='utf-8')
    monkeypatch.setattr(pipeline, '_invoke', lambda *args: pytest.fail('No worker for empty set'))
    assert pipeline.enrich_run(root, folder)['rows'] == 0

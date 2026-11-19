"""Independent adverse-input acceptance, using a marked fake local model."""
import json

import pytest

from src.admet import pipeline


def _run(root):
    run = root / 'output/runs/screening-independent'
    run.mkdir(parents=True)
    rows = [{'row_id': i, 'label': f'row_{i:06d}', 'name': 'duplicate',
             'smiles': smiles} for i, smiles in enumerate(['CCO', 'CCN'], 1)]
    results = {r['label']: {'A': {'affinity': -i, 'spec': {
        'receptor_sha': 'same-receptor', 'engine_sha': 'engine',
        'options': {'scoring': 'vina', 'exhaustiveness': 8}}}}
        for i, r in enumerate(rows, 1)}
    for name, value in [('preparation.json', rows), ('results.json', results),
                        ('summary.json', {'receptors': ['A']})]:
        (run / name).write_text(json.dumps(value), encoding='utf-8')
    return run


def _worker(python, request, timeout, work_dir):
    provenance = {'metadata': {'version': 'FAKE-independent-test',
                              'model_files_sha256': {'model.pt': 'fake'}},
                  'endpoints': {'DILI': {'type': 'classification', 'units': '-'}}}
    if request['action'] == 'probe':
        return provenance
    return {**provenance, 'predictions': {
        s: {'status': 'success', 'values': {'DILI': 0.5}}
        for s in request['smiles']}}


@pytest.mark.parametrize('corruption', [[], None, 'unexpected', 4])
def test_malformed_cache_object_is_recomputed(tmp_path, monkeypatch, corruption):
    run = _run(tmp_path)
    monkeypatch.setattr(pipeline, '_invoke', _worker)
    pipeline.enrich_run(tmp_path, run)
    files = list((tmp_path / '.calculation_cache/admet-v1').glob('*.json'))
    files[0].write_text(json.dumps(corruption), encoding='utf-8')
    stats = pipeline.enrich_run(tmp_path, run)
    assert stats['failed'] == 0
    assert stats['cache_hits'] == 1
    assert stats['new_predictions'] == 1


@pytest.mark.parametrize('field', ['receptor_sha', 'engine_sha', 'config_sha'])
def test_top_n_rejects_distinct_scientific_protocols(tmp_path, monkeypatch, field):
    run = _run(tmp_path)
    results = json.loads((run / 'results.json').read_text(encoding='utf-8'))
    results['row_000002']['A']['spec'][field] = 'different'
    (run / 'results.json').write_text(json.dumps(results), encoding='utf-8')
    monkeypatch.setattr(pipeline, '_invoke', lambda *a: pytest.fail('Reject before worker'))
    with pytest.raises(ValueError, match='protocol'):
        pipeline.enrich_run(tmp_path, run, top_n=1, target='A')


def test_failure_artifacts_preserve_all_scientific_source_bytes(tmp_path, monkeypatch):
    run = _run(tmp_path)
    original = {p.name: p.read_bytes() for p in run.iterdir()}
    monkeypatch.setattr(pipeline, '_invoke', lambda *a: (_ for _ in ()).throw(RuntimeError('timeout test')))
    stats = pipeline.enrich_run(tmp_path, run)
    assert stats['failed'] == 2
    assert all((run / name).read_bytes() == data for name, data in original.items())
    data = json.loads((run / 'admet.json').read_text(encoding='utf-8'))
    assert all(r['status'] == 'prediction_failed' and r['values'] == {} for r in data['rows'])
    assert (run / 'admet.csv').is_file()
    assert (run / 'admet.csv.notes.json').is_file()


@pytest.mark.parametrize('include_reports', [True, False])
def test_zip_includes_admet_provenance_and_honors_report_option(tmp_path, monkeypatch, include_reports):
    import zipfile
    from src.core.project import ProjectUtils
    run = _run(tmp_path)
    monkeypatch.setattr(pipeline, '_invoke', _worker)
    pipeline.enrich_run(tmp_path, run)
    (run / 'combined_report.html').write_text('<html>independent test</html>', encoding='utf-8')
    output = ProjectUtils(tmp_path).export_results_to_zip(
        tmp_path / 'results.zip', run_dir=run, include_reports=include_reports)
    with zipfile.ZipFile(output) as archive:
        names = set(archive.namelist())
        assert 'run/admet.json' in names
        assert archive.read('run/admet.json') == (run / 'admet.json').read_bytes()
        for name in ('admet.csv', 'admet.csv.notes.json', 'combined_report.html'):
            assert ('run/' + name in names) is include_reports
        assert not any('.calculation_cache' in name for name in names)

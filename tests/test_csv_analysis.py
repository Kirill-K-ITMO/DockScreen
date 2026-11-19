"""Independent report-import/postprocessing acceptance; synthetic molecular rows."""
import csv
import hashlib
import io
import json
from pathlib import Path
import sys
import zipfile

import pytest

from src.reporting.csv_safety import write_csv


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def raw_report(path, rows, headers=('row_id', 'name', 'smiles', 'R_delta_g')):
    headers = list(headers)
    extra = [h[:-len('_delta_g')] + suffix for h in headers if h.endswith('_delta_g')
             for suffix in ('_ki', '_ki_formatted', '_pki')]
    rows = [list(r) + [''] * len(extra) for r in rows]
    headers += extra
    stream = io.StringIO(newline='')
    writer = csv.writer(stream)
    writer.writerow(headers)
    writer.writerows(rows)
    path.write_bytes(stream.getvalue().encode('utf-8-sig'))
    return path


def import_report(root, path):
    from src.reporting.csv_import import import_docking_csv
    return Path(import_docking_csv(root, path))


def test_marked_native_csv_preserves_ids_duplicate_names_missing_values_and_exact_input(tmp_path, monkeypatch):
    import src.docking.vina as vina
    import src.admet.pipeline as pipeline
    def prohibited(*args, **kwargs): raise AssertionError('import must not calculate docking or ADMET')
    monkeypatch.setattr(vina.AutoDockVina, 'run_docking', prohibited)
    monkeypatch.setattr(pipeline, 'enrich_run', prohibited)
    path = tmp_path / 'native.csv'
    write_csv(path, ['row_id', 'name', 'smiles', 'R_delta_g', 'S_delta_g',
                     'R_ki', 'R_ki_formatted', 'R_pki', 'S_ki', 'S_ki_formatted', 'S_pki'], [
        {'row_id': 10, 'name': '=1+1', 'smiles': 'CCO', 'R_delta_g': -9., 'S_delta_g': -8.},
        {'row_id': 3, 'name': 'duplicate', 'smiles': 'CCN', 'R_delta_g': -7., 'S_delta_g': None},
        {'row_id': 20, 'name': 'duplicate', 'smiles': '', 'R_delta_g': None, 'S_delta_g': None},
    ], text_columns=['name', 'smiles', 'R_ki_formatted', 'S_ki_formatted'], notes={'kind': 'docking_report'}, bom=True)
    original, original_notes = path.read_bytes(), Path(str(path) + '.notes.json').read_bytes()
    run = import_report(tmp_path, path)
    assert run.parent == tmp_path / 'output/runs'
    prep = load(run / 'preparation.json')
    assert [r['row_id'] for r in prep] == [10, 3, 20]
    assert [r['name'] for r in prep] == ['=1+1', 'duplicate', 'duplicate']
    assert [r['smiles'] for r in prep] == ['CCO', 'CCN', '']
    assert len({r['label'] for r in prep}) == 3
    assert path.read_bytes() == original
    assert Path(str(path) + '.notes.json').read_bytes() == original_notes
    assert (run / 'reports/import/source_report.csv').read_bytes() == original
    assert (run / 'reports/import/source_report.csv.notes.json').read_bytes() == original_notes
    assert (run / 'reports/import/import_metadata.json').is_file()
    assert not (run / 'admet.json').exists()
    from src.reporting.combined import build_combined_data
    data = build_combined_data(tmp_path, run, include_images=False)
    assert [r['id'] for r in data['rows']] == ['10', '3', '20']
    assert data['rows'][0]['docking']['R']['score'] == -9.
    assert data['rows'][1]['docking']['S']['score'] is None
    assert all(p['spec'].get('source_protocol') and 'unknown' in str(p['spec']['source_protocol']).lower()
               for p in data['protocols'])
    second = import_report(tmp_path, path)
    assert second != run
    assert load(second / 'preparation.json') == prep


def test_plain_csv_without_row_ids_assigns_stable_file_order_and_keeps_literal_apostrophe(tmp_path):
    path = raw_report(tmp_path / 'plain.csv', [
        ["'=1+1", 'CCO', '-8.1'], ['same', 'CCN', ''], ['same', '', '-7.0']],
        headers=('name', 'smiles', 'R_delta_g'))
    original = path.read_bytes()
    run = import_report(tmp_path, path)
    prep = load(run / 'preparation.json')
    assert [r['row_id'] for r in prep] == [1, 2, 3]
    assert prep[0]['name'] == "'=1+1"
    assert (run / 'reports/import/source_report.csv').read_bytes() == original
    assert path.read_bytes() == original


@pytest.mark.parametrize('bad_id', ['0', '-1', '1.2', 'bad', '1e2', 'True', ''])
def test_invalid_explicit_row_ids_fail_without_publishing_run(tmp_path, bad_id):
    path = raw_report(tmp_path / 'bad-id.csv', [[bad_id, 'a', 'CCO', '-8']])
    original = path.read_bytes()
    with pytest.raises(ValueError): import_report(tmp_path, path)
    assert path.read_bytes() == original
    assert not list((tmp_path / 'output/runs').glob('*/preparation.json'))


def test_duplicate_explicit_ids_rejected_while_duplicate_names_are_allowed(tmp_path):
    path = raw_report(tmp_path / 'duplicate-id.csv', [['3', 'a', 'CCO', '-8'], ['3', 'b', 'CCN', '-7']])
    with pytest.raises(ValueError): import_report(tmp_path, path)


@pytest.mark.parametrize('bad_score', ['nan', 'inf', '-inf', '1e999', 'text', '=1+1'])
def test_nonfinite_or_nonnumeric_scores_rejected(tmp_path, bad_score):
    path = raw_report(tmp_path / 'score.csv', [[1, 'a', 'CCO', bad_score]])
    with pytest.raises(ValueError): import_report(tmp_path, path)


@pytest.mark.parametrize('headers,rows', [
    (('name', 'R_delta_g'), [['a', '-8']]),
    (('name', 'smiles'), [['a', 'CCO']]),
    (('name', 'smiles', 'R_delta_g', 'R_delta_g'), [['a', 'CCO', '-8', '-7']]),
])
def test_unrecognized_or_ambiguous_report_schema_rejected(tmp_path, headers, rows):
    path = raw_report(tmp_path / 'schema.csv', rows, headers)
    with pytest.raises(ValueError): import_report(tmp_path, path)


def test_tampered_safety_sidecar_cannot_trigger_unescaping(tmp_path):
    path = tmp_path / 'marked.csv'
    write_csv(path, ['name', 'smiles', 'R_delta_g', 'R_ki', 'R_ki_formatted', 'R_pki'], [['=1+1', 'CCO', -8., '', '', '']],
              text_columns=['name', 'smiles'], notes={'kind': 'docking_report'})
    path.write_bytes(path.read_bytes().replace(b'CCO', b'CCN'))
    with pytest.raises(ValueError): import_report(tmp_path, path)


def test_imported_admet_columns_are_not_misrepresented_as_verified_model_predictions(tmp_path):
    path = raw_report(tmp_path / 'with-admet.csv', [[12, 'a', 'CCO', -8., .01, 'success']],
                      headers=('row_id', 'name', 'smiles', 'R_delta_g', 'ADMET__DILI', 'admet_status'))
    original = path.read_bytes()
    run = import_report(tmp_path, path)
    assert not (run / 'admet.json').exists()
    from src.reporting.combined import build_combined_data
    data = build_combined_data(tmp_path, run, include_images=False)
    assert data['rows'][0]['values'].get('DILI') is None
    assert (run / 'reports/import/source_report.csv').read_bytes() == original
    metadata = json.dumps(load(run / 'reports/import/import_metadata.json'), ensure_ascii=False).lower()
    assert 'admet' in metadata


def fake_local_worker(monkeypatch, calls):
    from src.admet import pipeline
    import src.docking.vina as vina
    def no_docking(*args, **kwargs): raise AssertionError('CSV postprocessing must never dock')
    monkeypatch.setattr(vina.AutoDockVina, 'run_docking', no_docking)
    endpoints = {k: {'units': '-', 'type': 'classification'}
                 for k in ('DILI', 'ClinTox', 'Bioavailability_Ma', 'hERG')}
    provenance = {'metadata': {'version': 'FAKE-csv-test'}, 'endpoints': endpoints}
    def invoke(python, request, timeout, work):
        calls.append(request['action'])
        if request['action'] == 'probe': return provenance
        return {**provenance, 'predictions': {s: {'status': 'success',
            'values': {'DILI': .2, 'ClinTox': .2, 'Bioavailability_Ma': .8, 'hERG': .1}}
            for s in request['smiles']}}
    monkeypatch.setattr(pipeline, '_invoke', invoke)


@pytest.mark.parametrize('mode', ['admet', 'pareto', 'smaa', 'pareto+smaa'])
def test_csv_workflow_fresh_local_admet_optional_pareto_smaa_and_source_immutability(tmp_path, monkeypatch, mode):
    from src.analysis.csv_workflow import analyze_csv_report
    calls = []; fake_local_worker(monkeypatch, calls)
    path = raw_report(tmp_path / 'ready.csv', [[1, 'same', 'CCO', -9.], [7, 'same', 'CCN', -8.]])
    original = path.read_bytes()
    result = analyze_csv_report(tmp_path, path, mode=mode)
    run = Path(result['run_dir'])
    assert path.read_bytes() == original
    assert (run / 'reports/import/source_report.csv').read_bytes() == original
    assert calls == ['probe', 'predict']
    assert (run / 'admet.json').is_file()
    assert result['reports'] and all(Path(p).is_file() for p in result['reports'])
    if mode == 'admet':
        assert result['pareto'] is None and result['smaa'] is None
    elif mode == 'smaa':
        assert result['pareto'] is None
        assert result['smaa']['feasible'] == 2
        assert Path(result['smaa']['report_html']).is_file()
        assert not (run/'pareto').exists()
    else:
        assert result['pareto']['total'] == result['pareto']['feasible'] == 2
        if mode == 'pareto': assert result['smaa'] is None
        else:
            assert result['smaa']['feasible'] == 2
            assert load(Path(result['smaa']['directory']) / 'results.json')['status'] == 'complete'


def test_multitarget_csv_requires_explicit_target_before_local_prediction(tmp_path, monkeypatch):
    from src.analysis.csv_workflow import analyze_csv_report
    calls = []; fake_local_worker(monkeypatch, calls)
    path = raw_report(tmp_path / 'multi.csv', [[1, 'a', 'CCO', -8., -9.]],
                      headers=('row_id', 'name', 'smiles', 'R_delta_g', 'S_delta_g'))
    with pytest.raises(ValueError): analyze_csv_report(tmp_path, path, mode='pareto+smaa')
    assert calls == []


def test_csv_workflow_does_not_claim_smaa_success_when_admet_worker_fails(tmp_path, monkeypatch):
    from src.analysis.csv_workflow import analyze_csv_report
    from src.admet import pipeline
    def broken(*args, **kwargs): raise RuntimeError('synthetic worker unavailable')
    monkeypatch.setattr(pipeline, '_invoke', broken)
    path = raw_report(tmp_path / 'failure.csv', [[1, 'a', 'CCO', -8.]])
    original = path.read_bytes()
    try:
        result = analyze_csv_report(tmp_path, path, mode='pareto+smaa')
    except (ValueError, RuntimeError):
        pass
    else:
        assert result['smaa'] is None
    assert not list((tmp_path / 'output/runs').glob('*/smaa/analysis-*'))
    assert path.read_bytes() == original


def test_terminal_csv_menu_runs_selected_mode_and_keeps_original_report(tmp_path, monkeypatch):
    from src.analysis.csv_workflow import csv_analysis_menu
    calls = []; fake_local_worker(monkeypatch, calls)
    path = raw_report(tmp_path / 'menu.csv', [[1, 'a', 'CCO', -8.]])
    original = path.read_bytes()
    class Terminal:
        def __init__(self):
            self.answers = iter([str(path), '2', '', ''])
            self.messages = []
        def input(self, prompt): return next(self.answers)
        def print(self, value, **kwargs): self.messages.append(str(value))
    terminal = Terminal()
    csv_analysis_menu(tmp_path, terminal)
    assert calls == ['probe', 'predict']
    assert len(list((tmp_path / 'output/runs').glob('*/pareto/selection-*'))) == 1
    assert not list((tmp_path / 'output/runs').glob('*/smaa/analysis-*'))
    assert path.read_bytes() == original
    assert any('pareto:' in line for line in terminal.messages)


def test_csv_cli_analyze_and_zip_include_exact_source_and_verified_admet(tmp_path, monkeypatch):
    import main
    import src.ui.streams as streams
    monkeypatch.setattr(streams, 'configure_streams', lambda: None)
    calls = []; fake_local_worker(monkeypatch, calls)
    path = raw_report(tmp_path / 'cli.csv', [[1, 'a', 'CCO', -8.]])
    original = path.read_bytes()
    archive = tmp_path / 'result.zip'
    monkeypatch.setattr(sys, 'argv', ['main.py', '--project', str(tmp_path), '--csv-analyze', str(path),
                                     '--csv-analysis-mode', 'admet', '--export-zip', str(archive)])
    assert main.main() == 0
    assert calls == ['probe', 'predict']
    assert path.read_bytes() == original
    with zipfile.ZipFile(archive) as z:
        assert z.testzip() is None
        assert z.read('run/reports/import/source_report.csv') == original
        assert 'run/admet.json' in z.namelist()
        manifest = json.loads(z.read('MANIFEST.json'))
        assert all(hashlib.sha256(z.read(n)).hexdigest() == item['sha256'] for n, item in manifest['files'].items())

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.admet.workflow import available_runs, prepare_run
from src.reporting.combined import build_combined_data


def legacy(root, name='docking-enriched'):
    run = root / 'output/runs' / name
    run.mkdir(parents=True)
    results = {label: {'R': {'selection_row_id': i, 'input_name': 'duplicate',
                            'smiles': s, 'affinity': -i}}
               for label, i, s in [('duplicate', 1, 'CCO'), ('2_duplicate', 2, 'CCN')]}
    for filename, value in [('results.json', results), ('statistics.json', {'failed': 0}),
                            ('task_outcomes.json', {k: {'R': {'status': 'success'}} for k in results})]:
        (run / filename).write_text(json.dumps(value), encoding='utf-8')
    return run


def test_menu_discovers_enriched_run_not_raw_duplicate_and_imports_without_docking(tmp_path):
    run = legacy(tmp_path)
    raw = legacy(tmp_path, 'docking-raw')
    data = json.loads((raw / 'results.json').read_text())
    for records in data.values():
        for row in records.values(): row.pop('smiles')
    (raw / 'results.json').write_text(json.dumps(data))
    before = {p.name: p.read_bytes() for p in run.iterdir()}
    assert available_runs(tmp_path) == [run]
    imported = prepare_run(tmp_path, run)
    assert imported != run
    assert all((run / n).read_bytes() == b for n, b in before.items())
    assert (imported / 'results.json').read_bytes() == before['results.json']
    rows = json.loads((imported / 'preparation.json').read_text())
    assert [r['row_id'] for r in rows] == [1, 2]
    assert [r['name'] for r in rows] == ['duplicate', 'duplicate']
    assert [r['smiles'] for r in rows] == ['CCO', 'CCN']
    assert len(build_combined_data(tmp_path, imported)['rows']) == 2
    assert prepare_run(tmp_path, imported) == imported


def test_unrecoverable_failed_rows_rejected_instead_of_silently_lost(tmp_path):
    run = legacy(tmp_path)
    outcomes = json.loads((run / 'task_outcomes.json').read_text())
    outcomes['fully_failed'] = {'R': {'status': 'timeout'}}
    (run / 'task_outcomes.json').write_text(json.dumps(outcomes))
    with pytest.raises(ValueError, match='failed rows'):
        prepare_run(tmp_path, run)
    assert available_runs(tmp_path) == []


def test_conflicting_identity_and_scope_rejected(tmp_path):
    run = legacy(tmp_path)
    results = json.loads((run / 'results.json').read_text())
    results['duplicate']['S'] = {**results['duplicate']['R'], 'smiles': 'CC'}
    (run / 'results.json').write_text(json.dumps(results))
    with pytest.raises(ValueError, match='Conflicting'):
        prepare_run(tmp_path, run)
    with pytest.raises(ValueError, match='inside'):
        prepare_run(tmp_path, tmp_path)


def test_interactive_menu_saves_original_smiles_and_failed_rows(tmp_path, monkeypatch):
    from src.ui.docking_menu import docking_menu
    import src.core.preflight as preflight
    import src.reporting.hits as hits
    monkeypatch.setattr(preflight, 'check_run', lambda *a, **k: SimpleNamespace(ready=True))
    monkeypatch.setattr(preflight, 'display', lambda *a, **k: None)
    monkeypatch.setattr(hits, 'export_hits', lambda *a, **k: None)
    (tmp_path / 'data').mkdir()
    (tmp_path / 'data/ligands.csv').write_text('name,smiles\nduplicate,OCC\nduplicate,CCN\n')
    saved = {}
    class Docker:
        stats = {'failed': 0}
        def get_targets(self): return [{'id': 'R'}]
        def get_config(self, target): return Path('config')
        def run_docking(self, **kwargs):
            saved['results'] = {k: {'R': {'affinity': -1}} for k in kwargs['ligand_paths']}
            return saved['results']
        def _save_results_json(self):
            self.last_batch_dir = tmp_path / 'output/runs/docking-new'
            self.last_batch_dir.mkdir(parents=True)
            (self.last_batch_dir / 'results.json').write_text(json.dumps(saved['results']))
    def prepare(smiles):
        if smiles == 'CCN': raise ValueError('Test preparation failure')
        return {'path': 'fake.pdbqt'}
    answers = iter(['all', 'all', '', '', '1', 'no', 'yes', 'no', 'no'])
    console = SimpleNamespace(print=lambda *a, **k: None, input=lambda *a: next(answers))
    database = SimpleNamespace(add_experiment=lambda **k: 1, finish_experiment=lambda *a: None)
    app = SimpleNamespace(project_root=tmp_path, docker=Docker(), converter=SimpleNamespace(prepare_cached=prepare),
                          database=database, _save_results_to_db=lambda *a: None)
    docking_menu(app, console)
    run = app.docker.last_batch_dir
    prep = json.loads((run / 'preparation.json').read_text())
    assert [r['smiles'] for r in prep] == ['OCC', 'CCN']
    assert [r['status'] for r in prep] == ['prepared', 'preparation_failed']
    assert saved['results']['duplicate']['R']['smiles'] == 'OCC'
    assert json.loads((run / 'summary.json').read_text())['failed_pairs'] == 1
    assert available_runs(tmp_path) == [run]

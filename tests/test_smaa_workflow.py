"""Independent saved-run SMAA integration: no docking, models or GUI involved."""
import csv
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import zipfile

import pytest

from src.reporting.pareto_csv import HEADERS


@pytest.fixture
def saved_smaa_run(tmp_path):
    run = tmp_path / 'output/runs/screening-smaa'
    run.mkdir(parents=True)
    prep = [{'row_id': i, 'label': f'row_{i}', 'name': '=1+1' if i == 1 else 'duplicate',
             'smiles': 'CCO', 'status': 'prepared'} for i in range(1, 6)]
    scores = [-9., -8., -7., -10., -6.]
    results = {r['label']: {'R': {'affinity': score, 'spec': {'options': {'scoring': 'vina'}}}}
               for r, score in zip(prep, scores)}
    for name, value in [('preparation.json', prep), ('results.json', results), ('summary.json', {'receptors': ['R']})]:
        (run / name).write_text(json.dumps(value), encoding='utf-8')
    admet = {'metadata': {'version': 'FAKE-smaa-fixture', 'input_sha256': {
        n: hashlib.sha256((run / n).read_bytes()).hexdigest()
        for n in ('preparation.json', 'results.json', 'summary.json')}},
        'endpoints': {'DILI': {'units': '-', 'type': 'classification'}},
        'rows': [{**{k: row[k] for k in ('row_id', 'name', 'smiles')}, 'status': 'success',
                  'values': {'DILI': value}} for row, value in zip(prep, [.2, .3, .5, None, .8])]}
    (run / 'admet.json').write_text(json.dumps(admet), encoding='utf-8')
    stream = io.StringIO(newline='')
    writer = csv.writer(stream, delimiter=';')
    writer.writerow(HEADERS)
    writer.writerow(['docking_score', 'сравнивать', 'минимум', '', '-7', '', '', ''])
    writer.writerow(['DILI', 'сравнивать', 'минимум', '', '0.5', '', '', ''])
    criteria = tmp_path / 'criteria.csv'
    criteria.write_bytes(stream.getvalue().encode('utf-8-sig'))
    return tmp_path, run, criteria, tmp_path / 'smaa.json'


def workflow():
    from src.analysis.smaa_workflow import create_smaa_template, run_smaa
    return create_smaa_template, run_smaa


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def configure(fixture):
    root, run, criteria, settings = fixture
    create, _ = workflow()
    create(root, run, criteria, settings, target='R')
    doc = load(settings)
    doc['sampling'].update(iterations=131, seed=77, top_n=10)
    settings.write_text(json.dumps(doc), encoding='utf-8')
    return doc


def test_template_separate_explicit_binding_and_preserves_user_file(saved_smaa_run):
    root, run, criteria, settings = saved_smaa_run
    create, _ = workflow()
    before = {p.name: p.read_bytes() for p in run.iterdir()}
    create(root, run, criteria, settings, target='R')
    assert not (run / 'smaa').exists()
    doc = load(settings)
    assert doc['schema_version'] == 1
    assert doc['criteria_sha256'] == hashlib.sha256(criteria.read_bytes()).hexdigest()
    assert doc['protocol_id'].startswith('R:')
    assert doc['sampling']['weight_distribution'] == 'Dirichlet'
    assert all(s['alpha'] == 1. for s in doc['scales'])
    # Docking scale includes -6, although that row fails docking/DILI filters.
    docking = next(s for s in doc['scales'] if s['key'] == 'docking_score')
    assert docking['best'] == -10. and docking['worst'] == -6.
    assert docking.get('origin')
    original = settings.read_bytes()
    with pytest.raises((ValueError, FileExistsError)):
        create(root, run, criteria, settings, target='R')
    assert settings.read_bytes() == original
    assert all((run / n).read_bytes() == b for n, b in before.items())


def test_all_source_rows_dominated_included_excluded_null_csv_safe_and_exact_snapshots(saved_smaa_run):
    root, run, criteria, settings = saved_smaa_run
    configure(saved_smaa_run)
    before = {p.name: p.read_bytes() for p in run.iterdir() if p.is_file()}
    _, execute = workflow()
    result = execute(root, run, criteria, settings, target='R')
    folder = Path(result['directory'])
    assert folder.parent == run / 'smaa'
    assert folder.name.startswith('analysis-')
    saved = load(folder / 'results.json')
    assert saved['status'] == 'complete'
    assert [r['row_id'] for r in saved['rows']] == [1, 2, 3, 4, 5]
    assert len({r['id'] for r in saved['rows']}) == 5
    assert sum(r['name'] == 'duplicate' for r in saved['rows']) == 4
    assert result['total'] == 5 and result['feasible'] == 3 and result['front'] == 1
    assert result['effective_top_n'] == 3
    assert saved['rows'][1]['pareto_status'] == 'dominated'
    assert saved['rows'][1]['smaa']['expected_rank'] == 2.
    assert saved['rows'][2]['smaa']['expected_rank'] == 3.  # exact DILI boundary passes
    for r in saved['rows'][3:]:
        assert r['smaa'] is None
        assert r['exclusion_reasons']
    assert (folder / 'criteria.csv').read_bytes() == criteria.read_bytes()
    assert (folder / 'settings.json').read_bytes() == settings.read_bytes()
    assert all((run / n).read_bytes() == b for n, b in before.items())
    table = list(csv.DictReader((folder / 'candidates.csv').open(encoding='utf-8-sig')))
    assert table[0]['name'] == "'=1+1"
    assert saved['rows'][0]['name'] == '=1+1'
    assert (folder / 'rank_acceptability.csv').is_file()
    assert (folder / 'metadata.json').is_file()
    assert (folder / 'SUMMARY.txt').is_file()
    second = execute(root, run, criteria, settings, target='R')
    assert second['directory'] != result['directory']
    assert load(Path(second['directory']) / 'results.json')['rows'] == saved['rows']


def test_cancellation_cannot_publish_success(saved_smaa_run):
    root, run, criteria, settings = saved_smaa_run
    configure(saved_smaa_run)
    _, execute = workflow()
    def cancel(done, total): raise KeyboardInterrupt
    with pytest.raises(KeyboardInterrupt):
        execute(root, run, criteria, settings, target='R', progress=cancel)
    assert not list((run / 'smaa').glob('analysis-*'))
    for p in (run / 'smaa').rglob('results.json'):
        assert load(p).get('status') != 'complete'


@pytest.mark.parametrize('mutation', ['criteria_hash', 'protocol', 'missing_scale', 'duplicate_scale', 'bad_direction', 'invalid_sampling'])
def test_bound_inputs_and_invalid_preferences_fail_before_success(saved_smaa_run, mutation):
    root, run, criteria, settings = saved_smaa_run
    doc = configure(saved_smaa_run)
    if mutation == 'criteria_hash': doc['criteria_sha256'] = '0' * 64
    elif mutation == 'protocol': doc['protocol_id'] = 'wrong'
    elif mutation == 'missing_scale': doc['scales'].pop()
    elif mutation == 'duplicate_scale': doc['scales'].append(doc['scales'][0])
    elif mutation == 'bad_direction': doc['scales'][0]['direction'] = 'max'
    elif mutation == 'invalid_sampling': doc['sampling']['iterations'] = 0
    settings.write_text(json.dumps(doc), encoding='utf-8')
    _, execute = workflow()
    with pytest.raises(ValueError): execute(root, run, criteria, settings, target='R')
    assert not list((run / 'smaa').glob('analysis-*'))


def test_zip_contains_complete_analysis_and_skips_incomplete(saved_smaa_run):
    root, run, criteria, settings = saved_smaa_run
    configure(saved_smaa_run)
    _, execute = workflow()
    result = execute(root, run, criteria, settings, target='R')
    incomplete = run / 'smaa/.incomplete-synthetic'
    incomplete.mkdir()
    (incomplete / 'results.json').write_text('{}')
    from src.core.project import ProjectUtils
    archive = ProjectUtils(root).export_results_to_zip(root / 'result.zip', run_dir=run, include_docking_pdbqt=False)
    with zipfile.ZipFile(archive) as z:
        assert z.testzip() is None
        prefix = 'run/smaa/' + Path(result['directory']).name + '/'
        assert prefix + 'results.json' in z.namelist()
        assert prefix + 'rank_acceptability.csv' in z.namelist()
        assert not any('.incomplete' in n for n in z.namelist())
        manifest = json.loads(z.read('MANIFEST.json'))
        assert all(hashlib.sha256(z.read(n)).hexdigest() == meta['sha256'] for n, meta in manifest['files'].items())


def test_cli_template_and_run_saved_data_only(saved_smaa_run):
    root, run, criteria, settings = saved_smaa_run
    main = Path(__file__).resolve().parents[1] / 'main.py'
    before = {p.name: p.read_bytes() for p in run.iterdir() if p.is_file()}
    command = [sys.executable, '-B', str(main), '--project', str(root), '--pareto-criteria', str(criteria),
               '--smaa-settings', str(settings), '--pareto-target', 'R']
    created = subprocess.run(command + ['--smaa-template', str(run)], capture_output=True, text=True, timeout=30)
    assert created.returncode == 0, created.stdout + created.stderr
    assert not (run / 'smaa').exists()
    doc = load(settings); doc['sampling']['iterations'] = 131
    settings.write_text(json.dumps(doc), encoding='utf-8')
    executed = subprocess.run(command + ['--smaa-run', str(run)], capture_output=True, text=True, timeout=30)
    assert executed.returncode == 0, executed.stdout + executed.stderr
    assert len(list((run / 'smaa').glob('analysis-*'))) == 1
    assert not (root / '.calculation_cache').exists()
    assert all((run / n).read_bytes() == b for n, b in before.items())


def test_empty_feasible_set_keeps_every_excluded_row_unranked(saved_smaa_run):
    root, run, criteria, settings = saved_smaa_run
    criteria.write_bytes(criteria.read_bytes().replace(b'-7', b'-100'))
    configure(saved_smaa_run)
    _, execute = workflow()
    result = execute(root, run, criteria, settings, target='R')
    assert result['feasible'] == result['front'] == result['effective_top_n'] == 0
    doc = load(Path(result['directory']) / 'results.json')
    assert doc['configuration']['completed_scenarios'] == 0
    assert len(doc['rows']) == 5
    assert all(r['smaa'] is None and r['exclusion_reasons'] for r in doc['rows'])


def test_no_objectives_cannot_be_misrepresented_as_preference_analysis(saved_smaa_run):
    root, run, criteria, settings = saved_smaa_run
    criteria.write_bytes(criteria.read_bytes().decode('utf-8-sig').replace('сравнивать;минимум', 'ограничение;').encode('utf-8-sig'))
    create, execute = workflow()
    with pytest.raises(ValueError): create(root, run, criteria, settings, target='R')
    assert not list((run / 'smaa').glob('analysis-*'))


def test_settings_reject_changed_saved_data_without_rewriting_it(saved_smaa_run):
    root, run, criteria, settings = saved_smaa_run
    configure(saved_smaa_run)
    admet = load(run / 'admet.json')
    admet['rows'][0]['values']['DILI'] = .25
    (run / 'admet.json').write_text(json.dumps(admet), encoding='utf-8')
    before = (run / 'admet.json').read_bytes()
    _, execute = workflow()
    with pytest.raises(ValueError): execute(root, run, criteria, settings, target='R')
    assert (run / 'admet.json').read_bytes() == before
    assert not list((run / 'smaa').glob('analysis-*'))


@pytest.mark.parametrize('bad', ['not-a-number', True])
def test_nonnumeric_saved_properties_are_excluded_not_ranked(saved_smaa_run, bad):
    root, run, criteria, settings = saved_smaa_run
    admet = load(run / 'admet.json')
    admet['rows'][1]['values']['DILI'] = bad
    (run / 'admet.json').write_text(json.dumps(admet), encoding='utf-8')
    configure(saved_smaa_run)
    _, execute = workflow()
    result = execute(root, run, criteria, settings, target='R')
    assert result['feasible'] == 2
    row = load(Path(result['directory']) / 'results.json')['rows'][1]
    assert row['smaa'] is None and row['exclusion_reasons']


def test_terminal_menu_creates_template_then_runs_without_drawing_or_predictions(saved_smaa_run, monkeypatch):
    root, run, criteria, settings = saved_smaa_run
    from src.analysis.smaa_workflow import smaa_menu
    import src.reporting.combined as combined
    import src.admet.pipeline as pipeline
    import src.docking.vina as vina
    def prohibited(*args, **kwargs):
        raise AssertionError('SMAA must use saved properties only')
    monkeypatch.setattr(combined, '_drawing', prohibited)
    monkeypatch.setattr(pipeline, 'enrich_run', prohibited)
    monkeypatch.setattr(vina.AutoDockVina, 'run_docking', prohibited)
    class Terminal:
        def __init__(self, answers):
            self.answers = iter(answers)
            self.messages = []
        def input(self, prompt): return next(self.answers)
        def print(self, value, **kwargs): self.messages.append(str(value))
    terminal = Terminal(['1', '1', str(criteria), str(settings), '1'])
    smaa_menu(root, terminal)
    assert settings.exists() and not (run / 'smaa').exists()
    doc = load(settings); doc['sampling']['iterations'] = 131
    settings.write_text(json.dumps(doc), encoding='utf-8')
    terminal = Terminal(['1', '2', str(criteria), str(settings), '1'])
    smaa_menu(root, terminal)
    assert len(list((run / 'smaa').glob('analysis-*'))) == 1
    assert any('131/131' in m for m in terminal.messages)


def test_source_change_during_scenarios_aborts_publication(saved_smaa_run):
    root, run, criteria, settings = saved_smaa_run
    configure(saved_smaa_run)
    _, execute = workflow()
    changed = False
    def mutate(done, total):
        nonlocal changed
        if done and not changed:
            (run / 'task_outcomes.json').write_text('{}', encoding='utf-8')
            changed = True
    with pytest.raises(ValueError):
        execute(root, run, criteria, settings, target='R', progress=mutate)
    assert changed
    assert not list((run / 'smaa').glob('analysis-*'))


def single_goal_csv(path, direction='минимум', low='', high='', upper='-7'):
    stream = io.StringIO(newline='')
    writer = csv.writer(stream, delimiter=';')
    writer.writerow(HEADERS)
    writer.writerow(['docking_score', 'сравнивать', direction, '', upper, low, high, ''])
    path.write_bytes(stream.getvalue().encode('utf-8-sig'))


def test_pure_docking_needs_no_admet_or_task_outcomes_and_records_absence(saved_smaa_run):
    root, run, criteria, settings = saved_smaa_run
    (run / 'admet.json').unlink()
    single_goal_csv(criteria)
    configure(saved_smaa_run)
    _, execute = workflow()
    result = execute(root, run, criteria, settings, target='R')
    doc = load(Path(result['directory']) / 'results.json')
    assert result['feasible'] == 4 and result['front'] == 1
    assert doc['source_sha256']['admet.json'] is None
    assert doc['source_sha256']['task_outcomes.json'] is None
    assert doc['configuration']['objective_count'] == 1
    assert doc['configuration']['completed_scenarios'] == 131
    assert [r['smaa']['expected_rank'] if r['smaa'] else None for r in doc['rows']] == [2., 3., 4., 1., None]
    assert not (run / 'admet.json').exists() and not (run / 'task_outcomes.json').exists()


@pytest.mark.parametrize('low,high,worst', [(-9, -8, 2.), (-100, 100, 1.)])
def test_range_template_uses_distance_anchors_and_rejects_changed_interval(saved_smaa_run, low, high, worst):
    root, run, criteria, settings = saved_smaa_run
    single_goal_csv(criteria, direction='диапазон', low=low, high=high, upper='')
    doc = configure(saved_smaa_run)
    s = doc['scales'][0]
    assert s['direction'] == 'range' and s['low'] == low and s['high'] == high
    assert s['best'] == 0. and s['worst'] == worst
    assert s['origin']['distance_max'] == (2. if low == -9 else 0.)
    _, execute = workflow()
    result = execute(root, run, criteria, settings, target='R')
    rows = load(Path(result['directory']) / 'results.json')['rows']
    assert result['feasible'] == 5
    if low == -9:
        assert [r['smaa']['expected_rank'] for r in rows] == pytest.approx([1.5, 1.5, 3.5, 3.5, 5.])
    else:
        assert all(r['smaa']['expected_rank'] == pytest.approx(3.) for r in rows)
    doc['scales'][0]['low'] += .1
    settings.write_text(json.dumps(doc), encoding='utf-8')
    with pytest.raises(ValueError, match='CSV'):
        execute(root, run, criteria, settings, target='R')


def test_constant_single_goal_template_expansion_is_explicit_and_symmetric(saved_smaa_run):
    root, run, criteria, settings = saved_smaa_run
    (run / 'admet.json').unlink()
    source = load(run / 'results.json')
    for records in source.values(): records['R']['affinity'] = -8.
    (run / 'results.json').write_text(json.dumps(source), encoding='utf-8')
    single_goal_csv(criteria)
    doc = configure(saved_smaa_run)
    s = doc['scales'][0]
    assert s['best'] == -8.5 and s['worst'] == -7.5
    assert s['origin']['observed_min'] == s['origin']['observed_max'] == -8.
    assert s['origin']['constant_rule']
    _, execute = workflow()
    result = execute(root, run, criteria, settings, target='R')
    rows = load(Path(result['directory']) / 'results.json')['rows']
    assert result['feasible'] == result['front'] == 5
    assert all(r['smaa']['first_rank_acceptability'] == pytest.approx(.2) for r in rows)
    assert all(r['smaa']['expected_rank'] == pytest.approx(3.) for r in rows)

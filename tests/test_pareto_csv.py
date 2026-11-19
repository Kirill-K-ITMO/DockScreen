"""CSV selection acceptance; predictions below are explicitly synthetic fixtures."""
import csv
import hashlib
import io
import json
from pathlib import Path
import sys

import pytest

from src.reporting.pareto_csv import (HEADERS, read_criteria, create_templates,
                                      run_pareto, choose_protocol)
from src.reporting.combined import build_combined_data


def criteria(rows):
    stream = io.StringIO(newline='')
    writer = csv.writer(stream, delimiter=';')
    writer.writerow(HEADERS)
    for row in rows: writer.writerow(row)
    return stream.getvalue().encode('utf-8-sig')


@pytest.fixture
def fixture(tmp_path):
    run = tmp_path / 'output/runs/screening-csv'
    run.mkdir(parents=True)
    prep = [{'row_id': i, 'label': f'row_{i:06d}', 'name': '=1+1<script>bad</script>' if i == 1 else str(i),
             'smiles': 'CCO', 'status': 'prepared'} for i in range(1, 5)]
    results = {r['label']: {'R': {'affinity': score, 'spec': {'options': {'scoring': 'vina'}}}}
               for r, score in zip(prep[:3], [-9, -8, -10])}
    for name, value in [('preparation.json', prep), ('results.json', results), ('summary.json', {'receptors': ['R']})]:
        (run / name).write_text(json.dumps(value), encoding='utf-8')
    endpoints = {key: {'units': '-', 'type': 'classification', 'name': key} for key in ('DILI', 'Bioavailability_Ma', 'logP')}
    admet = {'metadata': {'version': 'FAKE-test', 'input_sha256': {
        name: hashlib.sha256((run / name).read_bytes()).hexdigest() for name in ('preparation.json','results.json','summary.json')}},
        'endpoints': endpoints, 'rows': [{**{k: r[k] for k in ('row_id','name','smiles')}, 'status': 'success',
            'values': {'DILI': dili, 'Bioavailability_Ma': bio, 'logP': lp}}
            for r, dili, bio, lp in zip(prep, [.2, .3, .4, .1], [.8, .7, .9, .9], [2, 4, 3, 2])]}
    (run / 'admet.json').write_text(json.dumps(admet), encoding='utf-8')
    return tmp_path, run


def test_csv_selection_reproducible_safe_exports_and_no_source_changes(fixture):
    root, run = fixture
    path, catalogue = create_templates(root, run)
    before = {p.name: p.read_bytes() for p in run.iterdir() if p.is_file()}
    result = run_pareto(root, run, path, target='R')
    assert {k: result[k] for k in ('total','feasible','front')} == {'total': 4, 'feasible': 3, 'front': 2}
    folder = Path(result['directory'])
    saved = json.loads((folder / 'selection.json').read_text(encoding='utf-8'))
    assert [r['row_id'] for r in saved['rows'] if r['selection']['front']] == [1, 3]
    assert saved['rows'][1]['selection']['dominators'] == ['1']
    assert (folder / 'criteria.csv').read_bytes() == path.read_bytes()
    assert (folder / 'settings.json').is_file()
    assert all((run / n).read_bytes() == b for n, b in before.items())
    assert '=1+1<script>bad</script>' == saved['rows'][0]['name']
    assert (folder / 'front.csv').read_bytes().startswith(b'\xef\xbb\xbf')
    csv_rows = list(csv.DictReader((folder / 'front.csv').open(encoding='utf-8-sig')))
    assert csv_rows[0]['name'].startswith("'=1+1")
    html = (folder / 'report.html').read_text(encoding='utf-8')
    assert '<script>' not in html and '&lt;script&gt;' in html
    assert '<input' not in html and '<select' not in html
    assert 'по всем целям CSV' in html
    assert catalogue.is_file()
    assert run_pareto(root, run, path, target='R')['directory'] != result['directory']


def test_custom_constraints_decimal_comma_range_and_equal_bound(fixture):
    root, run = fixture
    path = root / 'custom.csv'
    path.write_bytes(criteria([
        ['DILI','ограничение','','','0,3','','',''],
        ['logP','сравнивать','диапазон','','','2','3','']]))
    result = run_pareto(root, run, path, target='R')
    assert result['feasible'] == 2 and result['front'] == 1
    doc = json.loads((Path(result['directory']) / 'selection.json').read_text(encoding='utf-8'))
    assert doc['rows'][0]['selection']['front']
    assert not doc['rows'][1]['selection']['reasons']  # DILI 0.3 equality passes
    assert doc['rows'][2]['selection']['reasons']


@pytest.mark.parametrize('row,reason', [
    (['unknown','сравнивать','минимум','','','','',''], 'неизвестный'),
    (['DILI','oops','минимум','','','','',''], 'использование'),
    (['DILI','сравнивать','','','','','',''], 'направление'),
    (['DILI','сравнивать','диапазон','','','3','2',''], 'диапазон'),
    (['DILI','сравнивать','минимум','2','1','','',''], 'больше'),
    (['DILI','ограничение','','','NaN','','',''], 'конечным'),
    (['DILI','ограничение','','','=1+1','','',''], 'нужно число'),
    (['DILI','ограничение','','','','','',''], 'хотя бы'),
    (['DILI','сравнивать','максимум','','','0','1',''], 'только'),
])
def test_invalid_inputs_fail_with_row_explanation(row, reason):
    with pytest.raises(ValueError, match=reason):
        read_criteria(criteria([row]), {'DILI': {}})


def test_duplicate_disabled_empty_headers_and_no_objectives(fixture):
    root, run = fixture
    row = ['DILI','сравнивать','минимум','','','','','']
    with pytest.raises(ValueError, match='повторно'): read_criteria(criteria([row,row]), {'DILI':{}})
    with pytest.raises(ValueError, match='ни одной'): read_criteria(criteria([]), {'DILI':{}})
    with pytest.raises(ValueError, match='столбцы'): read_criteria(b'parameter,role\nx,y', {'DILI':{}})
    disabled = read_criteria(criteria([['DILI','не учитывать','минимум','','0.6','','',''],
        ['logP','сравнивать','максимум','','','','','']]), {'DILI':{},'logP':{}})
    assert disabled[0]['max'] is None and disabled[0]['role'] == 'display'
    path = root / 'constraint.csv'
    path.write_bytes(criteria([['DILI','ограничение','','','1','','','']]))
    result = run_pareto(root,run,path,target='R')
    assert result['feasible'] == 3 and result['front'] == 0
    text = (Path(result['directory'])/'report.html').read_text(encoding='utf-8')
    assert 'фронт не определяется' in text


def test_protocol_explicitness_template_no_overwrite_and_zip(fixture):
    root,run=fixture
    path,_=create_templates(root,run)
    path.write_bytes(criteria([['DILI','ограничение','','','0','','','']]))
    assert create_templates(root,run)[0].read_bytes() == path.read_bytes()
    data=build_combined_data(root,run)
    with pytest.raises(ValueError,match='Явно'): choose_protocol(data,None)
    data['protocols'].append({**data['protocols'][0],'id':'different'})
    with pytest.raises(ValueError,match='конкретный'): choose_protocol(data,'R')
    assert choose_protocol(data,'R','different')['id']=='different'
    result=run_pareto(root,run,path,target='R')
    assert result['front']==0 and result['feasible']==0
    import zipfile
    from src.core.project import ProjectUtils
    dest=ProjectUtils(root).export_results_to_zip(root/'test.zip',run_dir=run)
    with zipfile.ZipFile(dest) as z:
        assert any(n.startswith('run/pareto/') and n.endswith('/criteria.csv') for n in z.namelist())
        assert any(n.endswith('/report.html') for n in z.namelist())


def test_cli_never_calls_vina_or_admet(fixture,monkeypatch,capsys):
    root,run=fixture
    import main
    from src.admet import pipeline
    from src.docking.vina import AutoDockVina
    monkeypatch.setattr(AutoDockVina,'__init__',lambda *a,**k:pytest.fail('No docking'))
    monkeypatch.setattr(pipeline,'enrich_run',lambda *a,**k:pytest.fail('No ADMET'))
    monkeypatch.setattr(sys,'argv',['main.py','--project',str(root),'--pareto-template',str(run)])
    assert main.main()==0
    monkeypatch.setattr(sys,'argv',['main.py','--project',str(root),'--pareto-run',str(run),
        '--pareto-criteria',str(run/'settings/pareto_criteria.csv'),'--pareto-target','R'])
    assert main.main()==0
    assert 'Pareto results:' in capsys.readouterr().out


def test_csv_menu_runs_selection_without_browser_controls(fixture):
    root,run=fixture
    from types import SimpleNamespace
    from src.reporting.pareto_csv import pareto_csv_menu
    answers=iter(['1','1','','1'])
    messages=[]
    console=SimpleNamespace(input=lambda *a:next(answers),print=lambda text,**k:messages.append(str(text)))
    pareto_csv_menu(root,console)
    assert (root/'settings/PARETO_CRITERIA.csv').is_file()
    assert (root/'settings/PARETO_PARAMETERS.csv').is_file()
    assert len(list((run/'pareto').glob('selection-*/front.csv')))==1
    assert any('front: 2' in m for m in messages)

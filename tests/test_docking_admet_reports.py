"""Ordinary report integration; all model numbers in these fixtures are synthetic."""
import csv
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.reporting.admet import generate_run_reports, report_context
from src.reporting.docking import ReportGenerator
from src.reporting.pareto_csv import default_criteria, run_default_pareto


@pytest.fixture
def saved_run(tmp_path):
    run = tmp_path / 'output/runs/docking-report'
    run.mkdir(parents=True)
    prep = [{'row_id': i, 'label': f'row_{i}', 'name': '=1+1</script><script>bad</script>',
             'smiles': smiles, 'status': 'prepared'} for i, smiles in enumerate(['CCO','CCN','CCO'],1)]
    results = {row['label']: {t: {'selection_row_id': row['row_id'], 'input_name': row['name'],
        'smiles': row['smiles'], 'affinity': -5-row['row_id'], 'spec': {'options': {'scoring':'vina'}}}
        for t in ['R','S']} for row in prep}
    for name,value in [('preparation.json',prep),('results.json',results),('summary.json',{'receptors':['R','S']})]:
        (run/name).write_text(json.dumps(value),encoding='utf-8')
    admet={'metadata':{'version':'FAKE-report-test','input_sha256':{n:hashlib.sha256((run/n).read_bytes()).hexdigest()
        for n in ('preparation.json','results.json','summary.json')}},
        'endpoints': {'DILI':{'units':'-','type':'classification'},'ClinTox':{'units':'-','type':'classification'},'Bioavailability_Ma':{'units':'-','type':'classification'},
                      'hERG':{'units':'-','type':'classification'},'Half_Life_Obach':{'units':'hr','type':'regression','R^2':'-0.1','warnings':['negative reference R²']}},
        'rows':[{**{k:r[k] for k in ('row_id','name','smiles')},'status':'prediction_failed' if r['row_id']==2 else 'success',
                 'error':'fake failure' if r['row_id']==2 else '',
                 'values':{} if r['row_id']==2 else {'hERG':.2,'DILI':.2,'ClinTox':.2,'Bioavailability_Ma':.8,'Half_Life_Obach':2}}
                 for r in prep]}
    (run/'admet.json').write_text(json.dumps(admet),encoding='utf-8')
    return tmp_path,run,results


def test_ordinary_html_csv_join_duplicates_order_missing_and_safety(saved_run):
    root,run,results=saved_run
    before={p.name:p.read_bytes() for p in run.iterdir() if p.is_file()}
    html_path,csv_path=generate_run_reports(root,run)
    rows=list(csv.DictReader(csv_path.open(encoding='utf-8-sig')))
    headers=list(rows[0])
    assert headers.index('ADMET__DILI')==headers.index('S_delta_g')+1
    assert headers.count('ADMET__DILI')==1
    assert [r['row_id'] for r in rows]==['1','2','3']
    assert rows[0]['ADMET__DILI']==rows[2]['ADMET__DILI']=='0.2'
    assert rows[1]['ADMET__DILI']=='' and rows[1]['admet_status']=='prediction_failed'
    assert rows[1]['admet_error']=='fake failure'
    assert rows[0]['name'].startswith("'=1+1")
    html=html_path.read_text(encoding='utf-8')
    assert '</script><script>bad</script>' not in html
    assert 'ADMET · DILI' in html and 'not percent bioavailability' in html
    assert 'negative reference' in html
    assert html.index('Docking score (kcal/mol)')<html.index('ADMET · DILI')
    assert all((run/n).read_bytes()==b for n,b in before.items())
    notes=json.loads(Path(str(csv_path)+'.notes.json').read_text(encoding='utf-8'))
    assert notes['endpoints']['DILI']['type']=='classification'


def test_wrong_identity_rejected_and_no_admet_keeps_original_schema(saved_run):
    root,run,results=saved_run
    context=report_context(root,run)
    results['row_1']['R']['selection_row_id']=999
    with pytest.raises(ValueError,match='identity'):
        ReportGenerator(root).generate_csv_report(results,output_file=root/'bad.csv',admet=context)
    assert not (root/'bad.csv').exists()
    path=ReportGenerator(root).generate_csv_report(results,output_file=root/'plain.csv')
    assert not any(h.startswith('ADMET') for h in next(csv.reader(path.open(encoding='utf-8'))))


def test_named_default_and_user_csv_preserved_protocols_separate(saved_run):
    root,run,results=saved_run
    custom=root/'PARETO_CRITERIA.csv'
    custom.write_bytes(b'USER SETTINGS MUST NOT CHANGE')
    defaults=run_default_pareto(root,run)
    assert len(defaults)==2 and {d['target'] for d in defaults}=={'R','S'}
    assert custom.read_bytes()==b'USER SETTINGS MUST NOT CHANGE'
    for result in defaults:
        doc=json.loads((Path(result['directory'])/'settings.json').read_text(encoding='utf-8'))
        assert doc['preset_id']=='user-default-v3'
        assert doc['criteria'][1]['key']=='DILI' and doc['criteria'][1]['max']==.5
        assert doc['counts']['feasible']==1
    assert default_criteria({'endpoints':{'docking_score':{},'DILI':{},'Bioavailability_Ma':{}}})[2]['direction']=='max'


@pytest.mark.parametrize('reports,admet_choice,fail',[(False,False,False),(True,False,False),
    (True,True,False),(False,True,False),(True,True,True)])
def test_menu_question_order_optional_admet_and_failure_retains_docking(tmp_path,monkeypatch,reports,admet_choice,fail):
    from src.ui.docking_menu import docking_menu
    import src.core.preflight as preflight
    import src.reporting.hits as hits
    from src.admet import pipeline
    monkeypatch.setattr(preflight,'check_run',lambda *a,**k:SimpleNamespace(ready=True))
    monkeypatch.setattr(preflight,'display',lambda *a,**k:None)
    monkeypatch.setattr(hits,'export_hits',lambda *a,**k:None)
    calls=[]
    def worker(python,request,timeout,work):
        calls.append(request['action'])
        if fail: raise RuntimeError('fake missing environment')
        provenance={'metadata':{'version':'FAKE'},'endpoints':{'hERG':{'units':'-','type':'classification'},'DILI':{'units':'-','type':'classification'},'ClinTox':{'units':'-','type':'classification'},
            'Bioavailability_Ma':{'units':'-','type':'classification'}}}
        if request['action']=='probe': return provenance
        return {**provenance,'predictions':{s:{'status':'success','values':{'hERG':.2,'DILI':.2,'ClinTox':.2,'Bioavailability_Ma':.8}} for s in request['smiles']}}
    monkeypatch.setattr(pipeline,'_invoke',worker)
    (tmp_path/'data').mkdir()
    (tmp_path/'data/ligands.csv').write_text('name,smiles\nx,CCO\n',encoding='utf-8')
    class Docker:
        stats={}
        def get_targets(self):return [{'id':'R'}]
        def get_config(self,p):return Path('config')
        def run_docking(self,**kwargs):
            self.results={label:{'R':{'affinity':-6,'spec':{'options':{'scoring':'vina'}}}} for label in kwargs['ligand_paths']}
            return self.results
        def _save_results_json(self):
            self.last_batch_dir=tmp_path/'output/runs/docking-new'
            self.last_batch_dir.mkdir(parents=True)
            (self.last_batch_dir/'results.json').write_text(json.dumps(self.results),encoding='utf-8')
    answers=iter(['all','all','','','1','no','yes','yes' if reports else 'no','yes' if admet_choice else 'no'])
    prompts=[]
    def ask(prompt):prompts.append(prompt);return next(answers)
    generated=[]
    app=SimpleNamespace(project_root=tmp_path,docker=Docker(),converter=SimpleNamespace(prepare_cached=lambda s:{'path':'fake.pdbqt'}),
        database=SimpleNamespace(add_experiment=lambda **k:1,finish_experiment=lambda *a:None),
        _save_results_to_db=lambda *a:None,generate_reports=lambda **k:generated.append(k))
    docking_menu(app,SimpleNamespace(input=ask,print=lambda *a,**k:None))
    assert 'Generate reports' in prompts[-2] and 'ADMET' in prompts[-1]
    assert bool(calls)==admet_choice and bool(generated)==reports
    run=app.docker.last_batch_dir
    assert json.loads((run/'results.json').read_text(encoding='utf-8'))['x']['R']['affinity']==-6
    if reports:assert (generated[0]['admet'] is not None)==admet_choice
    if admet_choice and not fail:assert (run/'pareto/default_selections.json').is_file()

"""User-confirmed five-objective default, with exact inclusive boundaries."""
import json

import pytest

from src.reporting.pareto import select_pareto
from src.reporting.pareto_csv import (DEFAULT_PRESET_ID, default_criteria,
    read_criteria, write_criteria_template, run_default_pareto)


def data():
    return {'endpoints': {k: {} for k in ('docking_score','DILI','ClinTox','Bioavailability_Ma','hERG')}}


def test_default_csv_roundtrip_contains_all_five_bounds(tmp_path):
    path=write_criteria_template(data(),tmp_path/'default.csv')
    settings=read_criteria(path.read_bytes(),data()['endpoints'])
    assert settings==default_criteria(data())
    assert DEFAULT_PRESET_ID=='user-default-v3'
    assert [(s['key'],s['direction'],s['min'],s['max']) for s in settings]==[
        ('docking_score','min',None,-7.0),('DILI','min',None,.5),
        ('ClinTox','min',None,.5),('Bioavailability_Ma','max',.5,None),('hERG','min',None,.5)]


def test_sign_boundaries_and_missing_clintox_are_explicit():
    baseline={'docking_score':-7.,'DILI':.5,'ClinTox':.5,'Bioavailability_Ma':.5,'hERG':.5}
    variations=[('edge',{}),('better_docking',{'docking_score':-8.}),
        ('weak_docking',{'docking_score':-6.999}),('dili',{'DILI':.50001}),
        ('clintox',{'ClinTox':.50001}),('bio',{'Bioavailability_Ma':.49999}),
        ('herg',{'hERG':.50001}),('missing_herg',{'hERG':None}),('missing',{'ClinTox':None})]
    rows=[{'id':name,'values':{**baseline,**changed}} for name,changed in variations]
    decisions={d['id']:d for d in select_pareto(rows,default_criteria(data()))}
    assert not decisions['edge']['reasons']
    assert not decisions['better_docking']['reasons'] and decisions['better_docking']['front']
    assert decisions['edge']['dominators']==['better_docking']
    for name in ('weak_docking','dili','clintox','bio','herg','missing_herg','missing'):
        assert decisions[name]['reasons']


def test_full_default_fails_closed_when_clintox_not_available(tmp_path):
    run=tmp_path/'output/runs/screening-missing'
    run.mkdir(parents=True)
    prep=[{'row_id':1,'label':'r','name':'r','smiles':'CCO','status':'prepared'}]
    for name,value in [('preparation.json',prep),('results.json',{'r':{'R':{'affinity':-8}}}),
                       ('summary.json',{'receptors':['R']})]:
        (run/name).write_text(json.dumps(value),encoding='utf-8')
    with pytest.raises(ValueError,match='ClinTox'):
        run_default_pareto(tmp_path,run)
    assert not (run/'pareto').exists()

"""Independent join-integrity and scientific selection acceptance."""
import hashlib
import json

import pytest

from src.reporting.combined import build_combined_data
from src.reporting.pareto import select_pareto


def test_admet_for_another_structure_cannot_attach_by_row_number(tmp_path):
    run = tmp_path / 'output/runs/screening-join'
    run.mkdir(parents=True)
    prep = [{'row_id': 1, 'label': 'row_000001', 'name': 'same-name', 'smiles': 'CCO'}]
    for name, value in [('preparation.json', prep), ('results.json', {}), ('summary.json', {})]:
        (run / name).write_text(json.dumps(value), encoding='utf-8')
    hashes = {n: hashlib.sha256((run / n).read_bytes()).hexdigest()
              for n in ('preparation.json', 'results.json', 'summary.json')}
    admet = {'metadata': {'input_sha256': hashes}, 'endpoints': {'DILI': {}}, 'rows': [
        {'row_id': 1, 'name': 'same-name', 'smiles': 'CCN',
         'status': 'success', 'values': {'DILI': 0.1}}]}
    (run / 'admet.json').write_text(json.dumps(admet), encoding='utf-8')
    # A visible rejection or a non-success/missing value is acceptable.
    try:
        data = build_combined_data(tmp_path, run)
    except ValueError:
        return
    assert data['rows'][0]['values'].get('DILI') is None
    assert data['rows'][0]['admet_status'] != 'success'


def test_constraints_before_dominance_and_target_interval_ties():
    rows = [{'id': 'excluded-best', 'values': {'docking': -10, 'DILI': 0.6000001, 'p': 7}},
            {'id': 'edge', 'values': {'docking': -8, 'DILI': 0.6, 'p': 6}},
            {'id': 'equal', 'values': {'docking': -8, 'DILI': 0.6, 'p': 8}},
            {'id': 'dominated', 'values': {'docking': -7, 'DILI': 0.2, 'p': 9}},
            {'id': 'missing', 'values': {'docking': -12, 'DILI': None, 'p': 7}}]
    settings = [{'key': 'docking', 'role': 'objective', 'direction': 'min'},
                {'key': 'DILI', 'role': 'constraint', 'max': 0.6},
                {'key': 'p', 'role': 'objective', 'direction': 'range', 'low': 6, 'high': 8}]
    decisions = {r['id']: r for r in select_pareto(rows, settings)}
    assert {k for k, d in decisions.items() if d['front']} == {'edge', 'equal'}
    assert set(decisions['dominated']['dominators']) == {'edge', 'equal'}
    assert decisions['excluded-best']['reasons']
    assert decisions['missing']['reasons']


def test_inactive_missing_never_affects_selection():
    result = select_pareto([{'id': 1, 'values': {'score': -7}},
                            {'id': 2, 'values': {'score': -6, 'reference': None}}],
                           [{'key': 'score', 'role': 'objective', 'direction': 'min'},
                            {'key': 'reference', 'role': 'display', 'max': 0}])
    assert result[0]['front']
    assert result[1]['dominators'] == [1]
    assert not result[1]['reasons']

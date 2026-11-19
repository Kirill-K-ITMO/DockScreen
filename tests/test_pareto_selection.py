import json
import shutil
import subprocess

import pytest

from src.reporting.pareto import PARETO_JS, select_pareto


def row(id, **values):
    return {'id': str(id), 'values': values}


def goal(key, direction='min', **kwargs):
    return dict(key=key, role='objective', direction=direction, **kwargs)


@pytest.mark.parametrize('rows,settings,front', [
    ([row(1, x=1), row(2, x=2)], [goal('x')], ['1']),
    ([row(1, x=1), row(2, x=2)], [goal('x', 'max')], ['2']),
    ([row(1, x=1), row(2, x=1)], [goal('x')], ['1', '2']),
    ([row(1, x=1, y=4), row(2, x=2, y=3)], [goal('x'), goal('y')], ['1', '2']),
    ([row(1, x=1, y=4), row(2, x=2, y=3)], [goal('x'), goal('y', 'max')], ['1']),
    ([row(1, x=3), row(2, x=4), row(3, x=6)], [goal('x', 'range', low=3, high=5)], ['1', '2']),
    ([row(1, x=.6), row(2, x=.60001)], [goal('x', 'max', max=.6)], ['1']),
    ([row(1, x=-2), row(2, x=0)], [goal('x', min=-2, max=-2)], ['1']),
    ([row(1), row(2, x=None), row(3, x='0'), row(4, x=False), row(5, x=0)], [goal('x')], ['5']),
    ([row(1), row(2, x=0)], [{'key': 'x', 'role': 'display'}], []),
    ([row(1, x=2), row(2, x=3)], [{'key': 'x', 'role': 'constraint', 'min': 2, 'max': 3}], []),
    ([], [goal('x')], []),
])
def test_exact_selection_and_javascript_parity(rows, settings, front):
    actual = select_pareto(rows, settings)
    assert [r['id'] for r in actual if r['front']] == front
    node = shutil.which('node')
    if node:
        script = PARETO_JS + '\nprocess.stdout.write(JSON.stringify(Pareto.select(' + json.dumps(rows) + ',' + json.dumps(settings) + ')));'
        output = subprocess.run([node, '-e', script], capture_output=True, text=True, check=True, encoding='utf-8')
        assert json.loads(output.stdout) == actual


def test_missing_docking_is_not_candidate_even_without_docking_objective():
    rows = [dict(row(1, x=0), eligible=False, error='timeout'), row(2, x=1)]
    actual = select_pareto(rows, [goal('x')])
    assert actual[0]['reasons'] == ['timeout']
    assert actual[1]['front']


def test_all_dominators_and_nonfinite_missing():
    actual = select_pareto([row(1, x=0), row(2, x=1), row(3, x=2), row(4, x=float('nan'))], [goal('x')])
    assert actual[2]['dominators'] == ['1', '2']
    assert actual[3]['reasons']


def test_invalid_range():
    with pytest.raises(ValueError):
        select_pareto([row(1, x=1)], [goal('x', 'range', low=5, high=3)])

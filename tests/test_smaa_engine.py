"""Independent analytical acceptance cases; values are synthetic, not drug data."""
import copy

import numpy as np
import pytest

from src.analysis.smaa import analyze_preferences, utility_matrix, validate_scales


def scale(key='x', direction='max', worst=0., best=1., **extra):
    return {'key': key, 'direction': direction, 'worst': worst, 'best': best,
            'alpha': 1., **extra}


def candidates(values):
    return [{'id': str(i), 'name': 'same name', 'values': v} for i, v in enumerate(values)]


def indexed(result):
    return {r['id']: r for r in result['rows']}


def test_single_objective_strict_dominance_exact_ranks_and_top_clamping():
    result = analyze_preferences(candidates([{'x': .2}, {'x': .9}, {'x': .5}]),
                                 [scale()], iterations=37, seed=4, top_n=10)
    config = result['configuration']
    assert config['effective_top_n'] == config['candidate_count'] == 3
    assert config['requested_top_n'] == 10
    for row, rank in zip(result['rows'], [3, 1, 2]):
        assert row['rank_acceptability'] == {str(rank): 1.}
        assert row['expected_rank'] == rank
        assert row['median_rank'] == rank
        assert row['first_rank_acceptability'] == (rank == 1)
        assert row['top_n_acceptability'] == 1.


def test_dirichlet_simplex_not_normalized_independent_uniforms():
    # A beats B iff w_x > 1/4. Under Dirichlet(1,1), P=3/4.
    # Normalized independent U(0,1) would instead give 5/6.
    rows = candidates([{'x': 1., 'y': 0.}, {'x': 0., 'y': 1/3}])
    result = analyze_preferences(rows, [scale('x'), scale('y')],
                                 iterations=12000, seed=151, top_n=1)
    assert result['rows'][0]['first_rank_acceptability'] == pytest.approx(.75, abs=.02)
    assert result['configuration']['weight_distribution'] == 'Dirichlet'


def test_conflicting_symmetric_candidates_and_bistochastic_rank_distribution():
    rows = candidates([{'x': 1., 'y': 0.}, {'x': 0., 'y': 1.}, {'x': .2, 'y': .2}])
    result = analyze_preferences(rows, [scale('x'), scale('y')],
                                 iterations=6000, seed=78, top_n=2)
    data = result['rows']
    assert data[0]['first_rank_acceptability'] == pytest.approx(.5, abs=.03)
    assert data[1]['first_rank_acceptability'] == pytest.approx(.5, abs=.03)
    assert data[2]['first_rank_acceptability'] == 0
    matrix = np.array([[r['rank_acceptability'].get(str(k), 0.) for k in range(1, 4)] for r in data])
    np.testing.assert_allclose(matrix.sum(axis=0), 1., atol=1e-12)
    np.testing.assert_allclose(matrix.sum(axis=1), 1., atol=1e-12)
    assert sum(r['top_n_acceptability'] for r in data) == pytest.approx(2.)
    assert all(r['top_n_acceptability'] == pytest.approx(sum(matrix[i, :2])) for i, r in enumerate(data))


def test_identical_candidates_share_every_rank_and_boundary_top_n_symmetrically():
    rows = candidates([{'x': .5, 'y': .5}] * 4)
    args = dict(iterations=113, seed=9, top_n=2)
    result = analyze_preferences(rows, [scale('x'), scale('y')], **args)
    assert indexed(result) == indexed(analyze_preferences(list(reversed(rows)), [scale('x'), scale('y')], **args))
    for r in result['rows']:
        assert r['rank_acceptability'] == pytest.approx({'1': .25, '2': .25, '3': .25, '4': .25})
        assert r['top_n_acceptability'] == .5
        assert r['first_rank_acceptability'] == .25
        assert r['expected_rank'] == 2.5
        assert r['median_rank'] == 2
        assert r['rank_p05'] == 1 and r['rank_p95'] == 4


def test_partial_tie_group_crosses_top_boundary_without_input_order_advantage():
    rows = candidates([{'x': 1.}, {'x': .5}, {'x': .5}, {'x': .5}, {'x': 0.}])
    result = analyze_preferences(rows, [scale()], iterations=41, seed=3, top_n=2)
    for r in result['rows'][1:4]:
        assert r['top_n_acceptability'] == pytest.approx(1/3)
        assert r['rank_acceptability'] == pytest.approx({'2': 1/3, '3': 1/3, '4': 1/3})
    assert result['rows'][0]['first_rank_acceptability'] == 1.
    assert result['rows'][4]['top_n_acceptability'] == 0.


def test_scales_directions_clipping_and_target_distance():
    scales = [scale('a', 'min', 10., 0.), scale('b', 'max', 0., 10.),
              scale('c', 'range', 4., 0., low=2., high=4.)]
    rows = candidates([{'a': -1., 'b': 12., 'c': 3.},
                       {'a': 12., 'b': -1., 'c': 0.},
                       {'a': 5., 'b': 5., 'c': 8.}])
    np.testing.assert_allclose(utility_matrix(rows, scales), [[1., 1., 1.], [0., 0., .5], [.5, .5, 0.]])


@pytest.mark.parametrize('bad', [None, '0.4', float('nan'), float('inf'), True])
def test_missing_or_nonnumeric_engine_values_are_not_imputed(bad):
    with pytest.raises(ValueError):
        analyze_preferences(candidates([{'x': bad}]), [scale()], iterations=3)


@pytest.mark.parametrize('change', [dict(best=0.), dict(best=-1.), dict(alpha=0.),
    dict(alpha=float('nan')), dict(worst=True), dict(direction='unknown'),
    dict(direction='range', worst=2., best=0., low=4., high=2.),
    dict(direction='range', worst=2., best=1., low=0., high=2.)])
def test_invalid_scales_rejected(change):
    with pytest.raises(ValueError):
        validate_scales([scale(**change)])


def test_no_objectives_duplicate_ids_and_duplicate_objectives_rejected():
    with pytest.raises(ValueError): analyze_preferences([], [], iterations=3)
    with pytest.raises(ValueError): analyze_preferences(candidates([{'x': 1.}]), [scale(), scale()], iterations=3)
    with pytest.raises(ValueError): analyze_preferences([{'id': 'a', 'values': {'x': 1.}}] * 2, [scale()], iterations=3)


@pytest.mark.parametrize('options', [dict(iterations=0), dict(iterations=True), dict(seed=-1),
    dict(seed=2**32), dict(top_n=0), dict(top_n=True)])
def test_invalid_run_options_rejected(options):
    with pytest.raises(ValueError): analyze_preferences(candidates([{'x': 1.}]), [scale()], **options)


def test_repeatability_progress_and_cooperative_cancellation():
    rows = candidates([{'x': .7, 'y': .1}, {'x': .1, 'y': .8}])
    original = copy.deepcopy(rows)
    progress = []
    a = analyze_preferences(rows, [scale('x'), scale('y')], iterations=131, seed=33,
                            progress=lambda done, total: progress.append((done, total)))
    b = analyze_preferences(rows, [scale('x'), scale('y')], iterations=131, seed=33)
    assert a == b and rows == original
    assert progress[-1] == (131, 131)
    assert len(progress) >= 3
    assert all(a[0] < b[0] for a, b in zip(progress, progress[1:]))
    def cancel(done, total): raise KeyboardInterrupt
    with pytest.raises(KeyboardInterrupt):
        analyze_preferences(rows, [scale('x'), scale('y')], iterations=131, progress=cancel)


def test_empty_feasible_set_is_explicit_not_fictitious_last_rank():
    result = analyze_preferences([], [scale()], iterations=7, top_n=100)
    assert result['rows'] == []
    assert result['configuration']['candidate_count'] == 0
    assert result['configuration']['effective_top_n'] == 0
    assert result['configuration']['completed_scenarios'] == 0


def test_configurable_quantiles_and_scenario_batches_preserve_rank_results():
    rows = candidates([{'x': 1., 'y': 0.}, {'x': 0., 'y': 1.}, {'x': .4, 'y': .4}])
    kwargs = dict(iterations=173, seed=18, top_n=2, rank_quantiles=(.2, .8))
    small = analyze_preferences(rows, [scale('x'), scale('y')], batch_size=7, **kwargs)
    large = analyze_preferences(rows, [scale('x'), scale('y')], batch_size=64, **kwargs)
    for a, b in zip(small['rows'], large['rows']):
        assert a['rank_acceptability'] == pytest.approx(b['rank_acceptability'], abs=1e-12)
        assert a['rank_quantiles'] == b['rank_quantiles']
        assert a['rank_quantile_low'] <= a['median_rank'] <= a['rank_quantile_high']
        assert [entry['q'] for entry in a['rank_quantiles']] == [.2, .8]


@pytest.mark.parametrize('options', [dict(batch_size=0), dict(batch_size=True), dict(batch_size=257),
    dict(rank_quantiles=(.8, .2)), dict(rank_quantiles=(0., 1.)), dict(rank_quantiles=(.5, .5)),
    dict(rank_quantiles=(float('nan'), .9))])
def test_bad_quantiles_and_batch_limits_rejected(options):
    with pytest.raises(ValueError):
        analyze_preferences(candidates([{'x': 1.}]), [scale()], iterations=3, **options)

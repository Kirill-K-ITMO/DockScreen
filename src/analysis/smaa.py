"""Preference-only SMAA-2 on fixed values, with symmetric rank-slot sharing.

No property-error distribution is assumed. Output fractions are acceptability
under the chosen preferences, not experimental or clinical success probabilities.
"""
import math
import platform
from collections.abc import Mapping

import numpy as np

ENGINE_VERSION = 'smaa-preferences-v1'
MAX_CANDIDATES = 100000
MAX_OBJECTIVES = 64
MAX_ITERATIONS = 100000
MAX_BATCH_SIZE = 256
MAX_MEMORY_BYTES = 256 * 1024 * 1024


def _finite(value):
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def validate_options(iterations, seed, top_n):
    if type(iterations) is not int or not 1 <= iterations <= MAX_ITERATIONS:
        raise ValueError(f'Число сценариев должно быть целым от 1 до {MAX_ITERATIONS}')
    if type(seed) is not int or not 0 <= seed <= 2**32 - 1:
        raise ValueError('SMAA seed должен быть целым от 0 до 4294967295')
    if type(top_n) is not int or top_n < 1:
        raise ValueError('Размер короткого списка должен быть положительным целым')


def validate_quantiles(rank_quantiles):
    if (not isinstance(rank_quantiles, (list, tuple)) or len(rank_quantiles) != 2
            or not all(_finite(q) and 0 < q < 1 for q in rank_quantiles)
            or rank_quantiles[0] >= rank_quantiles[1]):
        raise ValueError('Квантили ранга должны удовлетворять 0 < нижний < верхний < 1')


def validate_scales(scales):
    if not isinstance(scales, (list, tuple)) or not 1 <= len(scales) <= MAX_OBJECTIVES:
        raise ValueError(f'SMAA требует от 1 до {MAX_OBJECTIVES} целей сравнения')
    if any(not isinstance(s, Mapping) or not isinstance(s.get('key'), str) or not s['key'].strip() for s in scales):
        raise ValueError('Каждая шкала требует непустой строковый key')
    keys = [s['key'] for s in scales]
    if len(set(keys)) != len(keys):
        raise ValueError('SMAA требует неповторяющиеся цели сравнения')
    for s in scales:
        if s.get('direction') not in ('min', 'max', 'range'):
            raise ValueError(f"{s['key']}: неизвестное направление")
        for field in ('worst', 'best', 'alpha'):
            if not _finite(s.get(field)):
                raise ValueError(f"{s['key']}: {field} должно быть конечным числом")
        if not 0.01 <= s['alpha'] <= 100:
            raise ValueError(f"{s['key']}: альфа должна быть от 0.01 до 100")
        valid = s['best'] > s['worst'] if s['direction'] == 'max' else s['best'] < s['worst']
        if not valid or not _finite(s['best'] - s['worst']):
            raise ValueError(f"{s['key']}: границы шкалы не соответствуют направлению или совпадают")
        if s['direction'] == 'range':
            if not (_finite(s.get('low')) and _finite(s.get('high')) and s['low'] <= s['high']):
                raise ValueError(f"{s['key']}: некорректный целевой диапазон")
            if s['best'] != 0 or s['worst'] <= 0:
                raise ValueError(f"{s['key']}: для расстояния до диапазона желательно=0, нежелательно>0")


def utility_matrix(rows, scales):
    """Piecewise-linear utilities in [0,1], clamped at explicit scale anchors.

    For a range goal the scale anchors describe distance to [low, high], not
    the raw property. best=0 gives every value inside the interval utility 1.
    """
    validate_scales(scales)
    matrix = np.empty((len(rows), len(scales)), dtype=np.float64)
    for j, s in enumerate(scales):
        for i, row in enumerate(rows):
            v = row.get('values', {}).get(s['key'])
            if not _finite(v):
                raise ValueError(f"{row.get('id')}, {s['key']}: нет конечного численного значения")
            if s['direction'] == 'range':
                v = max(s['low'] - v, 0, v - s['high'])
            # Clamp BEFORE subtraction: finite but very distant values can
            # otherwise overflow the numerator, although utility is well-defined.
            if s['direction'] == 'max':
                value = 0. if v <= s['worst'] else 1. if v >= s['best'] else (v - s['worst']) / (s['best'] - s['worst'])
            else:
                value = 0. if v >= s['worst'] else 1. if v <= s['best'] else (s['worst'] - v) / (s['worst'] - s['best'])
            if not math.isfinite(value):
                raise ValueError(f"{s['key']}: численная ошибка шкалирования")
            matrix[i, j] = value
    return matrix


def analyze_preferences(rows, scales, *, iterations=10000, seed=42, top_n=10,
                        rank_quantiles=(.05, .95), batch_size=64, progress=None):
    """Rank every supplied feasible row; exact ties share occupied rank slots.

    A group tied at positions a..b receives 1/(b-a+1) at each position for
    every member. The same fractional allocation applies at a top-N boundary.
    No random tiebreaker or input-order preference is used. Equality means exact
    float64 equality after a fixed objective-order summation, with no tolerance.
    Near-ties remain distinct. Quantiles use the inverse discrete CDF.

    Memory is O(candidates squared + batch*candidates), never a full scenario
    history. progress(done,total) is called before computation and after every
    batch; exceptions (including KeyboardInterrupt) propagate to the caller.
    Reproducibility requires matching inputs, objective order, options, NumPy
    and engine version; batch_size is part of the recorded configuration.
    """
    validate_options(iterations, seed, top_n)
    validate_scales(scales)
    if type(batch_size) is not int or not 1 <= batch_size <= MAX_BATCH_SIZE:
        raise ValueError(f'Размер пакета сценариев должен быть от 1 до {MAX_BATCH_SIZE}')
    validate_quantiles(rank_quantiles)
    ids = [r['id'] for r in rows]
    try:
        unique_ids = len(set(ids))
    except TypeError as error:
        raise ValueError('Идентификаторы кандидатов должны быть скалярными') from error
    if unique_ids != len(ids):
        raise ValueError('Повторяющиеся идентификаторы кандидатов')
    if len(rows) > MAX_CANDIDATES:
        raise ValueError(f'Первая версия SMAA поддерживает до {MAX_CANDIDATES} допустимых строк; сузьте ограничения')
    n, m = len(rows), len(scales)
    # Conservative allowance for dense Python rank dictionaries as well as
    # NumPy arrays. Interpreter/platform overhead can vary; this is an estimate.
    estimated_memory = 192 * n * n + 160 * batch_size * n + 64 * n * m
    if estimated_memory > MAX_MEMORY_BYTES:
        raise ValueError('SMAA: оценка памяти превышает 256 MiB; уменьшите набор или размер пакета')
    utilities = utility_matrix(rows, scales)
    effective_top = min(n, top_n)
    config = {'engine': ENGINE_VERSION, 'iterations': iterations, 'completed_scenarios': iterations if n else 0, 'seed': seed,
              'requested_top_n': top_n, 'effective_top_n': effective_top,
              'candidate_count': n, 'objective_count': m, 'numpy_version': np.__version__,
              'python_version': platform.python_version(), 'float_type': 'float64',
              'rng': 'numpy.PCG64', 'weight_distribution': 'Dirichlet',
              'alpha': [s['alpha'] for s in scales], 'scales': [dict(s) for s in scales],
              'value_uncertainty': 'not_modelled', 'acceptability_units': 'fraction_0_to_1',
              'tie_policy': 'exact float64 score ties share all occupied rank slots uniformly',
              'score_summation': 'numpy.einsum optimize=False, fixed objective order',
              'rank_quantiles': list(rank_quantiles), 'quantile_method': 'inverse_discrete_cdf',
              'scale_extrapolation': 'clamp utility to [0,1] at anchors',
              'mc_se_method': 'sqrt(population variance of per-scenario fractional credit / iterations)',
              'batch_size': batch_size, 'rank_scope': 'all feasible input rows; no Pareto prefilter',
              'limits': {'max_candidates': MAX_CANDIDATES, 'max_objectives': MAX_OBJECTIVES,
                         'max_iterations': MAX_ITERATIONS, 'max_batch_size': MAX_BATCH_SIZE,
                         'memory_budget_bytes': MAX_MEMORY_BYTES,
                         'estimated_memory_bytes': estimated_memory}}
    if progress:
        progress(0, iterations if n else 0)
    if not n:
        return {'configuration': config, 'rows': []}
    rng = np.random.Generator(np.random.PCG64(seed))
    rank_diff = np.zeros((n, n + 1), dtype=np.float64)
    win_weights = np.zeros((n, m), dtype=np.float64)
    top_sum, top_square = np.zeros(n), np.zeros(n)
    first_sum, first_square = np.zeros(n), np.zeros(n)
    index = np.arange(n)
    for start in range(0, iterations, batch_size):
        size = min(batch_size, iterations - start)
        weights = rng.dirichlet(config['alpha'], size=size)
        # No BLAS-dependent change of reduction with candidate ordering.
        scores = np.einsum('sj,ij->si', weights, utilities, optimize=False)
        order = np.argsort(-scores, axis=1, kind='stable')
        ordered = np.take_along_axis(scores, order, axis=1)
        different = ordered[:, 1:] != ordered[:, :-1]
        left = np.maximum.accumulate(np.where(np.column_stack((np.ones(size, bool), different)), index, 0), axis=1)
        right = np.minimum.accumulate(np.where(np.column_stack((different, np.ones(size, bool))), index, n - 1)[:, ::-1], axis=1)[:, ::-1]
        lo, hi = np.empty_like(order), np.empty_like(order)
        np.put_along_axis(lo, order, left, axis=1)
        np.put_along_axis(hi, order, right, axis=1)
        credit = 1. / (hi - lo + 1)
        candidate_indices = np.broadcast_to(index, lo.shape)
        np.add.at(rank_diff, (candidate_indices.ravel(), lo.ravel()), credit.ravel())
        np.add.at(rank_diff, (candidate_indices.ravel(), (hi + 1).ravel()), -credit.ravel())
        top_credit = np.clip(effective_top - lo, 0, hi - lo + 1) * credit
        top_sum += top_credit.sum(axis=0)
        top_square += (top_credit**2).sum(axis=0)
        first_credit = (lo == 0) * credit
        first_sum += first_credit.sum(axis=0)
        first_square += (first_credit**2).sum(axis=0)
        # Fixed per-scenario accumulation order for every candidate.
        win_weights += np.einsum('si,sj->ij', first_credit, weights, optimize=False)
        if progress:
            progress(start + size, iterations)
    probabilities = np.maximum(np.cumsum(rank_diff[:, :n], axis=1), 0)
    del rank_diff
    probabilities /= probabilities.sum(axis=1, keepdims=True)
    result = []
    for i, row in enumerate(rows):
        p = probabilities[i]
        cumulative = np.cumsum(p)
        cumulative[-1] = 1.  # Avoid a spurious n+1 from floating-point drift.
        def quantile(q):
            return min(n, int(np.searchsorted(cumulative, q, side='left')) + 1)
        first = float(p[0])
        mean_top = min(1., max(0., float(top_sum[i] / iterations)))
        first_mean = float(first_sum[i] / iterations)
        first_se = math.sqrt(max(0., first_square[i] / iterations - first_mean**2) / iterations)
        se = math.sqrt(max(0., top_square[i] / iterations - mean_top**2) / iterations)
        quantiles = [{'q': float(q), 'rank': quantile(q)} for q in rank_quantiles]
        result.append({'id': row['id'], 'first_rank_acceptability': first,
                       'top_n_acceptability': mean_top, 'top_n_mc_se': se,
                       'first_rank_mc_se': first_se,
                       'expected_rank': float(p @ (index + 1)),
                       'median_rank': quantile(.5), 'rank_p05': quantile(.05), 'rank_p95': quantile(.95),
                       'rank_quantile_low': quantiles[0]['rank'], 'rank_quantile_high': quantiles[1]['rank'],
                       'rank_quantiles': quantiles,
                       'rank_acceptability': {str(r + 1): float(value) for r, value in enumerate(p) if value > 0},
                       'central_first_weights': ({s['key']: float(win_weights[i, j] / first_sum[i])
                                                 for j, s in enumerate(scales)} if first > 0 else None)})
    return {'configuration': config, 'rows': result}

"""Reproducible, preference-only SMAA on immutable saved screening values."""
from datetime import datetime, timezone
import csv
import hashlib
import json
import math
from pathlib import Path
import platform
import uuid

from src.admet.workflow import completed_run
from src.analysis.smaa import analyze_preferences, validate_scales, MAX_CANDIDATES
from src.core.calculation_cache import atomic_json, atomic_write
from src.reporting.combined import build_combined_data
from src.reporting.csv_safety import escape_cell, write_csv
from src.reporting.pareto_csv import read_criteria, choose_protocol, apply_criteria
from src.version import __version__
from src.reporting.smaa_html import render_smaa_html
from src.reporting.document_names import publish_documents

WORKFLOW_VERSION = 'smaa-saved-values-v2-input100k'
WARNING = ('Анализ чувствительности к предпочтениям при фиксированных свойствах. '
           'Доли сценариев не являются вероятностями экспериментального успеха, '
           'клинической безопасности или истинного превосходства. Докинг не равен '
           'измеренной активности. ADMET-оценки не определяют индивидуальную точность. '
           'Неопределённость предсказаний не моделируется.')


def _path(root, value):
    p = Path(value)
    return p if p.is_absolute() else Path(root) / p


def _sha(content):
    return hashlib.sha256(content).hexdigest()


def _source_inventory(run):
    return {name: _sha((run / name).read_bytes()) if (run / name).is_file() else None
            for name in ('preparation.json', 'results.json', 'summary.json', 'admet.json', 'task_outcomes.json')}


def _inputs(root, run_dir, criteria_path, target, protocol_id):
    run = completed_run(root, run_dir)
    before = _source_inventory(run)
    data = build_combined_data(root, run, include_images=False)
    if before != _source_inventory(run) or any(before[k] != v for k, v in data['source_sha256'].items()):
        raise ValueError('Исходные данные изменились во время чтения SMAA')
    data['source_sha256'] = before
    content = _path(root, criteria_path).read_bytes()
    criteria = read_criteria(content, data['endpoints'])
    objectives = [s for s in criteria if s['role'] == 'objective']
    if not objectives:
        raise ValueError('SMAA требует хотя бы одну цель «сравнивать» в CSV; режим только Парето сохранён')
    protocol = choose_protocol(data, target, protocol_id)
    if len(data['rows']) > MAX_CANDIDATES:
        raise ValueError(f'SMAA поддерживает до {MAX_CANDIDATES} исходных строк (включая исключённые)')
    return run, data, content, criteria, objectives, protocol


def create_smaa_template(root, run_dir, criteria_path, settings_path, *, target, protocol_id=None):
    """Create ONLY a new settings file; scales use protocol data before constraints."""
    run, data, content, criteria, objectives, protocol = _inputs(root, run_dir, criteria_path, target, protocol_id)
    scales = []
    for s in objectives:
        values = []
        for row in data['rows']:
            dock = row['docking'].get(protocol['target'], {})
            if dock.get('protocol') != protocol['id'] or type(dock.get('score')) not in (int, float):
                continue
            value = dock['score'] if s['key'] == 'docking_score' else row['values'].get(s['key'])
            if type(value) in (int, float) and math.isfinite(value):
                values.append(value)
        if not values:
            raise ValueError(f'{s["key"]}: нет конечных значений выбранного протокола для шаблона шкалы')
        scale = {'key': s['key'], 'direction': s['direction'], 'alpha': 1.0}
        origin = {'method': 'observed_protocol_values_before_constraints', 'finite_count': len(values),
                  'observed_min': min(values), 'observed_max': max(values),
                  'scope': 'selected protocol; each objective independently; before CSV bounds'}
        if s['direction'] == 'range':
            distances = [max(s['low'] - v, 0, v - s['high']) for v in values]
            scale.update(low=s['low'], high=s['high'], best=0., worst=max(distances) or 1.)
            origin['distance_max'] = max(distances)
            origin['constant_rule'] = 'if all distances zero, worst distance=1 in original units'
        else:
            lo, hi = min(values), max(values)
            if lo == hi:
                delta = max(abs(lo) * .01, .5)
                lo, hi = lo - delta, hi + delta
                origin['constant_rule'] = 'expand constant by +/-max(abs(value)*0.01,0.5); constant utility=0.5'
            scale.update(worst=lo if s['direction'] == 'max' else hi,
                         best=hi if s['direction'] == 'max' else lo)
        scale['origin'] = origin
        scales.append(scale)
    validate_scales(scales)
    settings = {'schema_version': 1, 'criteria_sha256': _sha(content), 'protocol_id': protocol['id'],
                'source_sha256': data['source_sha256'],
                'sampling': {'iterations': 10000, 'seed': 42, 'top_n': 10, 'batch_size': 64,
                             'rank_quantiles': [.05, .95], 'weight_distribution': 'Dirichlet'},
                'scales': scales,
                'notes': {'warning': WARNING,
                          'scale_rule': 'utility=clip((x-worst)/(best-worst),0,1); range uses distance to CSV target interval',
                          'weights': 'Dirichlet(alpha); alpha=1 is uniform over simplex, a chosen assumption',
                          'editing': 'worst=low desirability, best=high desirability, alpha=positive preference concentration. '
                                     'For range, worst/best are distances. Scales are fixed; changing CSV requires a new template.'}}
    path = _path(root, settings_path)
    if path.suffix.lower() != '.json':
        raise ValueError('Настройки шкал SMAA должны иметь расширение .json')
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        stream.write((json.dumps(settings, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8'))
    return path


def _read_settings(content, data, criteria_content, objectives, protocol):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f'Повторяющийся ключ JSON: {key}')
            result[key] = value
        return result
    try:
        doc = json.loads(content.decode('utf-8-sig'), object_pairs_hook=unique)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError('Настройки SMAA должны быть корректным JSON UTF-8') from error
    required = {'schema_version', 'criteria_sha256', 'protocol_id', 'source_sha256', 'sampling', 'scales'}
    if not isinstance(doc, dict) or not required <= doc.keys() or doc.keys() - required - {'notes'}:
        raise ValueError('Неверная схема настроек SMAA; создайте отдельный шаблон')
    if type(doc['schema_version']) is not int or doc['schema_version'] != 1:
        raise ValueError('Неизвестная версия настроек SMAA')
    if doc['criteria_sha256'] != _sha(criteria_content):
        raise ValueError('CSV критериев изменён после создания шкал SMAA; создайте новый шаблон')
    if doc['protocol_id'] != protocol['id'] or doc['source_sha256'] != data['source_sha256']:
        raise ValueError('Шкалы SMAA относятся к другим исходным данным или протоколу')
    sampling = doc['sampling']
    fields = {'iterations', 'seed', 'top_n', 'batch_size', 'rank_quantiles', 'weight_distribution'}
    if not isinstance(sampling, dict) or set(sampling) != fields or sampling['weight_distribution'] != 'Dirichlet':
        raise ValueError('Настройте iterations, seed, top_n, batch_size, rank_quantiles и weight_distribution=Dirichlet')
    scales = doc['scales']
    if not isinstance(scales, list) or any(not isinstance(s, dict) for s in scales):
        raise ValueError('scales должен быть списком шкал')
    if [s.get('key') for s in scales] != [s['key'] for s in objectives]:
        raise ValueError('Шкалы должны точно соответствовать целям CSV в том же порядке')
    for s, objective in zip(scales, objectives):
        allowed = {'key', 'direction', 'worst', 'best', 'alpha', 'origin', 'low', 'high'}
        if set(s) - allowed or s.get('direction') != objective['direction']:
            raise ValueError(f'{objective["key"]}: неизвестные поля или направление шкалы не совпадает с CSV')
        if s['direction'] == 'range' and (s.get('low') != objective['low'] or s.get('high') != objective['high']):
            raise ValueError(f'{s["key"]}: диапазон шкалы должен совпадать с CSV')
    options = {k: v for k, v in sampling.items() if k != 'weight_distribution'}
    analyze_preferences([], scales, **options)  # validate even an empty feasible set
    return doc, options


def run_smaa(root, run_dir, criteria_path, settings_path, *, target, protocol_id=None, progress=None, include_pareto=True):
    """Pareto + SMAA; publish complete directory only after calculation and source recheck."""
    run, data, criteria_content, criteria, objectives, protocol = _inputs(root, run_dir, criteria_path, target, protocol_id)
    settings_content = _path(root, settings_path).read_bytes()
    settings, options = _read_settings(settings_content, data, criteria_content, objectives, protocol)
    rows = apply_criteria(data, criteria, protocol)
    feasible = [r for r in rows if not r['selection']['reasons']]
    result = analyze_preferences(feasible, settings['scales'], progress=progress, **options)
    by_id = {r['id']: r for r in result['rows']}
    active_keys = [s['key'] for s in criteria if s['role'] != 'display']
    output_rows = []
    for r in rows:
        decision = r['selection']
        output_rows.append({'id': r['id'], 'row_id': r['row_id'], 'name': r['name'], 'smiles': r['smiles'],
                            'values': {k: r['values'].get(k) for k in active_keys},
                            'pareto_status': 'excluded' if decision['reasons'] else 'front' if decision['front'] else 'dominated',
                            'exclusion_reasons': decision['reasons'], 'dominator_ids': decision['dominators'],
                            'smaa': by_id.get(r['id'])})
    metadata = {'status': 'complete', 'analysis_mode': 'pareto+smaa' if include_pareto else 'smaa', 'workflow_version': WORKFLOW_VERSION,
                'application_version': __version__, 'python_version': platform.python_version(),
                'created_utc': datetime.now(timezone.utc).isoformat(), 'source_run': run.name,
                'source_sha256': data['source_sha256'], 'criteria_sha256': _sha(criteria_content),
                'settings_sha256': _sha(settings_content), 'protocol': protocol, 'criteria': criteria,
                'scales': settings['scales'], 'configuration': result['configuration'],
                'counts': {'total': len(rows), 'feasible': len(feasible),
                           'front': sum(r['selection']['front'] for r in rows)},
                'units': 'acceptability fractions in [0,1]; ranks are 1-based; excluded metrics=null/blank',
                'warning': WARNING,
                'scale_limitation': 'clipping can turn raw Pareto dominance into a utility tie; no hidden rescaling',
                'admet_metadata': data['admet_metadata']}
    parent = run / 'smaa'
    if parent.is_symlink() or (parent.exists() and not parent.resolve().is_relative_to(run)):
        raise ValueError('Папка результатов SMAA должна находиться внутри выбранного запуска')
    parent.mkdir(exist_ok=True)
    token = uuid.uuid4().hex
    staging, destination = parent / ('.incomplete-' + token), parent / ('analysis-' + token)
    staging.mkdir()
    atomic_json(staging / 'status.json', {'status': 'running'})
    try:
        atomic_write(staging / 'criteria.csv', criteria_content)
        atomic_write(staging / 'settings.json', settings_content)
        atomic_json(staging / 'metadata.json', metadata)
        atomic_json(staging / 'results.json', {**metadata, 'rows': output_rows})
        metric_keys = ['top_n_acceptability', 'first_rank_acceptability', 'expected_rank', 'median_rank',
                       'rank_quantile_low', 'rank_quantile_high', 'top_n_mc_se', 'first_rank_mc_se']
        headers = ['id', 'row_id', 'name', 'smiles', 'pareto_status', 'exclusion_reasons',
                   *['value__' + k for k in active_keys], *metric_keys]
        csv_rows = []
        for r in output_rows:
            csv_rows.append({**{k: r[k] for k in headers[:5]}, 'exclusion_reasons': '; '.join(r['exclusion_reasons']),
                             **{'value__' + k: r['values'][k] for k in active_keys},
                             **{k: (r['smaa'] or {}).get(k) for k in metric_keys}})
        write_csv(staging / 'candidates.csv', headers, csv_rows, bom=True,
                  text_columns=['id', 'row_id', 'name', 'smiles', 'pareto_status', 'exclusion_reasons'],
                  notes={'kind': 'smaa_candidates', 'units': metadata['units'], 'warning': WARNING})
        # Stream the potentially quadratic rank table; no StringIO copy of the table.
        with (staging / 'rank_acceptability.csv').open('w', encoding='utf-8-sig', newline='') as stream:
            writer = csv.writer(stream)
            writer.writerow(['id', 'rank', 'acceptability_fraction'])
            for r in result['rows']:
                for rank, value in r['rank_acceptability'].items():
                    writer.writerow([escape_cell(r['id']), int(rank), value])
        summary = (f'{"Парето + SMAA" if include_pareto else "SMAA"}: {len(rows)} исходных строк; {len(feasible)} допустимых; '
                   f'{metadata["counts"]["front"]} на фронте.\n'
                   f'Запрошенный топ-{options["top_n"]}; применённый топ-{result["configuration"]["effective_top_n"]}.\n'
                   f'Сценариев запрошено: {options["iterations"]}; выполнено: {result["configuration"]["completed_scenarios"]}; seed: {options["seed"]}.\n'
                   f'Веса Dirichlet(alpha={[s["alpha"] for s in settings["scales"]]}); это выбранное допущение.\n'
                   'Шкалы фиксированы; за якорями желательность насыщается до 0/1.\n'
                   'Рассмотрены все допустимые кандидаты, включая доминируемые.\n'
                   'Равные оценки поровну делят занятые места, включая границу топ-N.\n'
                   'Доли 0–1; исключённые строки имеют пустые метрики, а не последнее место.\n'
                   + ('Допустимый набор пуст; ранжирование отсутствует.\n' if not feasible else '')
                   + WARNING + '\n')
        atomic_write(staging / 'SUMMARY.txt', summary.encode('utf-8'))
        atomic_write(staging / 'report.html', render_smaa_html({**metadata, 'rows': output_rows},
                     include_pareto=include_pareto).encode('utf-8'))
        documents = publish_documents(staging, kind='PARETO-SMAA' if include_pareto else 'SMAA',
            target=protocol['target'], identity=token, created_utc=metadata['created_utc'],
            filenames=['report.html','results.json','candidates.csv','rank_acceptability.csv',
                       'metadata.json','criteria.csv','settings.json','SUMMARY.txt'])
        if _source_inventory(run) != data['source_sha256']:
            raise ValueError('Исходные файлы изменились во время SMAA; результат не опубликован')
        atomic_json(staging / 'status.json', {'status': 'complete'})
        staging.rename(destination)
    except BaseException as error:
        atomic_json(staging / 'status.json', {'status': 'cancelled' if isinstance(error, KeyboardInterrupt) else 'failed',
                                            'error': str(error)})
        raise
    return {'directory': str(destination), 'report_html': str(destination / documents['report.html']),
            'documents': documents, **metadata['counts'],
            'effective_top_n': result['configuration']['effective_top_n']}


def smaa_menu(root, console):
    """Separate template and execution actions; never invokes docking or ADMET."""
    from src.admet.workflow import available_runs
    runs = [p for p in available_runs(root) if (p / 'preparation.json').is_file()]
    if not runs:
        console.print('No completed runs with saved input rows.', markup=False)
        return
    for i, run in enumerate(runs, 1):
        console.print(f'{i}: {run.name}', markup=False)
    ordinal = int(console.input('Run number: ').strip())
    if not 1 <= ordinal <= len(runs):
        raise ValueError('Invalid run number')
    run = runs[ordinal - 1]
    mode = console.input('1 — scales template; 2 — Pareto + SMAA; 3 — SMAA only: ').strip()
    if mode not in ('1', '2', '3'):
        raise ValueError('Choose 1, 2 or 3')
    criteria = console.input('Criteria CSV path: ').strip().strip('"')
    settings = console.input('SMAA scales JSON path: ').strip().strip('"')
    data = build_combined_data(root, run, include_images=False)
    for i, p in enumerate(data['protocols'], 1):
        console.print(f'{i}: {p["label"]}', markup=False)
    number = int(console.input('Target/protocol number: ').strip())
    if not 1 <= number <= len(data['protocols']):
        raise ValueError('Invalid protocol')
    protocol = data['protocols'][number - 1]
    if mode == '1':
        path = create_smaa_template(root, run, criteria, settings, target=protocol['target'], protocol_id=protocol['id'])
        console.print(f'Template: {path}. Anchors use data before bounds. Review the JSON before running a separate analysis.', markup=False)
    else:
        console.print('Preference sensitivity with fixed values. Scenario fractions are not experimental or clinical success probabilities.', markup=False)
        result = run_smaa(root, run, criteria, settings, target=protocol['target'], protocol_id=protocol['id'],
                          progress=lambda done, total: console.print(f'SMAA: {done}/{total}', markup=False), include_pareto=mode=='2')
        console.print(f'HTML: {result["report_html"]}', markup=False)
        console.print(f'Results: {result["directory"]}; feasible: {result["feasible"]}; top-N: {result["effective_top_n"]}', markup=False)

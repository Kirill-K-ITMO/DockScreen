"""File-based Pareto selection. No model or docking calls, no browser settings."""
import csv
from datetime import datetime, timezone
import hashlib
from html import escape
import io
import json
import math
from pathlib import Path
import uuid

from src.core.calculation_cache import atomic_json, atomic_write
from src.reporting.combined import build_combined_data
from src.reporting.csv_safety import escape_cell, write_csv
from src.reporting.pareto import select_pareto
from src.reporting.document_names import publish_documents
from src.core.settings_paths import settings_path, editable_settings_path, run_settings_dir

HEADERS = ['Параметр', 'Использование', 'Направление', 'Не ниже', 'Не выше', 'Цель от', 'Цель до', 'Пояснение']
ROLES = {'сравнивать': 'objective', 'ограничение': 'constraint', 'не учитывать': 'display',
         'objective': 'objective', 'constraint': 'constraint', 'ignore': 'display', 'display': 'display'}
DIRECTIONS = {'минимум': 'min', 'максимум': 'max', 'диапазон': 'range', 'min': 'min', 'max': 'max', 'range': 'range'}
EXPLANATIONS = {
    'docking_score': 'Оценка докинга, kcal/mol. Меньше — предпочтительнее по этой цели; не экспериментальная активность.',
    'DILI': 'Выход классификатора 0–1. Не клиническая вероятность. Граница 0.5 — пользовательский сценарий, не норматив.',
    'ClinTox': 'Clinical Toxicity: выход классификатора 0–1. Не частота клинических осложнений; граница 0.5 — пользовательский сценарий.',
    'hERG': 'Выход классификатора 0–1: сигнал блокады hERG. Не клиническая вероятность; граница 0.5 — пользовательский сценарий.',
    'Bioavailability_Ma': 'Выход классификатора 0–1. Не процент биодоступности.',
}
DEFAULT_PRESET_ID = 'user-default-v3'
DEFAULT_PRESET = (
    {'key': 'docking_score', 'role': 'objective', 'direction': 'min', 'max': -7.0},
    {'key': 'DILI', 'role': 'objective', 'direction': 'min', 'max': 0.5},
    {'key': 'ClinTox', 'role': 'objective', 'direction': 'min', 'max': 0.5},
    {'key': 'Bioavailability_Ma', 'role': 'objective', 'direction': 'max', 'min': 0.5, 'max': None},
    {'key': 'hERG', 'role': 'objective', 'direction': 'min', 'max': 0.5},
)


def default_criteria(data):
    """An editable exploratory scenario, never a clinical acceptance standard."""
    return [{'min': None, 'low': None, 'high': None, **s} for s in DEFAULT_PRESET
            if s['key'] in data['endpoints']]


def _csv_bytes(rows):
    stream = io.StringIO(newline='')
    writer = csv.writer(stream, delimiter=';', lineterminator='\r\n')
    writer.writerow(HEADERS)
    for row in rows:
        writer.writerow([escape_cell(v) for v in row])
    return stream.getvalue().encode('utf-8-sig')


def write_criteria_template(data, path, *, catalogue=False):
    """Create a new editable UTF-8 CSV; never overwrite an existing input."""
    path = Path(path)
    if path.suffix.lower() != '.csv': raise ValueError('Файл настроек должен иметь расширение .csv')
    defaults = {s['key']: s for s in default_criteria(data)}
    keys = list(data['endpoints']) if catalogue else list(defaults)
    rows = []
    for key in keys:
        meta = data['endpoints'][key]
        note = EXPLANATIONS.get(key, f"{meta.get('name', key)}; единицы: {meta.get('units', 'не указаны')}")
        if meta.get('R^2') and float(meta['R^2']) < 0:
            note += ' В метаданных модели отрицательное R²: слабое качество на той оценке.'
        rows.append([key, 'не учитывать' if catalogue else 'сравнивать',
                     '' if catalogue else 'максимум' if defaults[key]['direction'] == 'max' else 'минимум',
                     defaults[key]['min'] if not catalogue and defaults[key]['min'] is not None else '',
                     defaults[key]['max'] if not catalogue and defaults[key]['max'] is not None else '', '', '', note])
    content = _csv_bytes(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        stream.write(content)
    return path


def read_criteria(content, endpoints):
    """Strict editable schema; decimal comma accepted in semicolon/quoted CSV."""
    try:
        text = content.decode('utf-8-sig')
    except UnicodeDecodeError:
        raise ValueError('Сохраните настройки как CSV UTF-8; кодировка файла не распознана') from None
    try:
        options = {'dialect': csv.Sniffer().sniff(text[:8192], delimiters=';,\t')}
    except csv.Error:
        options = {'delimiter': ';'}
    reader = csv.DictReader(io.StringIO(text, newline=''), strict=True, **options)
    fields = reader.fieldnames
    if not fields or len(fields) != len(set(fields)) or set(fields) != set(HEADERS):
        raise ValueError('Ожидаются столбцы: ' + '; '.join(HEADERS))
    settings, seen = [], set()
    for ordinal, row in enumerate(reader, 2):
        if None in row or any(v is None for v in row.values()):
            raise ValueError(f'Строка {ordinal}: неверное число столбцов')
        row = {k: v.strip() for k, v in row.items()}
        if not any(row.values()): continue
        key = row['Параметр']
        prefix = f'Строка {ordinal}, {key!r}: '
        if key not in endpoints: raise ValueError(prefix + 'неизвестный параметр; возьмите имя из каталога параметров')
        if key in seen: raise ValueError(prefix + 'параметр указан повторно')
        seen.add(key)
        role = ROLES.get(row['Использование'].casefold())
        if role is None: raise ValueError(prefix + 'использование: сравнивать / ограничение / не учитывать')
        if role == 'display':
            settings.append({'key': key, 'role': role, 'direction': 'min',
                             'min': None, 'max': None, 'low': None, 'high': None})
            continue
        direction = DIRECTIONS.get(row['Направление'].casefold()) if row['Направление'] else None
        if role == 'objective' and direction is None:
            raise ValueError(prefix + 'направление: минимум / максимум / диапазон')
        if role != 'objective' and row['Направление']:
            raise ValueError(prefix + 'направление заполняется только для «сравнивать»')
        values = {}
        for title, field in [('Не ниже', 'min'), ('Не выше', 'max'), ('Цель от', 'low'), ('Цель до', 'high')]:
            value = row[title]
            try:
                value = float(value.replace(',', '.')) if value else None
            except ValueError:
                raise ValueError(prefix + f'{title}: нужно число или пустая ячейка') from None
            if value is not None and not math.isfinite(value):
                raise ValueError(prefix + f'{title}: число должно быть конечным')
            values[field] = value
        if values['min'] is not None and values['max'] is not None and values['min'] > values['max']:
            raise ValueError(prefix + '«Не ниже» больше «Не выше»')
        if role == 'constraint' and values['min'] is None and values['max'] is None:
            raise ValueError(prefix + 'для ограничения заполните хотя бы одну границу')
        if direction == 'range':
            if values['low'] is None or values['high'] is None or values['low'] > values['high']:
                raise ValueError(prefix + 'заполните корректный желаемый диапазон «Цель от» / «Цель до»')
        elif values['low'] is not None or values['high'] is not None:
            raise ValueError(prefix + '«Цель от» / «Цель до» нужны только для направления «диапазон»')
        settings.append({'key': key, 'role': role, 'direction': direction or 'min', **values})
    if not any(s['role'] != 'display' for s in settings):
        raise ValueError('В CSV не выбрано ни одной цели или ограничения')
    return settings


def choose_protocol(data, target, protocol_id=None):
    if not target: raise ValueError('Явно выберите мишень/профиль для отбора')
    protocols = [p for p in data['protocols'] if p['target'] == target and
                 (protocol_id is None or p['id'] == protocol_id)]
    if len(protocols) != 1:
        raise ValueError('Выберите один конкретный протокол. Доступны: ' +
                         ', '.join(p['id'] for p in data['protocols'] if p['target'] == target))
    return protocols[0]


def apply_criteria(data, settings, protocol):
    rows = []
    for original in data['rows']:
        dock = original['docking'].get(protocol['target'], {})
        matched = dock.get('protocol') == protocol['id']
        score = dock.get('score') if matched else None
        rows.append({**original, 'values': {**original['values'], 'docking_score': score},
                     'eligible': matched and type(score) in (float, int) and math.isfinite(score),
                     'error': 'Несовместимый протокол докинга' if dock.get('protocol') and not matched else
                              dock.get('error') or 'Нет успешного докинга для выбранного протокола'})
    decisions = select_pareto(rows, settings)
    return [{**row, 'selection': decision} for row, decision in zip(rows, decisions)]


def run_pareto(root, run_dir, criteria_path, *, target, protocol_id=None, preset_id=None):
    """Evaluate immutable input bytes, create a NEW reproducible selection directory."""
    from src.admet.workflow import completed_run
    root = Path(root).resolve()
    run_dir = completed_run(root, run_dir)
    criteria_path = Path(criteria_path)
    if not criteria_path.is_absolute(): criteria_path = root / criteria_path
    content = criteria_path.read_bytes()
    data = build_combined_data(root, run_dir)
    settings = read_criteria(content, data['endpoints'])
    protocol = choose_protocol(data, target, protocol_id)
    rows = apply_criteria(data, settings, protocol)
    counts = {'total': len(rows), 'feasible': sum(not r['selection']['reasons'] for r in rows),
              'front': sum(r['selection']['front'] for r in rows),
              'objectives': sum(s['role'] == 'objective' for s in settings)}
    document = {'schema_version': 1, 'created_utc': datetime.now(timezone.utc).isoformat(),
                'preset_id': preset_id,
                'source_run': run_dir.name, 'source_sha256': data['source_sha256'],
                'criteria_sha256': hashlib.sha256(content).hexdigest(), 'criteria': settings,
                'protocol': protocol, 'counts': counts, 'endpoints': data['endpoints'],
                'admet_metadata': data['admet_metadata'],
                'note': 'Технический отбор по модельным оценкам; клиническая пригодность не установлена.'}
    token = uuid.uuid4().hex
    destination = run_dir / 'pareto' / ('selection-' + token)
    staging = run_dir / 'pareto' / ('.incomplete-' + token)
    staging.mkdir(parents=True)
    atomic_write(staging / 'criteria.csv', content)
    atomic_json(staging / 'settings.json', document)
    atomic_json(staging / 'selection.json', {**document, 'rows': [{k: v for k, v in r.items() if k != 'image'} for r in rows]})
    metrics = [s['key'] for s in settings if s['role'] != 'display']
    fields = ['row_id', 'name', 'smiles', 'selection_status', 'reasons', 'dominator_row_ids', *metrics]
    table = []
    for row in rows:
        d = row['selection']
        status = 'excluded' if d['reasons'] else 'front' if d['front'] else 'dominated' if d['dominators'] else 'feasible_no_objectives'
        table.append({'row_id': row['row_id'], 'name': row['name'], 'smiles': row['smiles'],
                      'selection_status': status, 'reasons': '; '.join(d['reasons']),
                      'dominator_row_ids': ', '.join(d['dominators']), **{k: row['values'].get(k) for k in metrics}})
    for filename, selected in [('all_candidates.csv', table),
                               ('feasible.csv', [r for r in table if r['selection_status'] != 'excluded']),
                               ('front.csv', [r for r in table if r['selection_status'] == 'front'])]:
        write_csv(staging / filename, fields, selected,
                  text_columns=['name', 'smiles', 'selection_status', 'reasons', 'dominator_row_ids'],
                  notes={'kind': 'pareto_selection', 'settings': document}, bom=True)
    atomic_write(staging / 'report.html', _html(document, rows, metrics).encode('utf-8'))
    documents = publish_documents(staging, kind='PARETO', target=protocol['target'], identity=token,
        created_utc=document['created_utc'], filenames=['report.html','all_candidates.csv','feasible.csv',
            'front.csv','selection.json','criteria.csv','settings.json'])
    staging.rename(destination)
    return {'directory': str(destination), 'report_html': str(destination / documents['report.html']),
            'documents': documents, **counts}


def run_default_pareto(root, run_dir):
    """Save/apply a named default independently for each recorded protocol."""
    run_dir = Path(run_dir)
    data = build_combined_data(root, run_dir)
    missing = {s['key'] for s in DEFAULT_PRESET} - set(data['endpoints'])
    if missing:
        raise ValueError('Для полного набора по умолчанию отсутствуют параметры: ' + ', '.join(sorted(missing)))
    settings = default_criteria(data)
    rows = [[s['key'], 'сравнивать', 'максимум' if s['direction'] == 'max' else 'минимум',
             s['min'] if s['min'] is not None else '', s['max'] if s['max'] is not None else '',
             '', '', EXPLANATIONS[s['key']]] for s in settings]
    content = _csv_bytes(rows)
    key = hashlib.sha256(content).hexdigest()
    path = run_settings_dir(run_dir) / f'{DEFAULT_PRESET_ID}-{key[:16]}.csv'
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open('xb') as stream: stream.write(content)
    except FileExistsError:
        if path.read_bytes() != content: raise ValueError('Default Pareto preset was modified; refusing to replace it')
    create_templates(root, run_dir, editable_settings_path(root, 'PARETO_CRITERIA.csv'))
    results = []
    for protocol in data['protocols']:
        result = run_pareto(root, run_dir, path, target=protocol['target'], protocol_id=protocol['id'],
                            preset_id=DEFAULT_PRESET_ID)
        results.append({'preset': DEFAULT_PRESET_ID, 'target': protocol['target'],
                        'protocol_id': protocol['id'], 'criteria_csv': str(path), **result})
    atomic_json(run_dir / 'pareto/default_selections.json', {'preset': DEFAULT_PRESET_ID,
        'warning': 'Exploratory user-editable scenario, not a clinical standard.', 'results': results})
    return results


def create_templates(root, run_dir, criteria_path=None):
    from src.admet.workflow import completed_run
    run_dir = completed_run(root, run_dir)
    data = build_combined_data(root, run_dir)
    path = Path(criteria_path) if criteria_path is not None else run_settings_dir(run_dir) / 'pareto_criteria.csv'
    if not path.is_absolute(): path = Path(root).resolve() / path
    if not path.exists(): write_criteria_template(data, path)
    catalogue = run_settings_dir(run_dir) / 'pareto_parameters.csv'
    if not catalogue.exists(): write_criteria_template(data, catalogue, catalogue=True)
    return path, catalogue


def pareto_csv_menu(root, console):
    from src.admet.workflow import available_runs, prepare_run
    root = Path(root).resolve()
    runs = available_runs(root)
    if not runs:
        console.print('No completed runs. Finish docking first.', markup=False)
        return
    for i, run in enumerate(runs, 1):
        console.print(f'{i}: {run.name}' + (' · ADMET available' if (run / 'admet.json').exists() else ' · ADMET unavailable'), markup=False)
    index = int(console.input('Run number [1]: ').strip() or '1')
    if not 1 <= index <= len(runs): raise ValueError('Invalid run number')
    run = prepare_run(root, runs[index - 1])
    path, catalogue = create_templates(root, run, editable_settings_path(root, 'PARETO_CRITERIA.csv'))
    visible_catalogue = settings_path(root, 'PARETO_PARAMETERS.csv')
    if not visible_catalogue.exists():
        write_criteria_template(build_combined_data(root, run), visible_catalogue, catalogue=True)
    catalogue = visible_catalogue
    console.print(f'Settings: {path}', markup=False)
    console.print(f'Available parameter catalogue: {catalogue}', markup=False)
    console.print('Edit and save the CSV. Unlisted parameters do not affect selection.\n'
                  'сравнивать = Pareto objective; ограничение = filter only; не учитывать = disabled.\n'
                  'Не ниже / Не выше = bounds; Цель от / Цель до = desired interval without exclusion.\n'
                  'DILI/ClinTox/hERG bounds 0.5 define a user scenario, not clinical standards.\n'
                  'Bioavailability_Ma ≥0.5 means a model score, not percent bioavailability.', markup=False)
    action = console.input('Enter — templates ready, exit; 1 — apply saved CSV: ').strip()
    if not action: return
    if action != '1': raise ValueError('Enter 1 to run selection or Enter to exit')
    supplied = console.input('Other CSV (Enter = settings file above): ').strip().strip('"')
    if supplied: path = Path(supplied)
    data = build_combined_data(root, run)
    for i, p in enumerate(data['protocols'], 1):
        options = p.get('spec', {}).get('options', {})
        console.print(f'{i}: {p["target"]} · scoring={options.get("scoring", "unknown")} · '
                      f'exhaustiveness={options.get("exhaustiveness", "unknown")} · {p["id"]}', markup=False)
    index = int(console.input('Target/protocol number for this selection: ').strip())
    if not 1 <= index <= len(data['protocols']): raise ValueError('Invalid protocol number')
    protocol = data['protocols'][index - 1]
    result = run_pareto(root, run, path, target=protocol['target'], protocol_id=protocol['id'])
    console.print(f'Total: {result["total"]}; feasible: {result["feasible"]}; front: {result["front"]}', markup=False)
    console.print(f'HTML: {result["report_html"]}', markup=False)
    console.print(f'Done: {result["directory"]}\nOpen the named HTML report or front.csv in this folder.', markup=False)


def _html(document, rows, metrics):
    """Read-only summary with escaped scientific labels and original names."""
    def h(value): return escape(str(value))
    c = document['counts']
    result = ['<!doctype html><html lang="ru"><meta charset="utf-8"><title>DockScreen — отбор из CSV</title>',
              '<style>body{font:15px system-ui;background:#f4f7f2;color:#183b32;margin:32px}section{background:white;padding:24px;margin:18px 0;border-radius:12px}table{border-collapse:collapse;width:100%}td,th{padding:10px;text-align:left;border-bottom:1px solid #d6dfd7}pre{white-space:pre-wrap}img{max-width:260px}.scroll{overflow:auto}.front{color:#007361}small{color:#52675e}</style>',
              '<h1>Отбор кандидатов по CSV</h1>', f'<p>Мишень: <b>{h(document["protocol"]["target"])}</b></p>',
              f'<section><h2>Total: {c["total"]} · feasible: {c["feasible"]} · фронт Парето: {c["front"]}</h2>',
              '<p>Настройки взяты из criteria.csv. Для изменения отбора отредактируйте исходный CSV и запустите отбор ещё раз. Докинг и ADMET повторяться не будут.</p>']
    if not c['objectives']: result.append('<p>Цели сравнения не выбраны: показаны прошедшие ограничения, фронт не определяется.</p>')
    elif not c['feasible']: result.append('<p>Ни один кандидат не прошёл ограничения. Причины перечислены в таблице; проверьте заданные границы и наличие значений.</p>')
    result.append('<p>Докинг не равен экспериментальной активности. ADMET-классификаторы не являются клиническими вероятностями; Bioavailability_Ma не процент. Неопределённость не оценена.</p></section><section><h2>Применённые настройки</h2><table><tr><th>Параметр</th><th>Использование</th><th>Цель</th><th>Допустимые границы</th><th>Желаемый диапазон</th></tr>')
    for s in document['criteria']:
        if s['role'] == 'display': continue
        meta = document['endpoints'].get(s['key'], {})
        note = EXPLANATIONS.get(s['key'], '')
        if meta.get('R^2') and float(meta['R^2']) < 0:
            note += ' Отрицательное R² в метаданных модели: слабое качество на этой оценке.'
        caption = s['key'] + (f' ({meta["units"]})' if meta.get('units') not in (None, '', '-') else '')
        if note: caption += ' — ' + note
        result.append('<tr>' + ''.join(f'<td>{h(v)}</td>' for v in [caption, 'Сравнивать' if s['role'] == 'objective' else 'Только ограничение',
            {'min': 'Меньше', 'max': 'Больше', 'range': 'К диапазону'}[s['direction']] if s['role'] == 'objective' else '—',
            f'{s["min"] if s["min"] is not None else "без нижней"} … {s["max"] if s["max"] is not None else "без верхней"}',
            f'{s["low"]} … {s["high"]}' if s['direction'] == 'range' else '—']) + '</tr>')
    result.append('</table></section>' + _projection_svg(rows, metrics))
    result.append('<section><h2>Все кандидаты и причины отбора</h2><div class="scroll"><table><tr>' + ''.join(f'<th>{h(v)}</th>' for v in ['Строка', 'Имя', *metrics, 'Результат']) + '</tr>')
    names = {r['id']: f'{r["name"]} (строка {r["row_id"]})' for r in rows}
    for r in rows:
        d = r['selection']
        status = '; '.join(d['reasons']) if d['reasons'] else 'Фронт Парето' if d['front'] else 'Доминируют: ' + ', '.join(names[i] for i in d['dominators']) if d['dominators'] else 'Прошёл ограничения; цели не выбраны'
        result.append('<tr>' + ''.join(f'<td>{h(v)}</td>' for v in [r['row_id'], r['name'], *[r['values'].get(k) if r['values'].get(k) is not None else 'нет значения' for k in metrics], status]) + '</tr>')
    result.append('</table></div></section><section><h2>Структуры кандидатов фронта</h2>'
        '<p>Краткое досье каждого кандидата. DILI, ClinTox, hERG и AMES — модельные сигналы токсичности, '
        'не клинические вероятности. Bioavailability_Ma — оценка классификатора 0–1, не процент биодоступности. '
        'Индивидуальная неопределённость не оценена. Показанные числа округлены; точные значения — в CSV/JSON и подсказках.</p>'
        '<style>.dossier-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,320px),1fr));gap:18px}'
        '.candidate-dossier{border:1px solid #d4dfd6;border-radius:12px;padding:18px;min-width:0;background:#fafcf8}'
        '.candidate-dossier h3{margin:0 0 12px;overflow-wrap:anywhere}.candidate-dossier img{display:block;margin:0 auto 12px;max-width:100%}'
        '.dossier-smiles{overflow-wrap:anywhere;white-space:pre-wrap;font-size:12px;background:#edf3eb;padding:10px;border-radius:6px}'
        '.dossier-values{margin:12px 0}.dossier-values>div{display:flex;justify-content:space-between;gap:12px;padding:8px 0;border-bottom:1px solid #e0e7dc}'
        '.dossier-values dt{font-size:13px}.dossier-values dd{font-weight:650;margin:0;text-align:right;font-variant-numeric:tabular-nums}'
        '.dossier-values small{display:block;font-weight:400}.candidate-dossier summary{cursor:pointer}</style><div class="dossier-grid">')
    for row in [r for r in rows if r['selection']['front']][:200]:
        result.append(_candidate_dossier(row))
    result.append('</div><p>Полные структуры и исходные значения сохранены в selection.json; при фронте больше 200 строк здесь показаны первые 200.</p></section><details><summary>Протокол и происхождение</summary><pre>' + h(json.dumps(document, ensure_ascii=False, indent=2)) + '</pre></details></html>')
    return ''.join(result)


def _candidate_dossier(row):
    def h(value): return escape(str(value))
    def metric(key, label, unit):
        value = row['values'].get(key)
        available = type(value) in (int, float) and math.isfinite(value)
        display = format(value, '.6g') if available else 'нет значения'
        exact = f'Точное значение: {value}' if available else 'Значение не рассчитано или недоступно'
        return f'<div><dt>{h(label)}<small>{h(unit)}</small></dt><dd data-endpoint="{h(key)}" title="{h(exact)}">{h(display)}</dd></div>'
    html = [f'<article class="candidate-dossier" data-row-id="{h(row["row_id"])}"><h3>{h(row["name"])}</h3><small>Строка {h(row["row_id"])}</small>']
    if row.get('image'): html.append(f'<img src="{h(row["image"])}" alt="Структура {h(row["name"])}">')
    html.append(f'<p><strong>SMILES</strong></p><pre class="dossier-smiles">{h(row["smiles"])}</pre><dl class="dossier-values">')
    html.extend(metric(*args) for args in [
        ('docking_score','Оценка докинга','kcal/mol'),
        ('DILI','DILI · повреждение печени','модельная оценка 0–1'),
        ('ClinTox','ClinTox · клиническая токсичность','модельная оценка 0–1'),
        ('Bioavailability_Ma','Bioavailability_Ma · биодоступность','модельная оценка 0–1, не %')])
    html.append('</dl>')
    if any(k in row['values'] for k in ('hERG','AMES')):
        html.append('<details><summary>Другие сигналы токсичности</summary><dl class="dossier-values">')
        html.extend(metric(*args) for args in [('hERG','hERG · блокирование канала','модельная оценка 0–1'),
            ('AMES','AMES · мутагенность','модельная оценка 0–1')])
        html.append('</dl></details>')
    statuses={'success':'рассчитан','prediction_failed':'ошибка расчёта','not_run':'не рассчитан','not_selected':'не выбран для расчёта','invalid_structure':'ошибка структуры'}
    html.append(f'<p><small>ADMET: {h(statuses.get(row.get("admet_status"),row.get("admet_status","unknown")))}</small></p></article>')
    return ''.join(html)


def _projection_svg(rows, metrics):
    if len(metrics) < 2: return ''
    xkey, ykey = metrics[:2]
    points = [r for r in rows if all(type(r['values'].get(k)) in (int, float) and
              math.isfinite(r['values'][k]) for k in (xkey, ykey))]
    if not points: return ''
    xmin, xmax = min(r['values'][xkey] for r in points), max(r['values'][xkey] for r in points)
    ymin, ymax = min(r['values'][ykey] for r in points), max(r['values'][ykey] for r in points)
    if xmin == xmax: xmin, xmax = xmin - .5, xmax + .5
    if ymin == ymax: ymin, ymax = ymin - .5, ymax + .5
    output = ['<section><h2>Проекция отбора</h2><p>Зелёный — фронт по всем целям CSV; серый — прошедшие ограничения, оранжевый — исключённые. Показаны исходные значения первых двух активных параметров. Это проекция, а не отдельный отбор по двум осям.</p>',
              '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 700 360" style="width:100%;max-width:850px" role="img" aria-label="Проекция отбора"><path d="M80 25V300H670" fill="none" stroke="#658575"/>']
    xx = lambda value: 80 + (value - xmin) / (xmax - xmin) * 570
    yy = lambda value: 300 - (value - ymin) / (ymax - ymin) * 260
    for i in range(5):
        x, y = xmin + (xmax - xmin) * i / 4, ymin + (ymax - ymin) * i / 4
        output.append(f'<text x="{xx(x)}" y="320" text-anchor="middle" font-size="12">{x:.4g}</text><text x="72" y="{yy(y)}" text-anchor="end" font-size="12">{y:.4g}</text>')
    output.append(f'<text x="350" y="347" text-anchor="middle">{escape(xkey)}</text><text x="10" y="18">{escape(ykey)}</text>')
    for row in points:
        d = row['selection']
        color = '#be8635' if d['reasons'] else '#00846c' if d['front'] else '#95a79f'
        title = escape(f'{row["name"]}, строка {row["row_id"]}; {xkey}={row["values"][xkey]}; {ykey}={row["values"][ykey]}')
        output.append(f'<circle cx="{xx(row["values"][xkey])}" cy="{yy(row["values"][ykey])}" r="5" fill="{color}"><title>{title}</title></circle>')
    return ''.join(output) + '</svg></section>'

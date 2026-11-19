"""Import a native DockScreen report as a NEW saved run, without calculations.

Only docking score columns are used as scientific values. Existing ADMET columns
are retained in the byte-exact report snapshot but are not trusted as predictions:
subsequent enrichment computes/loads locally validated ADMET in the usual way.
"""
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
import math
from pathlib import Path
import re
import shutil
import stat
import uuid

from src.core.calculation_cache import atomic_json, atomic_write
from src.reporting.csv_safety import (decode_cell, load_export_metadata,
    notes_path, validate_export_metadata, write_csv)

IMPORT_VERSION = 'dockscreen-native-csv-v1'
MAX_ROWS = 100000
MAX_TARGETS = 64
MAX_SCORE_PAIRS = 100000
MAX_REPORT_BYTES = 64 * 1024 * 1024
MAX_NOTES_BYTES = 8 * 1024 * 1024
MAX_ROW_ID = 2**53 - 1
SCORE_SUFFIX = '_delta_g'


def _source(path, root):
    path = Path(path).expanduser()
    if not path.is_absolute():
        path = root / path
    path = path.resolve()
    if not path.is_file() or path.suffix.lower() != '.csv':
        raise ValueError('Выберите CSV-отчёт DockScreen (.csv)')
    if path.stat().st_size > MAX_REPORT_BYTES:
        raise ValueError('CSV-отчёт превышает предел 64 MiB')
    data = path.read_bytes()
    if len(data) > MAX_REPORT_BYTES:
        raise ValueError('CSV-отчёт превышает предел 64 MiB')
    sidecar = notes_path(path)
    if sidecar.exists() and (not sidecar.is_file() or sidecar.stat().st_size > MAX_NOTES_BYTES):
        raise ValueError('Некорректный или слишком большой файл метаданных CSV (предел 8 MiB)')
    notes = sidecar.read_bytes() if sidecar.exists() else None
    marker = load_export_metadata(path, data)
    # The snapshot must describe exactly the marker used for decoding, even if
    # another process edits the optional sidecar concurrently.
    if notes is not None:
        try:
            snapshot_document = json.loads(notes.decode('utf-8'))
        except (UnicodeError, json.JSONDecodeError) as error:
            raise ValueError('Не удалось прочитать метаданные CSV') from error
        snapshot_marker = (snapshot_document.get('csv_safety')
                           if isinstance(snapshot_document, dict) else None)
        if snapshot_marker != marker:
            raise ValueError('Метаданные CSV изменились во время чтения')
        if marker is not None:
            validate_export_metadata(data, snapshot_marker)
    elif marker is not None:
        raise ValueError('Метаданные CSV изменились во время чтения')
    return path, data, notes, marker


def _parse(data, marker):
    try:
        text = data.decode('utf-8-sig')
        reader = csv.reader(io.StringIO(text, newline=''), strict=True)
        raw_headers = next(reader)
        headers = ([decode_cell(h) for h in raw_headers] if marker else raw_headers)
        if not headers or any(not h for h in headers) or len(set(headers)) != len(headers):
            raise ValueError('CSV должен иметь непустые неповторяющиеся заголовки')
        if not {'name', 'smiles'}.issubset(headers):
            raise ValueError('Нужен CSV-отчёт DockScreen с колонками name и smiles; таблица молекул без докинга не подходит')
        targets = [h[:-len(SCORE_SUFFIX)] for h in headers
                   if h.endswith(SCORE_SUFFIX) and not h.startswith('ADMET__')]
        if not targets or any(not t for t in targets):
            raise ValueError('В отчёте нет колонок докинга <мишень>_delta_g')
        if len(targets) > MAX_TARGETS:
            raise ValueError(f'Импорт поддерживает до {MAX_TARGETS} мишеней в одном CSV')
        missing = [t + suffix for t in targets for suffix in ('_ki', '_ki_formatted', '_pki')
                   if t + suffix not in headers]
        if missing:
            raise ValueError('Неполная схема отчёта DockScreen: отсутствуют ' + ', '.join(missing))
        text_columns = set(marker['text_columns']) if marker else set()
        rows, seen = [], set()
        for physical_row, cells in enumerate(reader, 1):
            if (len(rows) + 1) * len(targets) > MAX_SCORE_PAIRS:
                raise ValueError(f'Импорт поддерживает до {MAX_SCORE_PAIRS} пар молекула/мишень; разделите CSV')
            if len(rows) >= MAX_ROWS:
                raise ValueError(f'Импорт поддерживает до {MAX_ROWS} строк; разделите CSV')
            if len(cells) != len(headers):
                raise ValueError(f'CSV, строка данных {physical_row}: число ячеек не совпадает с заголовком')
            row = {h: decode_cell(v) if h in text_columns else v for h, v in zip(headers, cells)}
            if 'row_id' in row:
                raw_id = row['row_id'].strip()
                if not re.fullmatch(r'[0-9]+', raw_id) or len(raw_id) > 32:
                    raise ValueError(f'CSV, строка данных {physical_row}: row_id должен быть положительным целым')
                row_id = int(raw_id)
                if not 1 <= row_id <= MAX_ROW_ID:
                    raise ValueError(f'CSV, строка данных {physical_row}: row_id должен быть от 1 до {MAX_ROW_ID}')
            else:
                row_id = physical_row
            if row_id in seen:
                raise ValueError(f'CSV: повторяющийся row_id {row_id}')
            seen.add(row_id)
            scores = {}
            for target in targets:
                value = row[target + SCORE_SUFFIX].strip()
                if not value:
                    scores[target] = None
                    continue
                try:
                    score = float(value)
                except (ValueError, OverflowError) as error:
                    raise ValueError(f'CSV, строка {row_id}, {target}: docking score должен быть числом или пустой ячейкой') from error
                if not math.isfinite(score):
                    raise ValueError(f'CSV, строка {row_id}, {target}: docking score должен быть конечным числом')
                scores[target] = score
            rows.append({'row_id': row_id, 'label': f'row_{physical_row:06d}',
                         'name': row['name'], 'smiles': row['smiles'], 'scores': scores})
    except (UnicodeError, csv.Error, StopIteration) as error:
        raise ValueError('Невозможно прочитать CSV-отчёт: требуется UTF-8 и разделитель запятая') from error
    if not rows:
        raise ValueError('CSV-отчёт не содержит строк молекул')
    return rows, targets, headers


def _runs_parent(root):
    # Never follow output/runs links or junctions into another project or into
    # existing user directories. The resolved project root itself is intentional.
    for part in ('output', 'output/runs'):
        path = root / part
        if path.exists() or path.is_symlink():
            info = path.lstat()
            if (stat.S_ISLNK(info.st_mode)
                    or getattr(info, 'st_file_attributes', 0) & 0x400
                    or path.resolve() != path):
                raise ValueError('Папка output/runs не должна содержать символические ссылки или junction')
            if not path.is_dir():
                raise ValueError('output/runs должен быть папкой')
        else:
            path.mkdir()
    return root / 'output/runs'


def import_docking_csv(root, path):
    """Return a new completed run reconstructed from a native CSV report.

    Existing rows, including duplicate names, empty SMILES and missing scores,
    are retained. Missing scores never become successful docking records. Native
    report-derived Ki/pKi and any ADMET columns are deliberately not imported as
    independent measurements or verified predictions. Original files are read-only.
    """
    root = Path(root).resolve()
    if not root.is_dir():
        raise ValueError('Папка проекта не существует')
    source, data, notes, marker = _source(path, root)
    rows, targets, headers = _parse(data, marker)
    sha = hashlib.sha256(data).hexdigest()
    warnings = [
        'Импортированы только docking score из сохранённого отчёта; докинг и подготовка структур не запускались.',
        'Исходный протокол докинга неизвестен: CSV не восстанавливает receptor/config/engine/seed provenance.',
        'Ki/pKi из отчёта не являются независимыми измерениями и не используются при импорте.',
    ]
    if marker is None:
        warnings.append('Нет проверенного csv_safety-маркера: текст сохранён буквально; апострофы экранирования невозможно надёжно отличить от исходного текста.')
    if any(h.startswith('ADMET__') for h in headers) or 'admet_status' in headers:
        warnings.append('Существующие ADMET-столбцы сохранены только в снимке CSV и не приняты как проверенные предсказания; нужен отдельный локальный ADMET-анализ.')
    parent = _runs_parent(root)
    identifier = uuid.uuid4().hex
    destination = parent / ('csv-import-' + identifier)
    stage = root / 'output' / ('.csv-import-stage-' + identifier)
    stage.mkdir()
    try:
        snapshot = stage / 'reports/import'
        snapshot.mkdir(parents=True)
        atomic_write(snapshot / 'source_report.csv', data)
        source_hashes = {'source_report.csv': sha}
        if notes is not None:
            atomic_write(snapshot / 'source_report.csv.notes.json', notes)
            source_hashes['source_report.csv.notes.json'] = hashlib.sha256(notes).hexdigest()
        spec = {'kind': 'imported_csv', 'report_format': IMPORT_VERSION,
                'source_report_sha256': sha,
                'source_protocol': 'unknown; original docking protocol unavailable in CSV'}
        preparation, results, outcomes = [], {}, {}
        for row in rows:
            original = {k: row[k] for k in ('row_id', 'label', 'name', 'smiles')}
            preparation.append({**original, 'status': 'imported_csv',
                                'identity_source': 'saved_csv_report',
                                'preparation_note': 'No conformer preparation was performed during import'})
            records, failures = {}, {}
            for target, score in row['scores'].items():
                if score is None:
                    failures[target] = {'status': 'not_available',
                                        'error': 'В исходном CSV отсутствует docking score'}
                else:
                    records[target] = {'selection_row_id': row['row_id'],
                        'input_name': row['name'], 'smiles': row['smiles'],
                        'affinity': score, 'spec': dict(spec),
                        'source': 'imported_csv_score', 'scoring': 'unknown'}
            results[row['label']] = records
            if failures:
                outcomes[row['label']] = failures
        atomic_json(stage / 'preparation.json', preparation)
        atomic_json(stage / 'results.json', results)
        atomic_json(stage / 'task_outcomes.json', outcomes)
        successful = sum(len(records) for records in results.values())
        metadata = {'schema_version': 1, 'kind': 'imported_docking_csv',
            'import_version': IMPORT_VERSION, 'created_utc': datetime.now(timezone.utc).isoformat(),
            'source_csv': str(source), 'source_sha256': source_hashes,
            'source_protocol': spec['source_protocol'],
            'csv_safety_decoded': marker is not None,
            'text_decoding': 'validated marked text columns only' if marker else 'literal text; no unescaping',
            'existing_admet_policy': 'ignored; source bytes retained; use local enrichment',
            'row_id_policy': 'preserved unique positive integer' if 'row_id' in headers else 'one-based CSV data-record order',
            'input_rows': len(rows), 'receptors': targets, 'successful_pairs': successful,
            'failed_pairs': len(rows) * len(targets) - successful,
            'new_docking_calculations': 0, 'new_preparation_calculations': 0,
            'warnings': warnings}
        atomic_json(snapshot / 'import_metadata.json', metadata)
        write_csv(stage / 'input.csv', ['row_id', 'name', 'smiles'], preparation,
                  text_columns=['name', 'smiles'], bom=True,
                  notes={'kind': 'reconstructed_report_identities', 'source_report_sha256': sha,
                         'warning': 'Reconstructed row identities, not the original pre-docking ligand input.'})
        atomic_json(stage / 'summary.json', {**metadata, 'run_dir': str(destination),
                    'status': 'complete', 'completion_kind': 'CSV import, not docking execution',
                    'input_csv_snapshot': str(destination / 'input.csv')})
        stage.rename(destination)
    except BaseException:
        # The stage is a freshly generated exact child of output; remove only it.
        # Even a failed cleanup cannot expose it through output/runs discovery.
        if stage.is_dir() and stage.resolve().parent == (root / 'output').resolve():
            shutil.rmtree(stage)
        raise
    return destination

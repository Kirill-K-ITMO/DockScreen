"""Reversible spreadsheet-safe CSV presentation with hash-bound import metadata."""
import csv
import hashlib
import io
import json
from pathlib import Path

POLICY = 'apostrophe-v1'


def escape_cell(value):
    """Protect text, including formula-like headers; leave numeric values numeric."""
    if not isinstance(value, str) or not value:
        return value
    probe = value
    while probe and (probe[0].isspace() or ord(probe[0]) < 32 or ord(probe[0]) == 127 or probe[0] == '\ufeff'):
        probe = probe[1:]
    if value.startswith("'") or (probe and probe[0] in '=+-@'):
        return "'" + value
    return value


def decode_cell(value):
    """Only call on cells covered by validated export metadata."""
    return value[1:] if isinstance(value, str) and value.startswith("'") else value


def notes_path(path):
    return Path(str(path) + '.notes.json')


def validate_export_metadata(data, marker):
    if marker is None:
        return None
    if (not isinstance(marker, dict) or type(marker.get('version')) is not int or marker.get('version') != 1
            or marker.get('policy') != POLICY or marker.get('delimiter') != ','
            or marker.get('headers_escaped') is not True):
        raise ValueError('Unsupported CSV safety metadata')
    headers, columns = marker.get('headers'), marker.get('text_columns')
    if (not isinstance(headers, list) or not headers or not all(isinstance(h, str) for h in headers)
            or len(headers) != len(set(headers)) or not isinstance(columns, list)
            or not all(isinstance(c, str) for c in columns)
            or len(columns) != len(set(columns)) or not set(columns).issubset(headers)):
        raise ValueError('Invalid CSV safety schema or text columns')
    if marker.get('sha256') != hashlib.sha256(data).hexdigest():
        raise ValueError('CSV safety metadata does not match the file checksum')
    for role in ('name_column', 'smiles_column'):
        if marker.get(role) is not None and marker[role] not in headers:
            raise ValueError('Invalid CSV import column role')
    if marker.get('name_column') is not None and marker.get('name_column') == marker.get('smiles_column'):
        raise ValueError('CSV name and SMILES roles must differ')
    try:
        actual = next(csv.reader(io.StringIO(data.decode('utf-8-sig'), newline=''), strict=True))
    except (StopIteration, UnicodeError, csv.Error) as error:
        raise ValueError('Invalid marked CSV header') from error
    if actual != [escape_cell(h) for h in headers]:
        raise ValueError('CSV safety metadata does not match the header schema')
    return marker


def load_export_metadata(path, data=None):
    path = Path(path)
    sidecar = notes_path(path)
    if not sidecar.exists():
        return None
    try:
        document = json.loads(sidecar.read_text(encoding='utf-8'))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError('Cannot read CSV notes metadata') from error
    if not isinstance(document, dict) or 'csv_safety' not in document:
        return None
    return validate_export_metadata(path.read_bytes() if data is None else data, document['csv_safety'])


def write_csv(path, headers, rows, *, text_columns=None, notes=None, bom=False):
    """Write safe CSV and a sidecar; original records stay in JSON/provenance."""
    from src.core.calculation_cache import atomic_json, atomic_write
    path = Path(path)
    headers = list(headers)
    columns = list(headers if text_columns is None else text_columns)
    if (not headers or len(set(headers)) != len(headers)
            or not all(isinstance(h, str) for h in headers)
            or not all(isinstance(c, str) for c in columns)
            or not set(columns).issubset(headers) or len(columns) != len(set(columns))):
        raise ValueError('Invalid CSV export schema')
    stream = io.StringIO(newline='')
    writer = csv.writer(stream)
    writer.writerow([escape_cell(h) for h in headers])
    for row in rows:
        values = [row.get(h, '') for h in headers] if isinstance(row, dict) else list(row)
        if len(values) != len(headers):
            raise ValueError('CSV row length does not match header schema')
        if any(isinstance(v, str) and h not in columns and escape_cell(v) != v
               for h,v in zip(headers,values)):
            raise ValueError('Formula-like text is not a numeric CSV value')
        writer.writerow([escape_cell(v) if h in columns else v for h,v in zip(headers,values)])
    data = stream.getvalue().encode('utf-8-sig' if bom else 'utf-8')
    marker = dict(version=1, policy=POLICY, sha256=hashlib.sha256(data).hexdigest(),
                  headers=headers, text_columns=columns, headers_escaped=True, delimiter=',',
                  name_column='name' if 'name' in headers else None,
                  smiles_column='smiles' if 'smiles' in headers else None)
    document = dict(notes or {})
    document['csv_safety'] = marker
    atomic_write(path, data)
    atomic_json(notes_path(path), document)
    return document

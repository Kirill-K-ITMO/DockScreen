"""One CSV schema for preparation, menus, reports."""
import csv
import io
import json
from collections import Counter
from pathlib import Path

SMILES_ALIASES = {'smiles', 'canonical_smiles', 'isomeric_smiles', 'canonicalsmiles', 'isomericsmiles'}
NAME_ALIASES = {'name', 'название', 'compound_id', 'compoundid', 'molecule_id', 'id', 'cid', 'title'}

def csv_options(root, path=None, data=None):
    """Project-wide import settings shared by CLI, menus and preparation."""
    settings_path = Path(root) / 'settings/ligand_import.json'
    if not settings_path.exists(): settings_path = Path(root) / 'data/ligand_import.json'
    options = json.loads(settings_path.read_text(encoding='utf-8-sig')) if settings_path.exists() else {}
    allowed = {'smiles_column', 'name_column', 'naming', 'name_prefix', 'delimiter'}
    if not isinstance(options, dict) or set(options) - allowed:
        raise ValueError('ligand_import.json must contain only CSV import settings: ' + ', '.join(sorted(allowed)))
    if path is not None:
        from src.reporting.csv_safety import load_export_metadata
        marker = load_export_metadata(path, data)
        if marker is not None:
            # App-generated tables carry their own schema; explicit CLI options
            # can still override these defaults without changing project settings.
            options.update(naming='preserve', delimiter=',')
            for role in ('name_column', 'smiles_column'):
                if marker.get(role) is not None: options[role]=marker[role]
        options['export_metadata']=marker
    return options

def _column(fields, explicit, aliases, role, required=False):
    if explicit is not None:
        if explicit not in fields:
            raise ValueError(f'CSV {role} column {explicit!r} not found; available columns: {fields}')
        return explicit
    matches = [f for f in fields if f.casefold() in aliases]
    if len(matches) > 1:
        raise ValueError(f'Ambiguous CSV {role} columns: {matches}; choose an explicit column')
    if not matches and required:
        raise ValueError(f'CSV requires a smiles column; choose an explicit mapping from {fields}')
    return matches[0] if matches else None

def read_ligand_table(path, **options):
    from src.reporting.csv_safety import load_export_metadata
    data = Path(path).read_bytes()
    if 'export_metadata' not in options:
        options['export_metadata'] = load_export_metadata(path, data)
    return read_ligand_table_bytes(data, **options)

def read_ligand_table_bytes(data, *, smiles_column=None, name_column=None,
                            naming='preserve', name_prefix='ligand', delimiter=None, export_metadata=None):
    """Parse the same immutable bytes that are retained as run provenance."""
    from src.reporting.csv_safety import validate_export_metadata, decode_cell
    export_metadata = validate_export_metadata(data, export_metadata)
    if export_metadata is not None:
        if name_column is None: name_column=export_metadata.get('name_column')
        if smiles_column is None: smiles_column=export_metadata.get('smiles_column')
    with io.StringIO(data.decode("utf-8-sig"), newline="") as stream:
        if naming not in ('preserve', 'row', 'column-row'):
            raise ValueError('naming must be preserve, row or column-row')
        if not isinstance(name_prefix, str) or not name_prefix.strip():
            raise ValueError('name_prefix must be nonempty text')
        separators = {'comma': ',', 'semicolon': ';', 'tab': '\t', ',': ',', ';': ';', '\t': '\t'}
        if delimiter is not None and delimiter not in separators:
            raise ValueError('delimiter must be comma, semicolon or tab')
        if export_metadata is not None:
            if delimiter is not None and separators[delimiter] != ',':
                raise ValueError('Marked CSV exports require a comma delimiter')
            delimiter = ','
        sample=stream.read(8192);stream.seek(0)
        if delimiter is None:
            try:dialect=csv.Sniffer().sniff(sample,delimiters=",;\t")
            except csv.Error:dialect=csv.excel
            reader=csv.DictReader(stream,dialect=dialect,strict=True)
        else:
            reader=csv.DictReader(stream,delimiter=separators[delimiter],strict=True)
        if not reader.fieldnames:raise ValueError("Empty CSV")
        fields=([decode_cell(f) for f in reader.fieldnames] if export_metadata is not None
                else [f.strip() for f in reader.fieldnames])
        if len(fields)!=len(set(fields)):raise ValueError("Duplicate CSV columns")
        reader.fieldnames=fields
        smiles_field = _column(fields, smiles_column, SMILES_ALIASES, 'smiles', required=True)
        name_field = _column(fields, name_column, NAME_ALIASES, 'name') if naming != 'row' or name_column is not None else None
        if smiles_field == name_field:
            raise ValueError('SMILES and name columns must differ')
        rows=[]
        for i,row in enumerate(reader,1):
            if None in row:raise ValueError(f"Extra columns on CSV row {i+1}")
            if export_metadata is not None:
                for column in export_metadata['text_columns']:
                    row[column] = decode_cell(row.get(column))
            value=(row.get(name_field) or '') if name_field else ''
            if export_metadata is None: value=value.strip()
            name = (f'{name_prefix}_{i:06d}' if naming == 'row' or not value
                    else f'{value}_{i:06d}' if naming == 'column-row' else value)
            smiles = (row.get(smiles_field) or '')
            if export_metadata is None: smiles=smiles.strip()
            if name_field and name_field != 'name': row.pop(name_field, None)
            if smiles_field != 'smiles': row.pop(smiles_field, None)
            row["name"] = name
            row["smiles"] = smiles
            rows.append(row)
        fields = ['name', 'smiles'] + [f for f in fields if f not in {name_field, smiles_field, 'name', 'smiles'}]
        return fields, rows

def read_ligand_rows(path, **options):
    _, rows = read_ligand_table(path, **options)
    return [(row["name"], row["smiles"]) for row in rows]

def read_ligand_rows_bytes(data, **options):
    _, rows = read_ligand_table_bytes(data, **options)
    return [(row["name"], row["smiles"]) for row in rows]

def unambiguous_rows(rows):
    counts=Counter(name.casefold() for name,smiles in rows)
    return [(name,smiles) for name,smiles in rows if name and smiles and counts[name.casefold()]==1]

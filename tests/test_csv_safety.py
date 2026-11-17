"""Spreadsheet-safe text exports retain their original values for marked imports."""
import csv
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


def hit_export(folder, names):
    from src.reporting.hits import export_hits
    data = {f"row{i}": {"R@site": {"affinity": -9.0, "input_name": name,
        "smiles": "CCO", "selection_row_id": i, "target_id": "R@site",
        "spec": {"options": {"scoring": "vina"}}}}
        for i, name in enumerate(names, 1)}
    original = json.loads(json.dumps(data))
    exported = export_hits(data, folder)["R@site"]
    assert data == original
    return Path(exported["csv"]), Path(exported["notes"])


@pytest.mark.parametrize("name", ["=1+1", "+SUM(1,2)", "-formula", "@SUM(A1)",
                                  " \t=1+1", "\t\r@SUM(A1)", "\x01=1+1", "\x7f@SUM(A1)", "'original", "''two",
                                  'quoted "name", text'])
def test_hits_safe_cells_roundtrip_without_changing_numeric_score(tmp_path, name):
    from src.preparation.inputs import read_ligand_rows
    path, notes = hit_export(tmp_path, [name])
    with path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        rows = list(reader)
        assert reader.fieldnames == ["name", "smiles", "dG", "Ki"]
    significant = name
    while significant and (significant[0].isspace() or ord(significant[0]) < 32 or ord(significant[0]) == 127):
        significant = significant[1:]
    dangerous = name.startswith("'") or significant.startswith(("=", "+", "-", "@"))
    assert rows[0]["name"] == ("'" + name if dangerous else name)
    assert float(rows[0]["dG"]) == -9.0 and not rows[0]["dG"].startswith("'")
    assert 0 < float(rows[0]["Ki"]) <= 1
    assert read_ligand_rows(path) == [(name, "CCO")]
    assert notes.is_file()


def test_exported_duplicate_names_remain_duplicate_rows(tmp_path):
    from src.preparation.inputs import read_ligand_rows
    path, _ = hit_export(tmp_path, ["=same", "=same", "'same"])
    assert read_ligand_rows(path) == [("=same", "CCO"), ("=same", "CCO"), ("'same", "CCO")]


@pytest.mark.parametrize("name", ["'=1+1", "'ordinary", "''two", "=1+1"])
def test_unmarked_input_is_never_automatically_dequoted(tmp_path, name):
    from src.preparation.inputs import read_ligand_rows
    path = tmp_path / "raw.csv"
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["name", "smiles"])
        writer.writerow([name, "CCO"])
    assert read_ligand_rows(path) == [(name, "CCO")]


def test_modified_csv_invalidates_decode_permission(tmp_path):
    from src.preparation.inputs import read_ligand_rows
    path, _ = hit_export(tmp_path, ["=1+1"])
    path.write_bytes(path.read_bytes() + b"\n")
    # A known marked export with a broken hash must fail explicitly.
    with pytest.raises(ValueError):
        rows = read_ligand_rows(path)


@pytest.mark.parametrize("value", ["=1+1", "+1", "-1", "@name", " \t=1+1", "\x01+1", "'text", "''text", "text", "", -9.0, 0, None])
def test_cell_helpers_are_reversible_and_keep_numeric_values(value):
    from src.reporting.csv_safety import escape_cell, decode_cell
    encoded = escape_cell(value)
    assert decode_cell(encoded) == value
    if not isinstance(value, str):
        assert encoded == value
        assert type(encoded) is type(value)


def test_verified_metadata_bytes_loader_and_column_whitelist(tmp_path):
    from src.reporting.csv_safety import write_csv, load_export_metadata, validate_export_metadata
    from src.preparation.inputs import read_ligand_rows_bytes
    path = tmp_path / "table.csv"
    write_csv(path, ["name", "smiles", "dG"], [[" \t=1+1", "CCO", -9.0]],
              text_columns=["name", "smiles"], notes={"kind": "test", "temperature_K": 298.15})
    data = path.read_bytes()
    sidecar = json.loads(Path(str(path) + ".notes.json").read_text(encoding="utf-8"))
    assert sidecar["kind"] == "test" and sidecar["temperature_K"] == 298.15
    assert sidecar["csv_safety"]["sha256"] == hashlib.sha256(data).hexdigest()
    assert sidecar["csv_safety"]["policy"] == "apostrophe-v1"
    assert sidecar["csv_safety"]["version"] == 1
    assert sidecar["csv_safety"]["headers"] == ["name", "smiles", "dG"]
    assert set(sidecar["csv_safety"]["text_columns"]) == {"name", "smiles"}
    marker = load_export_metadata(path, data=data)
    assert validate_export_metadata(data, marker) is not None
    assert read_ligand_rows_bytes(data, export_metadata=marker) == [(" \t=1+1", "CCO")]
    assert read_ligand_rows_bytes(data) == [("' \t=1+1", "CCO")]


@pytest.mark.parametrize("field,value", [
    ("policy", "unknown-policy"), ("version", 99), ("sha256", "0" * 64),
    ("headers", ["not-the-actual-header", "smiles"]),
    ("text_columns", ["name", "smiles", "not-a-column"]),
    ("headers_escaped", False), ("delimiter", ";"),
])
def test_tampered_marker_refuses_automatic_dequoting(tmp_path, field, value):
    from src.preparation.inputs import read_ligand_rows
    path, _ = hit_export(tmp_path, ["=1+1"])
    note_path = Path(str(path) + ".notes.json")
    note = json.loads(note_path.read_text(encoding="utf-8"))
    note["csv_safety"][field] = value
    note_path.write_text(json.dumps(note), encoding="utf-8")
    with pytest.raises(ValueError):
        read_ligand_rows(path)


def test_legacy_notes_without_marker_do_not_authorize_decode(tmp_path):
    from src.reporting.csv_safety import load_export_metadata
    from src.preparation.inputs import read_ligand_rows
    path = tmp_path / "legacy.csv"
    path.write_text("name,smiles\n'=1+1,CCO\n", encoding="utf-8")
    Path(str(path) + ".notes.json").write_text('{"kind":"legacy"}', encoding="utf-8")
    assert load_export_metadata(path) is None
    assert read_ligand_rows(path) == [("'=1+1", "CCO")]


def test_unsafe_header_roundtrips_with_explicit_column_mapping(tmp_path):
    from src.reporting.csv_safety import write_csv
    from src.preparation.inputs import read_ligand_rows
    path = tmp_path / "headers.csv"
    write_csv(path, ["=Compound", "SMILES"], [["'original", "CCO"]], text_columns=["=Compound", "SMILES"])
    with path.open(encoding="utf-8", newline="") as stream:
        assert next(csv.reader(stream)) == ["'=Compound", "SMILES"]
    assert read_ligand_rows(path, name_column="=Compound", smiles_column="SMILES") == [("'original", "CCO")]


def test_screening_keeps_original_json_and_snapshot_while_exporting_safe_csv(tmp_path):
    """Real ligand preparation, mocked docking: no engine or affinity validation."""
    from src.preparation.inputs import read_ligand_rows_bytes, read_ligand_rows
    from src.screening import run_screen
    original = b"name,smiles\n=1+1,CCO\n"
    source = tmp_path / "original.csv"
    source.write_bytes(original)
    rows = read_ligand_rows_bytes(original)
    docker = SimpleNamespace(run_docking=lambda **kwargs: {"row_000001": {"R": {"affinity": -9.0}}},
        _save_results_json=lambda: None, seed=42, timeout=1, vina_version="Mock adapter",
        stats={}, last_batch_dir=None, cpu_pool=SimpleNamespace(snapshot=lambda: {}))
    report = run_screen(tmp_path, rows, ["R"], docker, html=False, input_csv=source, input_csv_bytes=original)
    run = Path(report["run_dir"])
    assert source.read_bytes() == (run / "input.csv").read_bytes() == original
    assert report["input_csv_sha256"] == hashlib.sha256(original).hexdigest()
    results = json.loads((run / "results.json").read_text(encoding="utf-8"))
    prepared = json.loads((run / "preparation.json").read_text(encoding="utf-8"))
    assert results["row_000001"]["R"]["input_name"] == prepared[0]["name"] == "=1+1"
    with (run / "scores.csv").open(encoding="utf-8", newline="") as stream:
        record = next(csv.DictReader(stream))
    assert record["name"] == "'=1+1" and float(record["affinity_kcal_mol"]) == -9
    assert read_ligand_rows(run / "scores.csv", name_column="name") == [("=1+1", "CCO")]


def test_marked_hits_snapshot_and_result_zip_keep_import_metadata(tmp_path):
    import zipfile
    from src.reporting.csv_safety import write_csv
    from src.preparation.inputs import read_ligand_rows
    from src.screening import run_screen
    from src.core.project import ProjectUtils
    source = tmp_path/'hits.csv'
    write_csv(source, ['name','smiles','dG','Ki'], [[" \t=1+1",'CCO',-9,0.25]],
              text_columns=['name','smiles'])
    rows = read_ligand_rows(source)
    docker = SimpleNamespace(run_docking=lambda **kwargs: {'row_000001': {'R': {'affinity':-9}}},
        _save_results_json=lambda: None, seed=42, timeout=1, vina_version='Mock adapter',
        stats={}, last_batch_dir=None, cpu_pool=SimpleNamespace(snapshot=lambda: {}))
    report = run_screen(tmp_path, rows, ['R'], docker, html=False, input_csv=source)
    run = Path(report['run_dir'])
    assert read_ligand_rows(run/'input.csv') == rows
    assert report['csv_import_options']['export_metadata']['policy'] == 'apostrophe-v1'
    archive = ProjectUtils(tmp_path).export_results_to_zip(tmp_path/'result.zip',run_dir=run)
    with zipfile.ZipFile(archive) as z:
        assert 'run/input.csv.notes.json' in z.namelist()
        assert 'run/scores.csv.notes.json' in z.namelist()
        assert z.read('run/input.csv') == source.read_bytes()


def test_wide_report_protects_text_headers_and_keeps_scores_numeric(tmp_path):
    from src.reporting.docking import ReportGenerator
    from src.docking.affinity import AffinityCalculator
    from src.preparation.inputs import read_ligand_rows
    data = AffinityCalculator().process_docking_results({'row':{'=1+1':{
        'affinity':-9.0,'smiles':'CCO','input_name':'@name'}}})
    path = ReportGenerator(tmp_path).generate_csv_report(data,smiles_dict={'row':'CCO'})
    with path.open(encoding='utf-8',newline='') as stream:
        reader = csv.DictReader(stream)
        row = next(reader)
        assert "'=1+1_delta_g" in reader.fieldnames
    assert row['name'] == "'@name" and row["'=1+1_delta_g"] == '-9.0'
    assert read_ligand_rows(path) == [('@name','CCO')]


def test_formula_text_cannot_be_smuggled_into_numeric_column(tmp_path):
    from src.reporting.csv_safety import write_csv
    path = tmp_path/'numeric.csv'
    with pytest.raises(ValueError, match='numeric CSV'):
        write_csv(path,['name','dG'],[['sample','=1+1']],text_columns=['name'])
    assert not path.exists()


def test_marked_scores_choose_original_label_despite_molecule_id_column(tmp_path):
    from src.reporting.csv_safety import write_csv
    from src.preparation.inputs import read_ligand_rows
    path=tmp_path/'scores.csv'
    write_csv(path,['name','smiles','molecule_id'],[['=original','CCO','chemical-id']])
    assert read_ligand_rows(path) == [('=original','CCO')]
    assert read_ligand_rows(path,name_column='molecule_id') == [('chemical-id','CCO')]


def test_marked_export_schema_overrides_project_defaults_without_mutation(tmp_path):
    from src.reporting.csv_safety import write_csv
    from src.preparation.inputs import csv_options, read_ligand_rows, read_ligand_rows_bytes
    (tmp_path/'data').mkdir()
    settings=tmp_path/'data/ligand_import.json'
    original=json.dumps({'name_column':'CompoundCode','smiles_column':'Structure',
        'delimiter':'semicolon','naming':'column-row'}).encode('utf-8')
    settings.write_bytes(original)
    path=tmp_path/'hits.csv'
    write_csv(path,['name','smiles'],[['=original','CCO']])
    options=csv_options(tmp_path,path,path.read_bytes())
    assert read_ligand_rows_bytes(path.read_bytes(),**options) == [('=original','CCO')]
    assert read_ligand_rows(path,**csv_options(tmp_path,path)) == [('=original','CCO')]
    raw=tmp_path/'raw.csv'
    raw.write_text('CompoundCode;Structure\nexample;CCO\n',encoding='utf-8')
    assert read_ligand_rows(raw,**csv_options(tmp_path,raw)) == [('example_000001','CCO')]
    assert settings.read_bytes() == original

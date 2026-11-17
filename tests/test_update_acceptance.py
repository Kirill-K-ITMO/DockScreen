"""Independent acceptance checks for the 0.2 update.

Mocked tests cover control flow only. The real-Vina timeout test separately
observes that its actual child process has exited.
"""
from pathlib import Path
import csv
import json
import shutil
import subprocess
import zipfile
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_explicit_csv_mapping_is_case_sensitive_and_preserves_source(tmp_path):
    from src.preparation.inputs import read_ligand_rows_bytes
    source = "Code;SMI;smiles\nобразец;CCO;CCN\n".encode("utf-8-sig")
    original = bytes(source)
    assert read_ligand_rows_bytes(source, smiles_column="SMI", name_column="Code", delimiter=";") == [("образец", "CCO")]
    assert source == original
    with pytest.raises(ValueError):
        read_ligand_rows_bytes(source, smiles_column="smi", name_column="Code", delimiter=";")


def test_ambiguous_smiles_alias_requires_mapping():
    from src.preparation.inputs import read_ligand_rows_bytes
    source = b"name,smiles,SMILES\na,CCO,CCN\n"
    with pytest.raises(ValueError):
        read_ligand_rows_bytes(source)
    assert read_ligand_rows_bytes(source, smiles_column="SMILES") == [("a", "CCN")]


@pytest.mark.parametrize("mode", ["row", "column-row"])
def test_generated_names_remain_distinct_with_duplicate_input_names(mode):
    from src.preparation.inputs import read_ligand_rows_bytes
    source = b"ID,Structure\nsame,CCO\nsame,CCN\n,CCC\n"
    rows = read_ligand_rows_bytes(source, smiles_column="Structure", name_column="ID", naming=mode, name_prefix="sample")
    assert len(rows) == 3 and len({name for name, _ in rows}) == 3
    assert all(name.strip() for name, _ in rows)
    assert [smiles for _, smiles in rows] == ["CCO", "CCN", "CCC"]
    assert [name for name, _ in rows] == (
        ["sample_000001", "sample_000002", "sample_000003"] if mode == "row"
        else ["same_000001", "same_000002", "sample_000003"]
    )


def test_mapping_options_read_from_project_and_path_parser_agrees(tmp_path):
    from src.preparation.inputs import read_ligand_rows, read_ligand_rows_bytes, csv_options
    root = tmp_path / "проект с пробелами"
    (root / "data").mkdir(parents=True)
    options = {"smiles_column": "Structure", "name_column": "Code", "naming": "preserve", "delimiter": ";"}
    (root / "data/ligand_import.json").write_text(json.dumps(options), encoding="utf-8")
    source = "Code;Structure\nодин;CCO\n".encode("utf-8-sig")
    path = root / "data/молекулы.csv"
    path.write_bytes(source)
    loaded = csv_options(root)
    assert read_ligand_rows(path, **loaded) == read_ligand_rows_bytes(source, **loaded) == [("один", "CCO")]


def test_cli_documents_csv_selection_switches():
    import sys
    result = subprocess.run([sys.executable, str(ROOT / "main.py"), "--help"], capture_output=True, text=True, check=True)
    for flag in ("--smiles-column", "--name-column", "--name-mode", "--name-prefix", "--delimiter"):
        assert flag in result.stdout


def test_targets_preserve_legacy_and_resolve_profiles_without_copying_receptor(tmp_path):
    from src.docking.targets import get_targets, resolve_target
    root = tmp_path / "profiles"
    (root / "data/proteins").mkdir(parents=True)
    (root / "data/configs/R").mkdir(parents=True)
    receptor = root / "data/proteins/R.pdbqt"
    receptor.write_bytes(b"receptor bytes unchanged")
    (root / "data/configs/R.txt").write_text("legacy", encoding="utf-8")
    (root / "data/configs/R/first.txt").write_text("first", encoding="utf-8")
    (root / "data/configs/R/second.conf").write_text("second", encoding="utf-8")
    targets = get_targets(root)
    assert {target["id"] for target in targets} == {"R", "R@first", "R@second"}
    assert resolve_target(root, "R")["config_path"] == root / "data/configs/R.txt"
    assert resolve_target(root, "R@first")["config_path"] == root / "data/configs/R/first.txt"
    assert all(target["receptor_path"] == receptor for target in targets)
    assert receptor.read_bytes() == b"receptor bytes unchanged"
    with pytest.raises(FileNotFoundError):
        resolve_target(root, "R@absent")


@pytest.mark.parametrize("target_id", ["../R", "R@../first", "R@", "R@@first", "R@CON", "R/first", "R@first."])
def test_target_ids_reject_ambiguous_or_unsafe_components(tmp_path, target_id):
    from src.docking.targets import resolve_target
    with pytest.raises(ValueError):
        resolve_target(tmp_path, target_id)


def test_duplicate_configuration_extensions_are_rejected(tmp_path):
    from src.docking.targets import resolve_target
    (tmp_path / "data/proteins").mkdir(parents=True)
    (tmp_path / "data/configs/R").mkdir(parents=True)
    (tmp_path / "data/proteins/R.pdbqt").write_bytes(b"unchanged")
    for extension in ("txt", "conf"):
        (tmp_path / f"data/configs/R/first.{extension}").write_text("box", encoding="utf-8")
    with pytest.raises(ValueError, match="[Aa]mbiguous"):
        resolve_target(tmp_path, "R@first")


def test_single_run_zip_excludes_other_runs_and_technical_files(tmp_path):
    from src.core.project import ProjectUtils
    root = tmp_path / "экспорт проекта"
    for run_name in ("screening-first", "screening-second"):
        run = root / "output/runs" / run_name
        run.mkdir(parents=True)
        (run / "results.json").write_text("{}", encoding="utf-8")
        (run / "summary.json").write_text("{}", encoding="utf-8")
        (run / "scores.csv").write_text("name,status\na,success\n", encoding="utf-8")
    for relative in (".calculation_cache/v1/cache.sqlite3", "output/experiments.db", "output/cache/latest.json", "output/prepared/unrelated.pdbqt", "output/inputs/unrelated.pdbqt", "output/tmp/junk.txt"):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"excluded technical or unrelated bytes")
    selected = root / "output/runs/screening-first"
    output = root / "результаты.zip"
    ProjectUtils(root).export_results_to_zip(output_file=output, run_dir=selected)
    with zipfile.ZipFile(output) as archive:
        names = archive.namelist()
        assert any(name.endswith("scores.csv") for name in names)
        assert not any("screening-second" in name for name in names)
        assert not any("cache" in name or "tmp/" in name or name.endswith(".db") or name.endswith(".sqlite3") or "unrelated" in name for name in names)
        assert archive.testzip() is None
    with pytest.raises(ValueError):
        ProjectUtils(root).export_results_to_zip(output_file=root / "bad.zip", run_dir=tmp_path)
    impostor = root / "data/not-a-run"
    impostor.mkdir(parents=True)
    (impostor / "results.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError):
        ProjectUtils(root).export_results_to_zip(output_file=root / "bad-inside.zip", run_dir=impostor)


def test_hits_keep_two_profiles_of_one_receptor_independent(tmp_path):
    from src.reporting.hits import export_hits
    results = {"same_ligand": {
        "R@first": {"affinity": -9.0, "input_name": "одна молекула", "smiles": "CCO", "target_id": "R@first", "spec": {"options": {"scoring": "vina"}}},
        "R@second": {"affinity": -7.0, "input_name": "одна молекула", "smiles": "CCO", "target_id": "R@second", "spec": {"options": {"scoring": "vinardo"}}},
    }}
    exports = export_hits(results, tmp_path)
    assert exports["R@first"]["count"] == 1
    assert exports["R@second"]["count"] == 0
    assert exports["R@first"]["csv"] != exports["R@second"]["csv"]
    notes = {target: json.loads(Path(data["notes"]).read_text(encoding="utf-8")) for target, data in exports.items()}
    assert notes["R@first"]["scoring"] == "vina"
    assert notes["R@second"]["scoring"] == "vinardo"


def test_real_vina_timeout_child_exits_and_cpu_releases(tmp_path):
    """Real process termination, not a mock of subprocess.run or the engine."""
    from src.docking.vina import AutoDockVina
    from src.preparation.ligands import LigandConverter
    from src.screening import run_screen
    vina = ROOT / "tools/vina.exe"
    if not vina.is_file():
        pytest.skip("Real Windows Vina not available in this source checkout")
    root = tmp_path / "реальный timeout"
    proteins = root / "data/proteins"
    configs = root / "data/configs"
    proteins.mkdir(parents=True)
    configs.mkdir(parents=True)
    receptor = proteins / "JAK1_3EYG.pdbqt"
    config = configs / "JAK1_3EYG.txt"
    shutil.copyfile(ROOT / "data/proteins/JAK1_3EYG.pdbqt", receptor)
    shutil.copyfile(ROOT / "data/configs/JAK1_3EYG.txt", config)
    ligand = Path(LigandConverter(root).prepare_cached("CCO")["path"])
    docker = AutoDockVina(root, vina_executable=vina, timeout=0.001, cpu_budget=1)
    original_popen = subprocess.Popen
    children = []

    def observe_real_child(*args, **kwargs):
        child = original_popen(*args, **kwargs)
        children.append(child)
        return child

    with patch("src.docking.vina.subprocess.Popen", observe_real_child):
        report = run_screen(root, [("probe", "CCO")], ["JAK1_3EYG"], docker, exhaustiveness=10000, workers=1, html=False)
    assert children and all(child.poll() is not None for child in children)
    assert report["successful_pairs"] == 0 and report["failed_pairs"] == 1
    with (Path(report["run_dir"]) / "scores.csv").open(encoding="utf-8", newline="") as stream:
        scores = list(csv.DictReader(stream))
    assert len(scores) == 1 and scores[0]["status"] == "timeout"
    assert scores[0]["affinity_kcal_mol"] == ""
    assert docker.cpu_pool.active == docker.cpu_pool.waiting == 0
    assert "docking" not in docker.calculation_cache.statistics()
    assert docker.task_outcomes["row_000001"]["JAK1_3EYG"]["status"] == "timeout"


def test_real_cli_custom_csv_profile_and_timeout_exit_code(tmp_path):
    """Technical CLI integration using installed real Vina, no score benchmark."""
    import sys
    vina = ROOT / "tools/vina.exe"
    if not vina.is_file():
        pytest.skip("Real Windows Vina not available in this source checkout")
    root = tmp_path / "CLI профиль с пробелами"
    (root / "data/proteins").mkdir(parents=True)
    (root / "data/configs/R").mkdir(parents=True)
    shutil.copyfile(ROOT / "data/proteins/JAK1_3EYG.pdbqt", root / "data/proteins/R.pdbqt")
    shutil.copyfile(ROOT / "data/configs/JAK1_3EYG.txt", root / "data/configs/R/one.txt")
    source = "Compound\tSMI\nобразец\tCCO\n".encode("utf-8-sig")
    (root / "data/custom.tsv").write_bytes(source)
    command = [sys.executable, str(ROOT / "main.py"), "--run", "--project", str(root),
               "--vina", str(vina), "--targets", "R@one", "--ligands", "data/custom.tsv",
               "--smiles-column", "SMI", "--name-column", "Compound", "--delimiter", "tab",
               "--name-mode", "column-row", "--name-prefix", "input", "--timeout", "0.001",
               "--exhaustiveness", "10000", "--cpu-budget", "1", "--no-html"]
    result = subprocess.run(command, capture_output=True, text=True, timeout=45)
    assert result.returncode == 2, result.stdout + result.stderr
    runs = list((root / "output/runs").glob("screening-*"))
    assert len(runs) == 1
    assert (runs[0] / "input.csv").read_bytes() == source
    with (runs[0] / "scores.csv").open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 1 and rows[0]["name"] == "образец_000001"
    assert rows[0]["receptor"] == "R" and rows[0]["target_id"] == "R@one"
    assert rows[0]["config_id"] == "one" and rows[0]["status"] == "timeout"
    assert rows[0]["affinity_kcal_mol"] == ""

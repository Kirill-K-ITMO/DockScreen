"""Windows/path regressions; mocked engine cases are not real docking."""
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

import pytest

from src.preparation.inputs import read_ligand_rows


@pytest.mark.parametrize("separator", [",", ";", "\t"])
def test_unicode_space_csv_preserves_duplicate_labels(tmp_path, separator):
    folder = tmp_path / "проект с пробелами"
    folder.mkdir()
    table = folder / "молекулы вход.csv"
    table.write_text(
        f"name{separator}smiles\nодинаково{separator}CCO\nодинаково{separator}CCN\n",
        encoding="utf-8-sig",
    )
    assert read_ligand_rows(table) == [("одинаково", "CCO"), ("одинаково", "CCN")]


@pytest.mark.parametrize("text", ["name,name,smiles\na,b,CCO\n", "name,smiles\na,CCO,extra\n", "name\na\n"])
def test_malformed_csv_is_rejected(tmp_path, text):
    table = tmp_path / "некорректный файл.csv"
    table.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError):
        read_ligand_rows(table)


def test_real_preparation_unicode_path_and_cache(tmp_path):
    """Real RDKit/Meeko preparation, without a docking engine."""
    from src.preparation.ligands import LigandConverter
    from src.core.calculation_cache import validate_pdbqt
    converter = LigandConverter(tmp_path / "подготовка с пробелами")
    first = converter.prepare_cached("CCO")
    second = converter.prepare_cached("OCC")
    assert not first["cache_hit"] and second["cache_hit"]
    assert first["preparation_id"] == second["preparation_id"]
    validate_pdbqt(Path(second["path"]).read_bytes())


@pytest.mark.parametrize("failure", ["timeout", "empty", "missing", "no_score"])
def test_engine_failure_is_not_cached_and_releases_cpu(tmp_path, failure):
    """Exercise adapter failure handling with subprocess mocked, not Vina."""
    from src.docking.vina import AutoDockVina
    from src.preparation.ligands import LigandConverter
    root = tmp_path / "докинг с пробелами"
    ligand = Path(LigandConverter(root).prepare_cached("CCO")["path"])
    # Reusing the fixture bytes as a receptor only exercises adapter control flow.
    receptor = root / "рецептор тест.pdbqt"
    receptor.write_bytes(ligand.read_bytes())
    config = root / "box.txt"
    config.write_text("center_x=0\ncenter_y=0\ncenter_z=0\nsize_x=10\nsize_y=10\nsize_z=10\n")

    def probe(engine):
        engine.vina_executable = sys.executable
        engine.vina_version = "MOCK adapter test; not Vina"

    with patch.object(AutoDockVina, "_check_vina", probe):
        engine = AutoDockVina(root, cpu_budget=1, timeout=0.25)

    def fake_run(command, **kwargs):
        assert isinstance(command, list) and kwargs["timeout"] == 0.25
        if failure == "timeout":
            raise subprocess.TimeoutExpired(command, kwargs["timeout"])
        pose = Path(command[command.index("--out") + 1])
        if failure == "empty":
            pose.write_bytes(b"")
        elif failure == "no_score":
            pose.write_bytes(ligand.read_bytes())
        return subprocess.CompletedProcess(command, 0, "", "")

    with patch("src.docking.vina.subprocess.run", fake_run):
        assert engine.run_single_docking(ligand, receptor, config) is None
        assert engine.run_single_docking(ligand, receptor, config) is None
    assert engine.stats["failed"] == engine.stats["executed"] == 2
    assert engine.cpu_pool.active == engine.cpu_pool.waiting == 0
    assert "docking" not in engine.calculation_cache.statistics()


def test_keyboard_interrupt_does_not_commit_cache(tmp_path):
    """A local cache transaction test; not an OS process-cancellation test."""
    from src.core.calculation_cache import CalculationCache
    cache = CalculationCache(tmp_path / "кэш с пробелами")

    def interrupted():
        raise KeyboardInterrupt()

    with pytest.raises(KeyboardInterrupt):
        cache.get_or_compute("test", {}, interrupted)
    assert cache.get("test", {}) is None
    assert not cache.get_or_compute("test", {}, lambda: ({}, b"retry")).hit

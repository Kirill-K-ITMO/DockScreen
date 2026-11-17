"""Provenance/export regressions with real preparation and a mocked docker."""
import csv
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.preparation.inputs import read_ligand_rows_bytes
from src.screening import run_screen


@pytest.mark.parametrize('change', ['replace', 'delete'])
def test_snapshot_survives_source_change_and_csv_names_scoring(tmp_path, change):
    source = tmp_path / 'вход с пробелами.csv'
    original = 'name,smiles\nимя,CCO\n'.encode('utf-8-sig')
    source.write_bytes(original)
    rows = read_ligand_rows_bytes(original)

    def docking(**kwargs):
        if change == 'delete':
            source.unlink()
        else:
            source.write_bytes(b'name,smiles\nchanged,CCN\n')
        return {'row_000001': {'A': {'affinity': -1.5,
            'evaluation_id': 'mock-evaluation', 'spec': {'options': {'scoring': 'vinardo'}}}}}

    docker = SimpleNamespace(run_docking=docking, _save_results_json=lambda: None,
        seed=42, timeout=1, vina_version='MOCK, not real docking',
        stats={}, last_batch_dir=None, cpu_pool=SimpleNamespace(snapshot=lambda: {}))
    summary = run_screen(tmp_path, rows, ['A'], docker, html=False,
        input_csv=source, input_csv_bytes=original)
    run = Path(summary['run_dir'])
    assert (run / 'input.csv').read_bytes() == original
    assert summary['input_csv_sha256'] == hashlib.sha256(original).hexdigest()
    with (run / 'scores.csv').open(encoding='utf-8', newline='') as stream:
        row = next(csv.DictReader(stream))
    assert row['name'] == 'имя'
    assert row['scoring'] == 'vinardo'
    assert row['score_units'] == 'kcal/mol'
    assert row['ranking_direction'] == 'lower_is_better'
    assert row['evaluation_id'] == 'mock-evaluation'
    assert row['preparation_id']
    assert row['molecule_id']
    assert json.loads((run / 'preparation.json').read_text(encoding='utf-8'))[0]['status'] == 'prepared'


def test_mismatched_snapshot_rejected_before_calculation(tmp_path):
    with pytest.raises(ValueError, match='snapshot does not match'):
        run_screen(tmp_path, [('old', 'CCO')], ['A'], None,
            input_csv_bytes=b'name,smiles\nnew,CCN\n')
    assert not (tmp_path / 'output').exists()

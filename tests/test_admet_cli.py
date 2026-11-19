"""CLI acceptance: missing optional environment is a retained partial result."""
import json
import sys

import main


def test_missing_environment_does_not_start_docking_then_report_regenerates(tmp_path, monkeypatch, capsys):
    run = tmp_path / 'output/runs/screening-cli'
    run.mkdir(parents=True)
    prep = [{'row_id': 1, 'label': 'row_000001', 'name': '=dangerous-name',
             'smiles': 'CCO', 'status': 'prepared'}]
    for name, value in [('preparation.json', prep), ('results.json', {}),
                        ('summary.json', {'receptors': ['R']})]:
        (run / name).write_text(json.dumps(value), encoding='utf-8')
    original = {p.name: p.read_bytes() for p in run.iterdir()}
    from src.docking.vina import AutoDockVina
    def unexpected_docking(*args, **kwargs):
        raise AssertionError('Postprocessing must never instantiate Vina')
    monkeypatch.setattr(AutoDockVina, '__init__', unexpected_docking)
    monkeypatch.setattr(sys, 'argv', ['main.py', '--project', str(tmp_path), '--admet-run',
                                    str(run), '--admet-python', str(tmp_path / 'absent/python.exe')])
    assert main.main() == 2
    output = capsys.readouterr().out
    assert 'ADMET Python is unavailable' in output
    assert 'Docking files are retained' in output
    assert all((run / name).read_bytes() == data for name, data in original.items())
    assert (run / 'combined_report.html').is_file()
    admet = json.loads((run / 'admet.json').read_text(encoding='utf-8'))
    assert admet['rows'][0]['status'] == 'prediction_failed'
    assert admet['rows'][0]['values'] == {}
    monkeypatch.setattr(sys, 'argv', ['main.py', '--project', str(tmp_path),
                                    '--combined-report', str(run)])
    assert main.main() == 0
    assert 'Interactive report:' in capsys.readouterr().out

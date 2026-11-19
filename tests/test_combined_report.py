import json
import hashlib
import re
import shutil
import subprocess

from src.reporting.combined import build_combined_data, generate_combined_report, REPORT_JS


def write(run, name, value):
    (run / name).write_text(json.dumps(value), encoding='utf-8')


def fixture_run(tmp_path):
    run = tmp_path / 'run'
    run.mkdir()
    rows = [dict(row_id=i, label=f'row_{i:06d}', name='=1+1</script><script>alert(1)</script>', smiles='CCO', status='prepared') for i in range(1, 4)]
    write(run, 'preparation.json', rows)
    write(run, 'summary.json', {'receptors': ['A@site', 'B']})
    write(run, 'results.json', {'row_000001': {'A@site': {'affinity': -5, 'spec': {'ligand_sha': 'a', 'options': {'scoring': 'vina', 'seed': 42}}}},
                                'row_000002': {'A@site': {'affinity': -6, 'spec': {'ligand_sha': 'b', 'options': {'scoring': 'vina', 'seed': 42}}}},
                                'row_000003': {'A@site': {'affinity': -8, 'spec': {'ligand_sha': 'c', 'options': {'scoring': 'vinardo', 'seed': 42}}}}})
    return run


def test_preserve_duplicates_protocol_isolation_and_missing(tmp_path):
    run = fixture_run(tmp_path)
    data = build_combined_data(tmp_path, run)
    assert len(data['rows']) == 3
    assert len(data['protocols']) == 3  # vina, vinardo, no-success target B
    one, two, three = data['rows']
    assert one['docking']['A@site']['protocol'] == two['docking']['A@site']['protocol']
    assert one['docking']['A@site']['protocol'] != three['docking']['A@site']['protocol']
    assert one['admet_status'] == 'not_run'
    assert one['docking']['B']['score'] is None
    assert one['image'].startswith('data:image/svg+xml;base64,')


def test_admet_join_by_row_id_not_name_and_json_script_safety(tmp_path):
    run = fixture_run(tmp_path)
    hashes = {name: hashlib.sha256((run / name).read_bytes()).hexdigest() for name in ('preparation.json', 'results.json', 'summary.json')}
    original = json.loads((run / 'preparation.json').read_text())[1]
    write(run, 'admet.json', {'metadata': {'version': 'test', 'input_sha256': hashes}, 'endpoints': {'DILI': {'type': 'classification', 'units': 'score'}},
                            'rows': [{'row_id': 2, 'name': original['name'], 'smiles': original['smiles'], 'status': 'success', 'values': {'DILI': .4}}]})
    data = build_combined_data(tmp_path, run)
    assert 'DILI' not in data['rows'][0]['values']
    assert data['rows'][1]['values']['DILI'] == .4
    path = generate_combined_report(tmp_path, run)
    html = path.read_text(encoding='utf-8')
    assert '</script><script>alert(1)</script>' not in html
    embedded = re.search(r'<script id="report-data" type="application/json">(.*?)</script>', html, re.S).group(1)
    assert json.loads(embedded)['rows'][0]['name'] == data['rows'][0]['name']
    assert 'https://' not in html
    assert 'http://' not in html.replace('http://www.w3.org/2000/svg', '')
    assert 'uncertainty' not in data or data['uncertainty'] is None


def test_stale_admet_hashes_and_structure_join_rejected(tmp_path):
    import pytest
    run = fixture_run(tmp_path)
    hashes = {name: hashlib.sha256((run / name).read_bytes()).hexdigest() for name in ('preparation.json', 'results.json', 'summary.json')}
    original = json.loads((run / 'preparation.json').read_text())[0]
    document = {'metadata': {'input_sha256': hashes}, 'rows': [{'row_id': 1, 'name': original['name'], 'smiles': 'CCN', 'values': {'DILI': .4}}]}
    write(run, 'admet.json', document)
    with pytest.raises(ValueError, match='identity/SMILES'):
        build_combined_data(tmp_path, run)
    document['rows'][0]['smiles'] = original['smiles']
    document['metadata']['input_sha256']['results.json'] = 'stale'
    write(run, 'admet.json', document)
    with pytest.raises(ValueError, match='provenance mismatch'):
        build_combined_data(tmp_path, run)


def test_generated_browser_javascript_syntax(tmp_path):
    node = shutil.which('node')
    if node:
        path = tmp_path / 'report.js'
        path.write_text(REPORT_JS, encoding='utf-8')
        subprocess.run([node, '--check', str(path)], check=True, capture_output=True)

"""Independent saved-analysis HTML/document acceptance; synthetic fixed properties."""
import csv
import hashlib
from html.parser import HTMLParser
import io
import json
from pathlib import Path
import re
import sys
import zipfile

import pytest

from src.reporting.pareto_csv import HEADERS
from src.reporting.csv_safety import load_export_metadata, write_csv


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


class Tags(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.tags = []
        self.feed(html)
    def handle_starttag(self, tag, attrs): self.tags.append(tag)


@pytest.fixture
def analysis_input(tmp_path):
    run = tmp_path / 'output/runs/screening-documents'
    run.mkdir(parents=True)
    malicious = '</script><script>alert(1)</script><img src=x onerror=alert(2)>'
    preparation = [{'row_id': n, 'label': f'row_{n}', 'name': malicious if n == 1 else 'duplicate',
                    'smiles': 'CCO', 'status': 'prepared'} for n in range(1, 5)]
    results = {row['label']: {'R': {'affinity': score, 'spec': {'options': {'scoring': 'vina'}}}}
               for row, score in zip(preparation, [-9., -8., -8., -6.])}
    for name, value in [('preparation.json', preparation), ('results.json', results), ('summary.json', {'receptors': ['R']})]:
        (run / name).write_text(json.dumps(value), encoding='utf-8')
    admet = {'metadata': {'version': 'SYNTHETIC-document-test', 'input_sha256': {
        n: hashlib.sha256((run / n).read_bytes()).hexdigest()
        for n in ['preparation.json', 'results.json', 'summary.json']}},
        'endpoints': {'DILI': {'type': 'classification', 'units': '-'}},
        'rows': [{**{k: row[k] for k in ['row_id', 'name', 'smiles']}, 'status': 'success',
                  'values': {'DILI': v}} for row, v in zip(preparation, [.2, .2, .2, .8])]}
    (run / 'admet.json').write_text(json.dumps(admet), encoding='utf-8')
    text = io.StringIO(newline='')
    writer = csv.writer(text, delimiter=';')
    writer.writerow(HEADERS)
    writer.writerow(['docking_score', 'сравнивать', 'минимум', '', '-7', '', '', ''])
    writer.writerow(['DILI', 'сравнивать', 'минимум', '', '.5', '', '', ''])
    criteria = tmp_path / 'criteria.csv'
    criteria.write_bytes(text.getvalue().encode('utf-8-sig'))
    settings = tmp_path / 'scales.json'
    from src.analysis.smaa_workflow import create_smaa_template
    create_smaa_template(tmp_path, run, criteria, settings, target='R')
    config = load(settings)
    config['sampling'].update(iterations=65, seed=42, top_n=2)
    settings.write_text(json.dumps(config), encoding='utf-8')
    return tmp_path, run, criteria, settings


def test_smaa_only_and_combined_html_keep_identical_numbers_ties_and_immutable_sources(analysis_input):
    from src.analysis.smaa_workflow import run_smaa
    root, run, criteria, settings = analysis_input
    before = {p: p.read_bytes() for p in [run / n for n in
              ['preparation.json', 'results.json', 'summary.json', 'admet.json']] + [criteria, settings]}
    combined = run_smaa(root, run, criteria, settings, target='R', include_pareto=True)
    standalone = run_smaa(root, run, criteria, settings, target='R', include_pareto=False)
    assert combined['directory'] != standalone['directory']
    a = load(Path(combined['directory']) / 'results.json')
    b = load(Path(standalone['directory']) / 'results.json')
    assert a['rows'] == b['rows']
    assert [r['smaa']['expected_rank'] if r['smaa'] else None for r in a['rows']] == [1., 2.5, 2.5, None]
    assert [r['smaa']['top_n_acceptability'] if r['smaa'] else None for r in a['rows']] == [1., .5, .5, None]
    for result in [combined, standalone]:
        folder = Path(result['directory'])
        html = Path(result['report_html'])
        assert html.is_file() and html.resolve().is_relative_to(folder.resolve())
        content = html.read_text(encoding='utf-8')
        assert '<script' not in content.lower()
        assert '<img src=x' not in content.lower()
        assert '&lt;script&gt;' in content
        assert not {'script', 'iframe', 'input', 'select'} & set(Tags(content).tags)
        assert result['documents']
        assert all((folder / name).is_file() for name in result['documents'].values())
    combined_html = Path(combined['report_html']).read_text(encoding='utf-8')
    standalone_html = Path(standalone['report_html']).read_text(encoding='utf-8')
    assert '<th>Статус Парето</th>' in combined_html
    assert '<th>Статус Парето</th>' not in standalone_html
    assert all(path.read_bytes() == content for path, content in before.items())


def test_pareto_only_returns_named_readable_html_without_smaa(analysis_input):
    from src.reporting.pareto_csv import run_pareto
    root, run, criteria, _ = analysis_input
    result = run_pareto(root, run, criteria, target='R')
    folder = Path(result['directory'])
    assert Path(result['report_html']).is_file()
    assert result['documents']
    assert not (run / 'smaa').exists()
    assert result['total'] == 4 and result['feasible'] == 3 and result['front'] == 1
    assert (folder / 'criteria.csv').read_bytes() == criteria.read_bytes()


def test_empty_feasible_smaa_html_is_complete_and_does_not_invent_a_winner(analysis_input):
    from src.analysis.smaa_workflow import create_smaa_template, run_smaa
    root, run, criteria, settings = analysis_input
    criteria.write_bytes(criteria.read_bytes().replace(b'-7', b'-100'))
    replacement = root / 'empty-scales.json'
    create_smaa_template(root, run, criteria, replacement, target='R')
    result = run_smaa(root, run, criteria, replacement, target='R', include_pareto=False)
    doc = load(Path(result['directory']) / 'results.json')
    assert result['feasible'] == result['effective_top_n'] == 0
    assert doc['configuration']['completed_scenarios'] == 0
    assert all(r['smaa'] is None and r['exclusion_reasons'] for r in doc['rows'])
    html = Path(result['report_html']).read_text(encoding='utf-8')
    assert 'SMAA' in html
    assert 'пуст' in html.lower() or 'нет допустим' in html.lower()


def test_result_zip_keeps_nested_named_html_csv_and_document_index(analysis_input):
    from src.analysis.smaa_workflow import run_smaa
    from src.core.project import ProjectUtils
    root, run, criteria, settings = analysis_input
    result = run_smaa(root, run, criteria, settings, target='R', include_pareto=True)
    folder = Path(result['directory'])
    archive = ProjectUtils(root).export_results_to_zip(root / 'documents.zip', run_dir=run,
                                                      include_docking_pdbqt=False)
    with zipfile.ZipFile(archive) as z:
        assert z.testzip() is None
        prefix = 'run/smaa/' + folder.name + '/'
        for name in result['documents'].values():
            assert z.read(prefix + name) == (folder / name).read_bytes()
        assert any(n.startswith(prefix) and n.endswith('INDEX.json') for n in z.namelist())
        manifest = json.loads(z.read('MANIFEST.json'))
        assert all(hashlib.sha256(z.read(name)).hexdigest() == metadata['sha256']
                   for name, metadata in manifest['files'].items())


def test_publication_utc_windows_safe_names_csv_sidecar_and_unchanged_snapshots(tmp_path):
    from src.reporting.document_names import publish_documents
    folder = tmp_path / 'analysis'
    folder.mkdir()
    write_csv(folder / 'candidates.csv', ['id', 'name', 'score'],
              [{'id': '1', 'name': '=1+1', 'score': -8.}], text_columns=['id', 'name'], bom=True)
    (folder / 'results.json').write_bytes(b'{"raw_name":"=1+1","score":-8.0}\n')
    (folder / 'report.html').write_text('<!doctype html><a href="candidates.csv">CSV</a><a href="results.json">JSON</a>', encoding='utf-8')
    protected = {p.name: p.read_bytes() for p in folder.iterdir()}
    identity = 'analysis-0123456789abcdef'
    mapping = publish_documents(folder, kind='SMAA', target='CON: JAK/..\\bad?*<>"',
                                identity=identity, created_utc='2026-11-19T03:00:00+03:00',
                                filenames=['report.html', 'candidates.csv', 'results.json'])
    assert set(mapping) == {'report.html', 'candidates.csv', 'candidates.csv.notes.json', 'results.json'}
    for relative in mapping.values():
        path = Path(relative)
        assert path.parent == Path('documents')
        assert '2026-11-19_00-00-00Z' in path.name
        assert hashlib.sha256(identity.encode('utf-8')).hexdigest()[:8] in path.name
        assert not re.search(r'[<>:"/\\|?*\x00-\x1f]', path.name)
        assert not path.name.endswith((' ', '.'))
        assert (folder / path).is_file()
    alias_csv = folder / mapping['candidates.csv']
    assert (folder / mapping['candidates.csv.notes.json']) == Path(str(alias_csv) + '.notes.json')
    assert alias_csv.read_bytes() == protected['candidates.csv']
    assert load_export_metadata(alias_csv)['sha256'] == hashlib.sha256(alias_csv.read_bytes()).hexdigest()
    assert (folder / mapping['results.json']).read_bytes() == protected['results.json']
    html = (folder / mapping['report.html']).read_text(encoding='utf-8')
    assert 'href="candidates.csv"' not in html
    assert Path(mapping['candidates.csv']).name in html
    assert (folder / 'documents/INDEX.json').is_file()
    assert all((folder / name).read_bytes() == value for name, value in protected.items())


def test_repeated_publication_refuses_overwrite_without_changing_any_documents(tmp_path):
    from src.reporting.document_names import publish_documents
    (tmp_path / 'report.html').write_text('<html>fixed</html>', encoding='utf-8')
    options = dict(kind='SMAA', target='R', identity='same', created_utc='2026-11-19T00:00:00Z',
                   filenames=['report.html'])
    publish_documents(tmp_path, **options)
    before = {p.relative_to(tmp_path).as_posix(): p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    with pytest.raises((ValueError, FileExistsError)):
        publish_documents(tmp_path, **options)
    after = {p.relative_to(tmp_path).as_posix(): p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    assert before == after


def test_publication_rejects_windows_case_insensitive_filename_collision(tmp_path):
    from src.reporting.document_names import publish_documents
    # These are distinct files on Linux and one path on usual Windows volumes.
    # Either platform must reject the ambiguous pair before publishing anything.
    (tmp_path / 'report.html').write_text('<html>lowercase</html>', encoding='utf-8')
    (tmp_path / 'REPORT.HTML').write_text('<html>uppercase</html>', encoding='utf-8')
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    with pytest.raises(ValueError, match='collid|collision|[Dd]uplicate|повтор|совпад'):
        publish_documents(tmp_path, kind='SMAA', target='R', identity='a',
                          created_utc='2026-11-19T00:00:00Z', filenames=['report.html', 'REPORT.HTML'])
    assert not (tmp_path / 'documents').exists()
    assert all((tmp_path / name).read_bytes() == content for name, content in before.items())


@pytest.mark.parametrize('name', ['../secret.json', '/absolute.json', 'nested/report.html', 'C:\\secret.json'])
def test_publication_rejects_nonbasename_sources_without_creating_documents(tmp_path, name):
    from src.reporting.document_names import publish_documents
    (tmp_path / 'report.html').write_text('<html>fixed</html>', encoding='utf-8')
    with pytest.raises(ValueError):
        publish_documents(tmp_path, kind='SMAA', target='R', identity='a',
                          created_utc='2026-11-19T00:00:00Z', filenames=[name])
    assert not (tmp_path / 'documents').exists()


def test_publication_requires_timezone_instead_of_guessing_local_time(tmp_path):
    from src.reporting.document_names import publish_documents
    (tmp_path / 'report.html').write_text('<html>fixed</html>', encoding='utf-8')
    with pytest.raises(ValueError):
        publish_documents(tmp_path, kind='SMAA', target='R', identity='a',
                          created_utc='2026-11-19T00:00:00', filenames=['report.html'])
    assert not (tmp_path / 'documents').exists()


def test_cli_smaa_only_creates_html_from_saved_values_without_docking_or_admet(analysis_input, monkeypatch):
    import main
    import src.ui.streams as streams
    import src.admet.pipeline as pipeline
    import src.docking.vina as vina
    root, run, criteria, settings = analysis_input
    monkeypatch.setattr(streams, 'configure_streams', lambda: None)
    def prohibited(*args, **kwargs): raise AssertionError('saved-result reporting must never calculate docking/ADMET')
    monkeypatch.setattr(pipeline, '_invoke', prohibited)
    monkeypatch.setattr(vina.AutoDockVina, 'run_docking', prohibited)
    monkeypatch.setattr(sys, 'argv', ['main.py', '--project', str(root), '--smaa-run', str(run),
                                     '--pareto-criteria', str(criteria), '--smaa-settings', str(settings),
                                     '--pareto-target', 'R', '--smaa-only'])
    assert main.main() == 0
    folders = list((run / 'smaa').glob('analysis-*'))
    assert len(folders) == 1
    reports = list((folders[0] / 'documents').glob('*.html'))
    assert len(reports) == 1
    assert 'SMAA' in reports[0].name.upper()
    assert all(r['smaa'] is not None for r in load(folders[0] / 'results.json')['rows'][:3])


def test_html_failure_never_publishes_successful_analysis(analysis_input, monkeypatch):
    import src.analysis.smaa_workflow as workflow
    root, run, criteria, settings = analysis_input
    before = {p:p.read_bytes() for p in run.iterdir() if p.is_file()}
    def broken(*args, **kwargs):
        raise RuntimeError('synthetic HTML failure')
    monkeypatch.setattr(workflow, 'render_smaa_html', broken)
    with pytest.raises(RuntimeError, match='HTML failure'):
        workflow.run_smaa(root, run, criteria, settings, target='R')
    assert not list((run/'smaa').glob('analysis-*'))
    stages=list((run/'smaa').glob('.incomplete-*'))
    assert stages and all(load(p/'status.json')['status']=='failed' for p in stages)
    assert all(p.read_bytes()==data for p,data in before.items())

"""Interface and packaging checks. Actual docking is checked separately with Vina."""
import importlib
import io
from pathlib import Path
import subprocess
import sys
import pytest
from src.version import APP_NAME,__version__
from src.preparation.inputs import read_ligand_rows
from src.ui.docking_menu import parse_selection

ROOT=Path(__file__).resolve().parents[1]

def test_launcher_and_verification_help():
    for script in ['main.py','verify_screening.py']:
        result=subprocess.run([sys.executable,str(ROOT/script),'--help'],capture_output=True,text=True)
        assert result.returncode==0,result.stderr
    result=subprocess.run([sys.executable,str(ROOT/'main.py'),'--version'],capture_output=True,text=True)
    assert result.stdout.strip()==f'{APP_NAME} {__version__}'

def test_check_without_dependencies_explains_problem(tmp_path):
    result=subprocess.run([sys.executable,'-S',str(ROOT/'main.py'),'--check','--project',str(tmp_path)],capture_output=True,text=True)
    assert result.returncode==1
    assert 'requirements.txt' in result.stdout
    assert 'Traceback' not in result.stderr


def test_all_remaining_modules_import():
    for path in (ROOT/'src').rglob('*.py'):
        if path.name=='__init__.py': continue
        importlib.import_module('.'.join(path.relative_to(ROOT).with_suffix('').parts))

def test_menu_without_vina(tmp_path,monkeypatch):
    from rich.console import Console
    from src.ui import application
    output=io.StringIO()
    monkeypatch.setattr(application,'console',Console(file=output,color_system=None))
    app=application.DockScreenApp(tmp_path)
    try:
        app.show_menu()
        assert 'Docking' in output.getvalue()
        assert 'Evolution' not in output.getvalue()
        assert app._docker is None
    finally: app.close()

@pytest.mark.parametrize('text,expected',[('all',[0,1,2]),('3,1,3',[2,0])])
def test_selection(text,expected):
    assert parse_selection(text,3)==expected

def test_duplicate_names_retained_in_csv(tmp_path):
    path=tmp_path/'input.csv'
    path.write_text('name,smiles\nsame,CCO\nsame,CCN\n')
    assert read_ligand_rows(path)==[('same','CCO'),('same','CCN')]

def test_receptor_provenance_hashes():
    import hashlib,json
    sources=json.loads((ROOT/'data/receptor_sources.json').read_text())
    for record in sources:
        for item in record['files']:
            assert hashlib.sha256((ROOT/'data'/item['path']).read_bytes()).hexdigest()==item['sha256']

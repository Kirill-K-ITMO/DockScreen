from pathlib import Path
import pytest
from src.preparation.ligands import LigandConverter

@pytest.fixture
def project(tmp_path):
    converter=LigandConverter(tmp_path)
    prepared=converter.prepare_cached('CCO')
    return tmp_path,converter,Path(prepared['path'])

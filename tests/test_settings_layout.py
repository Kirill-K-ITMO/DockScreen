import json
from pathlib import Path
import pytest


def test_settings_preferred_and_legacy_import_still_reads(tmp_path):
    from src.core.app_settings import vina_path
    from src.core.cpu_budget import project_budget
    from src.preparation.inputs import csv_options
    (tmp_path/'settings').mkdir()
    (tmp_path/'app_settings.json').write_text(json.dumps({'vina_executable':'old-vina'}))
    (tmp_path/'settings/app_settings.json').write_text(json.dumps({'vina_executable':'new-vina'}))
    assert 'new-vina' in vina_path(tmp_path)
    (tmp_path/'settings/cpu_settings.json').write_text(json.dumps({'cpu_budget':1,'cpu_per_job':1}))
    assert project_budget(tmp_path).total == 1
    (tmp_path/'settings/ligand_import.json').write_text(json.dumps({'smiles_column':'CUSTOM'}))
    assert csv_options(tmp_path)['smiles_column'] == 'CUSTOM'


def test_relocated_receptors_are_selected_and_legacy_not_mixed(tmp_path):
    from src.docking.targets import get_targets
    (tmp_path/'data/proteins').mkdir(parents=True)
    (tmp_path/'settings/receptors/R').mkdir(parents=True)
    (tmp_path/'data/proteins/R.pdbqt').write_text('fixture')
    (tmp_path/'settings/receptors/R/site.txt').write_text('center_x=0')
    targets = get_targets(tmp_path)
    assert [x['id'] for x in targets] == ['R@site']
    assert targets[0]['config_path'] == tmp_path/'settings/receptors/R/site.txt'


def test_unified_dependencies_keep_incompatible_rdkit_separate():
    import scripts.install as installer
    groups=installer.dependency_groups()
    assert 'rdkit==2026.3.6' in groups['docking']
    assert 'rdkit==2026.9.2' in groups['admet']
    assert not any('admet-ai' in x for x in groups['docking'])


def test_settings_directory_is_protected_from_zip_output(tmp_path):
    from src.core.project import ProjectUtils
    (tmp_path/'settings').mkdir()
    with pytest.raises(ValueError, match='protected'):
        ProjectUtils(tmp_path).export_results_to_zip(tmp_path/'settings/bad.zip')

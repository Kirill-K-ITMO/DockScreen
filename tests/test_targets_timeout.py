"""Target selection and mocked-engine outcomes, not scientific validation."""
import json
from pathlib import Path
import subprocess
import sys

import pytest

from src.docking.targets import get_targets, resolve_target, split_target
from src.docking.vina import AutoDockVina, validate_timeout

BOX = 'center_x=0\ncenter_y=0\ncenter_z=0\nsize_x=10\nsize_y=10\nsize_z=10\n'


def layout(root):
    (root / 'data/proteins').mkdir(parents=True, exist_ok=True)
    (root / 'data/configs/R').mkdir(parents=True, exist_ok=True)
    (root / 'data/proteins/R.pdbqt').write_bytes(b'target discovery fixture')
    (root / 'data/configs/R.txt').write_text(BOX)
    (root / 'data/configs/R/first.conf').write_text(BOX + 'exhaustiveness=3\n')
    (root / 'data/configs/R/second.config').write_text(BOX + 'exhaustiveness=5\n')


def test_targets_preserve_legacy_and_resolve_profiles(tmp_path):
    layout(tmp_path)
    targets = get_targets(tmp_path)
    assert [target['id'] for target in targets] == ['R', 'R@first', 'R@second']
    assert targets[0]['config_id'] == 'default'
    assert resolve_target(tmp_path, 'R@first')['receptor_path'] == targets[0]['receptor_path']
    (tmp_path / 'data/configs/R/first.txt').write_text(BOX)
    with pytest.raises(ValueError, match='Ambiguous'):
        get_targets(tmp_path)


@pytest.mark.parametrize('target', ['../R', 'R@../x', 'R@@x', 'R@', '@x', 'R@CON',
                                    'R@a:b', 'R@x.', 'R@x ', 'R@x\\y', 'R@a?'])
def test_unsafe_ids_rejected(target):
    with pytest.raises(ValueError):
        split_target(target)


@pytest.mark.parametrize('timeout', [0, -1, float('nan'), float('inf'), True, '1', None])
def test_invalid_timeout_rejected(timeout):
    with pytest.raises(ValueError, match='timeout'):
        validate_timeout(timeout)


def engine(root, monkeypatch):
    def probe(docker):
        docker.vina_executable = sys.executable
        docker.vina_version = 'MOCK, not Vina'
    monkeypatch.setattr(AutoDockVina, '_check_vina', probe)
    return AutoDockVina(root, cpu_budget=2, timeout=.1)


def test_config_exhaustiveness_none_and_explicit_override(tmp_path, monkeypatch):
    layout(tmp_path)
    docker = engine(tmp_path, monkeypatch)
    first = docker.get_config('R@first')
    assert docker._effective_options(first, None)['exhaustiveness'] == '3'
    assert docker._effective_options(first, 8)['exhaustiveness'] == '8'
    assert docker._effective_options(docker.get_config('R'), None)['exhaustiveness'] == '8'


def test_timeout_independent_success_provenance_cache_and_reset(project, monkeypatch):
    root, _, ligand = project
    layout(root)
    (root / 'data/proteins/R.pdbqt').write_bytes(ligand.read_bytes())
    docker = engine(root, monkeypatch)
    calls = []

    def fake_run(command, **kwargs):
        effort = command[command.index('--exhaustiveness') + 1]
        calls.append(effort)
        if effort == '5':
            raise subprocess.TimeoutExpired(command, kwargs['timeout'])
        pose = Path(command[command.index('--out') + 1])
        pose.write_bytes(b'REMARK VINA RESULT: -2.5 0 0\n' + ligand.read_bytes())
        return subprocess.CompletedProcess(command, 0, 'mock', '')

    monkeypatch.setattr('src.docking.vina.subprocess.run', fake_run)
    result = docker.run_docking(proteins=['R@first', 'R@second'], ligand_paths={'L': ligand},
                                exhaustiveness=None, num_workers=2)
    assert list(result['L']) == ['R@first']
    good = result['L']['R@first']
    assert (good['receptor'], good['config_id'], good['target_id']) == ('R', 'first', 'R@first')
    assert Path(good['input_files']['config']).read_bytes() == (root / 'data/configs/R/first.conf').read_bytes()
    assert good['config_sha256'] == good['spec']['config_sha']
    assert docker.task_outcomes['L']['R@second']['status'] == 'timeout'
    assert 'affinity' not in docker.task_outcomes['L']['R@second']
    assert docker.cpu_pool.active == docker.cpu_pool.waiting == 0
    assert docker.calculation_cache.statistics()['docking']['entries'] == 1
    saved = json.loads((docker.last_batch_dir / 'task_outcomes.json').read_text())
    assert saved['L']['R@second']['status'] == 'timeout'
    again = docker.run_docking(proteins=['R@first'], ligand_paths={'L': ligand}, exhaustiveness=None)
    assert again['L']['R@first']['cache_hit']
    assert list(docker.task_outcomes['L']) == ['R@first']
    assert sorted(calls) == ['3', '5']

"""Verification must use release settings without changing the source example."""
from pathlib import Path

import pytest

from verify_screening import _copy_verification_inputs


@pytest.mark.parametrize('legacy', [False, True])
def test_verification_copies_current_or_legacy_layout_to_isolated_project(tmp_path, legacy):
    project = tmp_path/'source'
    data = project/'data'
    (data/'proteins').mkdir(parents=True)
    receptor = data/'proteins/R.pdbqt'
    receptor.write_bytes(b'fixture receptor bytes')
    config = data/'configs' if legacy else project/'settings/receptors'
    config.mkdir(parents=True)
    box = config/'R.txt'
    box.write_bytes(b'center_x = 1\n')
    if not legacy:
        (data/'configs').mkdir()
        (data/'configs/R.txt').write_bytes(b'wrong old config')
    target = tmp_path/'isolated'
    _copy_verification_inputs(data, target)
    assert (target/'data/proteins/R.pdbqt').read_bytes() == receptor.read_bytes()
    assert (target/'settings/receptors/R.txt').read_bytes() == box.read_bytes()
    assert box.read_bytes() == b'center_x = 1\n'
    assert not (target/'data/configs').exists()


def test_verification_explains_missing_configs_without_touching_source(tmp_path):
    data = tmp_path/'source/data'
    data.mkdir(parents=True)
    with pytest.raises(ValueError, match='settings/receptors'):
        _copy_verification_inputs(data, tmp_path/'isolated')
    assert not (tmp_path/'isolated').exists()

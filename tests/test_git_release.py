"""Release bytes survive a real local Git index/checkout without any commit."""
from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.parametrize("relative", ["src/sample.py", "docs/sample.md", "examples/sample.sh"])
def test_release_text_bytes_are_canonical_lf(tmp_path, monkeypatch, relative):
    import scripts.source_release as release
    monkeypatch.setattr(release, "ROOT", tmp_path)
    path = tmp_path / relative
    path.parent.mkdir(parents=True)
    path.write_bytes(b"first\r\nsecond\nthird\r\n")
    original = path.read_bytes()
    assert release.source_bytes(path) == b"first\nsecond\nthird\n"
    assert path.read_bytes() == original


@pytest.mark.parametrize("relative", ["data/ligands.csv", "data/proteins/R.pdbqt", "data/configs/R.txt",
                                      "data/README.md", "licenses/sample/LICENSE.md"])
def test_release_preserves_scientific_input_bytes(tmp_path, monkeypatch, relative):
    import scripts.source_release as release
    monkeypatch.setattr(release, "ROOT", tmp_path)
    path = tmp_path / relative
    path.parent.mkdir(parents=True)
    original = b"scientific bytes\r\nline two\n"
    path.write_bytes(original)
    assert release.source_bytes(path) == original
    assert path.read_bytes() == original


def test_manifest_stable_after_real_git_add_and_checkout_without_commit(tmp_path, monkeypatch):
    import scripts.source_release as release
    executable = shutil.which("git")
    if executable is None:
        pytest.skip("Local Git executable unavailable")
    monkeypatch.setattr(release, "ROOT", tmp_path)
    fixtures = {
        ".gitattributes": b"* -text\n*.py text eol=lf\n*.md text eol=lf\n*.sh text eol=lf\n",
        "src/sample.py": b"print('example')\r\n# second line\r\n",
        "docs/sample.md": b"# Example\r\n\r\nText\r\n",
        "examples/sample.sh": b"#!/bin/sh\r\ntrue\r\n",
        "data/ligands.csv": b"name,smiles\r\nexample,CCO\r\n",
        "data/proteins/R.pdbqt": b"EXACT SCIENTIFIC INPUT\r\n",
        "data/configs/R.txt": b"seed=42\r\n",
    }
    paths = []
    for name, content in fixtures.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        paths.append(path)
    monkeypatch.setattr(release, "source_paths", lambda: paths)
    before = release.inventory()

    def git(*arguments, check=True):
        return subprocess.run([executable, "-c", "core.autocrlf=true", *arguments],
                              cwd=tmp_path, capture_output=True, text=True, check=check, timeout=15)

    git("init", "--quiet")
    git("add", "--", *fixtures)
    for path in paths:
        if path.name != ".gitattributes":
            path.unlink()
    git("checkout-index", "--all", "--force")
    assert git("rev-parse", "--verify", "HEAD", check=False).returncode != 0
    assert release.inventory() == before
    for name, original in fixtures.items():
        actual = (tmp_path / name).read_bytes()
        if Path(name).suffix in {".py", ".md", ".sh"}:
            assert actual == original.replace(b"\r\n", b"\n")
        else:
            assert actual == original

"""Build a public source release from reviewed files, without local work history."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.version import __version__
FILES = ['.gitattributes', '.gitignore', 'AUTHORS.md', 'CITATION.cff',
         'LICENSE', 'README.md', 'README_RU.md', 'CHANGELOG.md', 'THIRD_PARTY_NOTICES.md',
         'main.py', 'pyproject.toml', 'INSTALL.cmd', 'START.cmd', 'CHECK.cmd', 'verify_screening.py',
         '.github/workflows/tests.yml',
         'examples/slurm_screening.sh',
         'examples/windows/INSTALL.cmd', 'examples/windows/START.cmd', 'examples/windows/CHECK.cmd']
DOCUMENTS = ['affinity_estimates.md', 'admet.md', 'pareto_csv.md', 'smaa.md', 'csv_analysis.md',
             'references.md', 'test_data.md', 'licensing.md', 'dependency_inventory.json',
             'example_checksums.json']
ASSETS = ['admet-panel-preview.gif', 'dockscreen-logo.svg', 'dockscreen-logo.png', 'dockscreen-icon.svg', 'dockscreen-console.txt']
DATA = ['ligands.csv', 'ligand_sources.csv', 'receptor_sources.json',
        'proteins/JAK1_3EYG.pdbqt', 'proteins/JAK2_6BBV.pdbqt',
        ]
LICENSE_NAMES = {'LICENSE', 'LICENSE.txt', 'LICENSE.md', 'LICENSE.markdown-it',
                 'LICENSE.APACHE', 'LICENSE.BSD', 'README.md', 'RDKit-core-license.txt',
                 'SA_Score-NOTICE.txt', 'AutoDock-Vina-LICENSE.txt', 'Boost-LICENSE_1_0.txt',
                 'OpenBabel-COPYING.txt', 'Vina-Windows-NOTICES.txt'}


def source_bytes(path):
    name = path.relative_to(ROOT).as_posix()
    if name == 'settings/app_settings.json':
        return b'{\n  "vina_executable": "vina"\n}\n'
    if name == 'settings/cpu_settings.json':
        return b'{\n  "cpu_budget": 4,\n  "cpu_per_job": 1\n}\n'
    content = path.read_bytes()
    if path.relative_to(ROOT).parts[0] not in ('data', 'licenses') and path.suffix in ('.py', '.md', '.sh'):
        content = content.replace(b'\r\n', b'\n').replace(b'\r', b'\n')
    return content


def source_paths():
    paths = [ROOT / name for name in FILES]
    paths += [ROOT / 'docs' / name for name in DOCUMENTS]
    paths += [ROOT / 'assets' / name for name in ASSETS]
    paths += [ROOT / 'data' / name for name in DATA]
    required_settings = ['app_settings.json', 'cpu_settings.json', 'PARETO_CRITERIA.csv',
                         'examples/ligand_import.json',
                         'receptors/JAK1_3EYG.txt', 'receptors/JAK2_6BBV.txt']
    paths.extend(ROOT / 'settings' / name for name in required_settings)
    for name in ('src', 'tests', 'scripts'):
        paths.extend(p for p in (ROOT / name).rglob('*.py') if p.is_file()
                     and not any(part.startswith('.') or part in ('__pycache__', 'tmp', 'temp', 'cache')
                                 for part in p.relative_to(ROOT).parts))
    paths.extend(p for p in (ROOT / 'licenses').rglob('*') if p.is_file() and p.name in LICENSE_NAMES)
    for path in paths:
        if not path.is_file():
            raise ValueError(f'Required release file is missing: {path.relative_to(ROOT)}')
        if not path.resolve().is_relative_to(ROOT.resolve()):
            raise ValueError(f'Release source escapes the project: {path.relative_to(ROOT)}')
        for part in (path, *path.parents):
            if part == ROOT:
                break
            if part.is_symlink() or part.is_junction():
                raise ValueError(f'Linked files are not allowed in releases: {path.relative_to(ROOT)}')
    expected = json.loads((ROOT / 'docs/example_checksums.json').read_text(encoding='utf-8'))
    for name, sha in expected.items():
        if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != sha:
            raise ValueError(f'Example data changed: {name}; review before publishing')
    return sorted(set(paths), key=lambda p: p.relative_to(ROOT).as_posix())


def inventory():
    return {p.relative_to(ROOT).as_posix():
            {'sha256': hashlib.sha256(source_bytes(p)).hexdigest(), 'size': len(source_bytes(p))}
            for p in source_paths()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Verify the saved source manifest')
    parser.add_argument('--output', type=Path, help='Build source ZIP after writing manifest')
    parser.add_argument('--directory', type=Path, help='Write a clean project into a NEW directory')
    args = parser.parse_args()
    if args.output is not None:
        destination = args.output.resolve()
        protected = ('data','src','tests','scripts','docs','assets','licenses','examples','tools','settings','.github','.git','.venv')
        if destination.suffix.lower() != '.zip' or any(destination.is_relative_to(ROOT/p) for p in protected):
            parser.error('Source ZIP must have a .zip suffix and be outside project source/input directories')
    files = {p.relative_to(ROOT).as_posix(): source_bytes(p) for p in source_paths()}
    records = {name: {'sha256':hashlib.sha256(content).hexdigest(), 'size':len(content)}
               for name,content in files.items()}
    manifest = {'application': 'DockScreen', 'version': __version__, 'format': 1, 'files': records}
    target = ROOT / 'MANIFEST.json'
    contents = sorted([*manifest['files'], 'MANIFEST.json', 'CONTENTS.txt'])
    contents_bytes = ('\n'.join(contents) + '\n').encode('utf-8')
    if args.check:
        if json.loads(target.read_text(encoding='utf-8')) != manifest:
            parser.exit(1, 'Manifest differs; review changes and regenerate it.\n')
        if (ROOT / 'CONTENTS.txt').read_bytes() != contents_bytes:
            parser.exit(1, 'CONTENTS.txt differs from the reviewed release layout.\n')
        print(f"Manifest verified: {len(manifest['files'])} files")
        return
    files['MANIFEST.json'] = (json.dumps(manifest, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    files['CONTENTS.txt'] = contents_bytes
    if args.directory:
        directory = args.directory.resolve()
        if directory.exists():
            parser.exit(1, 'The clean output directory must not already exist.\n')
        directory.mkdir(parents=True)
        for name, content in files.items():
            destination = directory / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(content)
        print(f'Clean project: {directory}')
    target.write_bytes(files['MANIFEST.json'])
    (ROOT / 'CONTENTS.txt').write_bytes(contents_bytes)
    if args.output:
        output = args.output.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
            for name, content in sorted(files.items()):
                archive.writestr('DockScreen/' + name, content)
        with zipfile.ZipFile(output) as archive:
            assert archive.testzip() is None
            assert set(archive.namelist()) == {'DockScreen/' + name for name in files}
            for name, content in files.items():
                assert archive.read('DockScreen/' + name) == content
        print(f'Source ZIP: {output}')
    print(f"Manifest written: {len(manifest['files'])} files")


if __name__ == '__main__':
    main()

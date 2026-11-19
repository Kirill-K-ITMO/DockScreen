"""Build a Windows source ZIP with the verified external Vina executable.

The two root READMEs are included unchanged; there is no generated third guide.
"""
import hashlib
import json
from pathlib import Path
import zipfile

from source_release import ROOT, source_paths, source_bytes, __version__

VINA_SHA256 = 'e0c4b2715e0c1a74f6e92d0f3be0328ac97542eafbc111e6b1efad897a73cce5'


def main():
    vina = (ROOT / 'tools/vina.exe').read_bytes()
    if hashlib.sha256(vina).hexdigest() != VINA_SHA256:
        raise SystemExit('Unexpected Vina binary: review provenance before bundling')
    files = {p.relative_to(ROOT).as_posix(): source_bytes(p) for p in source_paths()}
    files['tools/vina.exe'] = vina
    files['settings/app_settings.json'] = b'{\n  "vina_executable": "tools/vina.exe"\n}\n'
    for name, value in list(files.items()):
        if name.endswith('.cmd'):
            files[name] = value.replace(b'\r\n', b'\n').replace(b'\n', b'\r\n')
    files['THIRD_PARTY_NOTICES.md'] = (
        '# Windows distribution supplement\n\n'
        'This Windows-with-Vina ZIP includes AutoDock Vina 1.2.7. The historical\n'
        'source-only inventory below describes the base source distribution.\n'
        'For the bundled executable see README.md, README_RU.md,\n'
        'licenses/Vina-Windows-NOTICES.txt, licenses/AutoDock-Vina-LICENSE.txt\n'
        'and licenses/Boost-LICENSE_1_0.txt. Python runtime/packages are not bundled.\n\n'
    ).encode('utf-8') + files['THIRD_PARTY_NOTICES.md']
    manifest = {'application': 'DockScreen', 'version': __version__,
                'distribution': 'windows-with-vina', 'format': 1,
                'files': {name: {'sha256': hashlib.sha256(data).hexdigest(), 'size': len(data)}
                          for name, data in sorted(files.items())}}
    files['MANIFEST.json'] = (json.dumps(manifest, indent=2, ensure_ascii=False) + '\n').encode('utf-8')
    files['CONTENTS.txt'] = ('\n'.join(sorted([*files, 'CONTENTS.txt'])) + '\n').encode('utf-8')
    target = ROOT / f'dist/DockScreen_{__version__}-Windows-with-Vina.zip'
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(files.items()):
            archive.writestr('DockScreen/' + name, data)
    with zipfile.ZipFile(target) as archive:
        assert len(archive.namelist()) == len(files)
        for name, item in manifest['files'].items():
            assert hashlib.sha256(archive.read('DockScreen/' + name)).hexdigest() == item['sha256']
        assert archive.read('DockScreen/settings/app_settings.json') == files['settings/app_settings.json']
        assert archive.testzip() is None
    print(f'Built and verified: {target} ({target.stat().st_size} bytes)')


if __name__ == '__main__':
    main()

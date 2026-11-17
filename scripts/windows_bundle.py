"""Build a Windows source ZIP with the verified external Vina executable."""
import hashlib
import json
from pathlib import Path
import zipfile

from source_release import ROOT, source_paths, source_bytes, __version__

VINA_SHA256 = 'e0c4b2715e0c1a74f6e92d0f3be0328ac97542eafbc111e6b1efad897a73cce5'


def windows_readme():
    return f'''# DockScreen {__version__} для Windows

Подготовка лигандов из SMILES и CPU-докинг по одному или нескольким
рецепторам. AutoDock Vina 1.2.7 уже включена в tools/vina.exe и настроена.
Python и Python-библиотеки устанавливаются отдельно.

## Установка и запуск

1. Установите Python 3.12 x64 с Python Launcher, если его ещё нет.
2. Полностью распакуйте ZIP в доступную для записи локальную папку.
3. Откройте INSTALL.cmd: он создаст .venv и установит requirements.txt.
   Нужен интернет. Дождитесь сообщения Installation complete.
4. Откройте CHECK.cmd. Ожидаемый результат — Ready to run.
5. Откройте START.cmd — появится терминальное меню. Далее достаточно START.cmd.

Вручную из PowerShell в папке DockScreen:

```powershell
py -3.12 -m venv .venv
.\\.venv\\Scripts\\python.exe -m pip install -r requirements.txt
.\\.venv\\Scripts\\python.exe main.py
```

Пакетный запуск (полная входящая таблица, не только проверка):

```powershell
.\\.venv\\Scripts\\python.exe main.py --run --receptors JAK1_3EYG JAK2_6BBV --cpu-budget 2 --cpu-per-job 1 --workers 2 --timeout 600 --export-zip results.zip
```

## Входы и результаты

Лиганды: data/ligands.csv, UTF-8, столбцы name,smiles. Для других схем:
--smiles-column, --name-column, --name-mode, --delimiter; проектная настройка
data/ligand_import.json, пример — examples/ligand_import.json.
Рецепторы: data/proteins/R.pdbqt, конфиг: data/configs/R.txt. Программа не
подготавливает белки. Несколько профилей: data/configs/R/PROFILE.txt,
выбор --targets R@PROFILE. Без --exhaustiveness используется config значение
или 8; явный аргумент переопределяет его. Сайты и протоколы выбирайте явно.

Каждый batch сохраняет output/runs/screening-… с CSV/JSON, необязательным HTML
и отдельными hits CSV по конфигурациям: name,smiles,dG,Ki. Ki — оценка из
score в мкмоль/л, порог ≤1; это не экспериментальная аффинность. Сохраняйте
notes рядом с hits. Пути поз указаны в JSON. Для продолжения повторите
команду с неизменными входами и сохранённым кэшем .calculation_cache.
Несколько экземпляров в одной папке не запускайте. Все параметры: main.py --help.

Экспорт ZIP не перезаписывает исходники и существующие файлы. Для явной замены
валидного архива используется --overwrite-zip; в меню нужна отдельная команда
подтверждения. CSV защищает текст от формул электронных таблиц апострофом.
Числа не меняются; исходные имена/SMILES сохранены в JSON. Переносите CSV
вместе с *.csv.notes.json: DockScreen проверяет hash/schema/policy и восстанавливает
имена при повторном докинге. Без соответствующих notes автоснятия префикса нет.

Научное происхождение и ограничения примеров: [test_data](docs/test_data.md).
Нативная подготовка RDKit/Meeko не ограничена таймаутом Vina. Ctrl+C не
гарантирует мгновенной остановки всех workers; итоговый экспорт может
потребовать повторного запуска. На Linux нужны Linux Vina и новая среда.

## Авторство и лицензии

Автор и разработчик DockScreen — Kirill V. Karkhanin, собственный код —
[MIT](LICENSE). Комплект содержит неизменённую Vina 1.2.7, Apache-2.0;
она переименована из vina_1.2.7_win.exe. Boost — BSL-1.0.
Сохраняйте [third-party notices](THIRD_PARTY_NOTICES.md) и licenses/.
Происхождение бинарника: [официальный релиз](https://github.com/forlilab/AutoDock-Vina/releases/tag/v1.2.7).
Исходники и атрибуция: [Vina notices](licenses/Vina-Windows-NOTICES.txt).
SHA256 tools/vina.exe: `{VINA_SHA256}`.
'''.encode('utf-8')


def main():
    vina = (ROOT / 'tools/vina.exe').read_bytes()
    if hashlib.sha256(vina).hexdigest() != VINA_SHA256:
        raise SystemExit('Unexpected Vina binary: review provenance before bundling')
    files = {p.relative_to(ROOT).as_posix(): source_bytes(p) for p in source_paths()}
    files['tools/vina.exe'] = vina
    files['app_settings.json'] = b'{\n  "vina_executable": "tools/vina.exe"\n}\n'
    files['tools/README.md'] = (
        '# Bundled Windows executable\n\n'
        'This Windows ZIP contains the unmodified official AutoDock Vina 1.2.7\n'
        'executable, renamed to vina.exe. See ../README.md and\n'
        '../licenses/Vina-Windows-NOTICES.txt for provenance and licensing.\n'
        'This executable cannot run natively on Linux.\n'
    ).encode('utf-8')
    for name in ('INSTALL.cmd', 'START.cmd', 'CHECK.cmd'):
        text = (ROOT / 'examples/windows' / name).read_text(encoding='ascii')
        files[name] = text.replace('\r\n', '\n').replace('\n', '\r\n').encode('ascii')
    files['README.md'] = windows_readme()
    files['THIRD_PARTY_NOTICES.md'] = (
        '# Windows distribution supplement\n\n'
        'This Windows-with-Vina ZIP includes AutoDock Vina 1.2.7. The historical\n'
        'source-only inventory below describes the base source distribution.\n'
        'For the bundled executable see README.md, licenses/Vina-Windows-NOTICES.txt,\n'
        'licenses/AutoDock-Vina-LICENSE.txt\n'
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
    # Verify final archive bytes, not only the staging dictionary.
    with zipfile.ZipFile(target) as archive:
        assert len(archive.namelist()) == len(files)
        for name, item in manifest['files'].items():
            assert hashlib.sha256(archive.read('DockScreen/' + name)).hexdigest() == item['sha256']
        assert archive.read('DockScreen/app_settings.json') == files['app_settings.json']
        assert archive.testzip() is None
    print(f'Built and verified: {target} ({target.stat().st_size} bytes)')


if __name__ == '__main__':
    main()

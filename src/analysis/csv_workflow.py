"""Optional postprocessing of DockScreen's own docking CSV reports."""
from pathlib import Path

from src.admet.pipeline import enrich_run
from src.admet.workflow import completed_run
from src.reporting.admet import generate_run_reports
from src.reporting.combined import build_combined_data
from src.reporting.csv_import import import_docking_csv
from src.reporting.pareto_csv import (choose_protocol, run_pareto, write_criteria_template,
                                     DEFAULT_PRESET, DEFAULT_PRESET_ID)
from src.analysis.smaa_workflow import create_smaa_template, run_smaa
from src.core.settings_paths import run_settings_dir


def analyze_imported_csv(root, run_dir, *, mode='pareto+smaa', python_executable=None,
                         criteria_path=None, target=None, batch_size=16, timeout=600):
    if mode not in ('admet', 'pareto', 'smaa', 'pareto+smaa'):
        raise ValueError('Режим: admet / pareto / smaa / pareto+smaa')
    root = Path(root).resolve()
    run = completed_run(root, run_dir)
    data = build_combined_data(root, run, include_images=False)
    if mode != 'admet':
        if target is None and len(data['protocols']) == 1:
            target = data['protocols'][0]['target']
        protocol = choose_protocol(data, target)
    python = Path(python_executable) if python_executable is not None else None
    if python is not None and not python.is_absolute(): python = root / python
    print('ADMET: local prediction from report SMILES. Docking is not repeated.', flush=True)
    admet = enrich_run(root, run, python_executable=python, batch_size=batch_size, timeout=timeout)
    reports = generate_run_reports(root, run)
    result = {'run_dir': str(run), 'admet': admet, 'reports': [str(p) for p in reports], 'pareto': None, 'smaa': None}
    if admet.get('error'):
        raise RuntimeError(f'ADMET не завершён: {admet["error"]}. Импорт и доступные результаты сохранены: {run}')
    if mode == 'admet': return result
    if criteria_path is None:
        # Fail closed if a required default endpoint is unavailable.
        data = build_combined_data(root, run, include_images=False)
        missing = {s['key'] for s in DEFAULT_PRESET} - set(data['endpoints'])
        if missing: raise ValueError('Для полного набора отсутствуют параметры: ' + ', '.join(sorted(missing)))
        criteria = write_criteria_template(data, run_settings_dir(run) / 'PARETO_CRITERIA.csv')
        preset_id = DEFAULT_PRESET_ID
    else:
        criteria = Path(criteria_path)
        if not criteria.is_absolute(): criteria = root / criteria
        preset_id = None
    if mode in ('pareto', 'pareto+smaa'):
        result['pareto'] = run_pareto(root, run, criteria, target=target, protocol_id=protocol['id'], preset_id=preset_id)
        result['reports'].append(result['pareto']['report_html'])
    if mode in ('smaa', 'pareto+smaa'):
        settings = run_settings_dir(run) / 'SMAA_SETTINGS.json'
        print('SMAA: creating fixed scales using protocol data before bounds; '
              'Dirichlet alpha=1, 10000 scenarios, seed=42. Settings are saved in the new run.', flush=True)
        create_smaa_template(root, run, criteria, settings, target=target, protocol_id=protocol['id'])
        result['smaa'] = run_smaa(root, run, criteria, settings, target=target, protocol_id=protocol['id'],
                                  progress=lambda done, total: print(f'SMAA: {done}/{total}', flush=True), include_pareto=mode=='pareto+smaa')
        result['smaa_settings'] = str(settings)
        result['reports'].append(result['smaa']['report_html'])
    return result


def analyze_csv_report(root, path, **kwargs):
    mode = kwargs.get('mode', 'pareto+smaa')
    if mode not in ('admet', 'pareto', 'smaa', 'pareto+smaa'):
        raise ValueError('Режим: admet / pareto / smaa / pareto+smaa')
    run = import_docking_csv(root, path)
    print(f'CSV imported into new run: {run}', flush=True)
    return analyze_imported_csv(root, run, **kwargs)


def csv_analysis_menu(root, console):
    path = console.input('DockScreen CSV report: ').strip().strip('"')
    mode = console.input('1 — ADMET; 2 — ADMET + Pareto; 3 — ADMET + Pareto + SMAA; 4 — ADMET + SMAA [3]: ').strip() or '3'
    if mode not in ('1', '2', '3', '4'): raise ValueError('Choose 1, 2, 3 or 4')
    criteria = console.input('Criteria CSV (Enter — current defaults): ').strip().strip('"') if mode != '1' else ''
    python = console.input('ADMET Python (Enter — .venv-admet): ').strip().strip('"')
    console.print('Original CSV retained. The complete docking protocol cannot be recovered from CSV; '
                  'the import is marked as an unknown protocol. '
                  'Existing ADMET columns do not replace local predictions.', markup=False)
    run = import_docking_csv(root, path)
    console.print(f'New run: {run}', markup=False)
    target = None
    if mode != '1':
        data = build_combined_data(root, run, include_images=False)
        protocols = data['protocols']
        if len(protocols) == 1: target = protocols[0]['target']
        else:
            for i, p in enumerate(protocols, 1): console.print(f'{i}: {p["target"]}', markup=False)
            ordinal = int(console.input('Target number for Pareto/SMAA: ').strip())
            if not 1 <= ordinal <= len(protocols): raise ValueError('Invalid target number')
            target = protocols[ordinal - 1]['target']
    result = analyze_imported_csv(root, run, mode={'1':'admet','2':'pareto','3':'pareto+smaa','4':'smaa'}[mode],
                                  python_executable=python or None, criteria_path=criteria or None, target=target)
    console.print(f'Done: {result["run_dir"]}', markup=False)
    for p in result['reports']: console.print(f'Report: {p}', markup=False)
    for key in ('pareto', 'smaa'):
        if result[key]: console.print(f'{key}: {result[key]["directory"]}', markup=False)

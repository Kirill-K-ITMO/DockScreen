"""DockScreen launcher: terminal menu or non-interactive screening."""
import argparse
from pathlib import Path
from src.version import APP_NAME, __version__

def main():
    from src.ui.streams import configure_streams
    configure_streams()
    parser=argparse.ArgumentParser(description=f'{APP_NAME} {__version__}: SMILES preparation and Vina screening')
    parser.add_argument('--version',action='version',version=f'{APP_NAME} {__version__}')
    parser.add_argument('--project',type=Path,default=Path(__file__).resolve().parent)
    modes=parser.add_mutually_exclusive_group()
    modes.add_argument('--run',action='store_true',help='Run screening without interactive prompts')
    modes.add_argument('--check',action='store_true',help='Check selected screening inputs without running calculations')
    modes.add_argument('--admet-run',type=Path,help='Add local ADMET and a combined report to a completed screening run; no docking')
    modes.add_argument('--combined-report',type=Path,help='Regenerate the interactive report for a completed screening run')
    modes.add_argument('--pareto-menu',action='store_true',help='Set up and apply Pareto selection from an editable CSV')
    modes.add_argument('--pareto-template',type=Path,help='Create criteria CSV and endpoint catalogue for this completed run')
    modes.add_argument('--pareto-run',type=Path,help='Apply criteria CSV to a completed run; no docking or ADMET')
    modes.add_argument('--smaa-template',type=Path,help='Create fixed SMAA scales/preferences JSON; no analysis')
    modes.add_argument('--smaa-run',type=Path,help='Pareto + preference-only SMAA on saved results; no docking or ADMET')
    modes.add_argument('--smaa-menu',action='store_true',help='Separate SMAA template and execution actions')
    modes.add_argument('--csv-import',type=Path,help='Import a DockScreen docking CSV into a new saved run; no predictions')
    modes.add_argument('--csv-analyze',type=Path,help='Import DockScreen docking CSV and calculate local ADMET / Pareto / SMAA')
    modes.add_argument('--csv-analysis-menu',action='store_true',help='Analyze a saved DockScreen CSV report')
    parser.add_argument('--csv-analysis-mode',choices=['admet','pareto','smaa','pareto+smaa'],default='pareto+smaa')
    parser.add_argument('--smaa-only',action='store_true',help='With --smaa-run, generate only the SMAA report (all feasible candidates)')
    parser.add_argument('--smaa-settings',type=Path,help='SMAA scales/preferences JSON path')
    parser.add_argument('--pareto-criteria',type=Path,help='Editable criteria CSV path')
    parser.add_argument('--pareto-target',help='Explicit target/profile for file-based selection')
    parser.add_argument('--pareto-protocol',help='Exact protocol ID when a target contains multiple protocols')
    parser.add_argument('--admet-python',type=Path,help='Python in a separate ADMET environment (default .venv-admet)')
    parser.add_argument('--admet-batch-size',type=int,default=16)
    parser.add_argument('--admet-timeout',type=float,default=600,help='ADMET worker timeout in seconds')
    parser.add_argument('--admet-top',type=int,help='Predict only best N successful rows for --admet-target')
    parser.add_argument('--admet-target',help='Explicit receptor/profile used to choose top N')
    parser.add_argument('--ligands',type=Path,help='CSV path, relative to --project unless absolute')
    parser.add_argument('--receptors',nargs='+',help='Receptor filename stems; default: all in data/proteins')
    parser.add_argument('--targets',nargs='+',help='Explicit targets: receptor or receptor@profile (settings/receptors/receptor/profile.txt)')
    parser.add_argument('--smiles-column',help='Exact input CSV SMILES column name')
    parser.add_argument('--name-column',help='Exact input CSV molecule name/identifier column')
    parser.add_argument('--name-mode',choices=['preserve','row','column-row'],default=None)
    parser.add_argument('--name-prefix',help='Prefix for generated names (default ligand)')
    parser.add_argument('--delimiter',choices=['comma','semicolon','tab'],default=None)
    parser.add_argument('--vina',help='Executable name or path, relative to --project unless absolute')
    parser.add_argument('--cpu-budget',type=int)
    parser.add_argument('--cpu-per-job',type=int)
    parser.add_argument('--workers',type=int,default=4)
    parser.add_argument('--exhaustiveness',type=int,default=None,help='Override config effort; otherwise use config or 8')
    parser.add_argument('--seed',type=int,default=42,help='Default Vina seed; a receptor config seed takes precedence')
    parser.add_argument('--preparation-seed',type=int,default=42)
    parser.add_argument('--timeout',type=float,default=3600,help='Timeout in seconds per Vina task')
    parser.add_argument('--force-preparation',action='store_true')
    parser.add_argument('--force-docking',action='store_true')
    parser.add_argument('--no-html',action='store_true',help='Skip the optional HTML report')
    parser.add_argument('--export-zip',type=Path,help='Export this completed run to a compact result ZIP')
    parser.add_argument('--overwrite-zip',action='store_true',help='Explicitly replace an existing valid result ZIP')
    args=parser.parse_args()
    root=args.project.resolve()
    from src.core.preflight import check_dependencies,check_run,display
    dependencies=check_dependencies()
    if not dependencies.ready:
        display(dependencies)
        return 1
    app=None
    try:
        import math
        from src.core.cpu_budget import configure_project_cpu,project_budget,positive
        positive(args.workers,'workers')
        if args.exhaustiveness is not None: positive(args.exhaustiveness,'exhaustiveness')
        if args.receptors is not None and args.targets is not None:
            raise ValueError('Use either --receptors or --targets')
        if args.export_zip is not None and not (args.run or args.admet_run or args.combined_report or args.smaa_run or args.csv_analyze or args.pareto_run):
            raise ValueError('Use --run, --admet-run, --combined-report, --smaa-run --csv-analyze or --pareto-run with --export-zip')
        if args.overwrite_zip and args.export_zip is None:
            raise ValueError('Use --export-zip with --overwrite-zip')
        if not 1<=args.seed<=2147483647:
            raise ValueError('seed must be in 1..2147483647')
        if not 0<=args.preparation_seed<=2147483647:
            raise ValueError('preparation-seed must be in 0..2147483647')
        if not math.isfinite(args.timeout) or args.timeout<=0:
            raise ValueError('timeout must be finite and positive')
        if args.smaa_only and not args.smaa_run:
            raise ValueError('Use --smaa-only with --smaa-run')
        if args.csv_analysis_menu:
            from src.analysis.csv_workflow import csv_analysis_menu
            from src.ui.console import console
            csv_analysis_menu(root, console)
            return 0
        if args.csv_import or args.csv_analyze:
            from src.reporting.csv_import import import_docking_csv
            if args.csv_import:
                print(f'CSV imported: {import_docking_csv(root, args.csv_import)}')
            else:
                from src.analysis.csv_workflow import analyze_csv_report
                result = analyze_csv_report(root, args.csv_analyze, mode=args.csv_analysis_mode,
                    python_executable=args.admet_python, criteria_path=args.pareto_criteria,
                    target=args.pareto_target, batch_size=args.admet_batch_size, timeout=args.admet_timeout)
                print(f'Results: {result["run_dir"]}')
                for report in result['reports']: print(f'Report: {report}')
                for key in ('pareto', 'smaa'):
                    if result[key]: print(f'{key}: {result[key]["directory"]}')
                if args.export_zip is not None:
                    from src.core.project import ProjectUtils
                    destination = args.export_zip if args.export_zip.is_absolute() else root / args.export_zip
                    ProjectUtils(root).export_results_to_zip(output_file=destination,
                        run_dir=Path(result['run_dir']), include_docking_pdbqt=False, overwrite=args.overwrite_zip)
                    print(f'Result ZIP: {destination}')
            return 0
        if args.smaa_menu:
            from src.analysis.smaa_workflow import smaa_menu
            from src.ui.console import console
            smaa_menu(root, console)
            return 0
        if args.smaa_template or args.smaa_run:
            from src.analysis.smaa_workflow import create_smaa_template, run_smaa, WARNING
            if args.pareto_criteria is None or args.smaa_settings is None:
                raise ValueError('Use --pareto-criteria CSV and --smaa-settings JSON with SMAA')
            selected = args.smaa_template or args.smaa_run
            if args.smaa_template:
                path = create_smaa_template(root, selected, args.pareto_criteria, args.smaa_settings,
                                            target=args.pareto_target, protocol_id=args.pareto_protocol)
                print(f'Шаблон шкал SMAA: {path}. Границы получены до ограничений; проверьте JSON и выполните отдельный --smaa-run.')
            else:
                print(WARNING)
                result = run_smaa(root, selected, args.pareto_criteria, args.smaa_settings,
                                  target=args.pareto_target, protocol_id=args.pareto_protocol,
                                  progress=lambda done, total: print(f'SMAA: {done}/{total}', flush=True), include_pareto=not args.smaa_only)
                print(f'HTML: {result["report_html"]}')
                print(f'SMAA results: {result["directory"]}\nFeasible: {result["feasible"]}; effective top-N: {result["effective_top_n"]}')
                if args.export_zip is not None:
                    from src.admet.workflow import completed_run
                    from src.core.project import ProjectUtils
                    destination = args.export_zip if args.export_zip.is_absolute() else root / args.export_zip
                    ProjectUtils(root).export_results_to_zip(output_file=destination,
                        run_dir=completed_run(root, selected), overwrite=args.overwrite_zip)
                    print(f'Result ZIP: {destination}')
            return 0
        if args.pareto_menu:
            from src.reporting.pareto_csv import pareto_csv_menu
            from src.ui.console import console
            pareto_csv_menu(root, console)
            return 0
        if args.pareto_template or args.pareto_run:
            from src.admet.workflow import prepare_run
            from src.reporting.pareto_csv import create_templates, run_pareto
            run = prepare_run(root, args.pareto_template or args.pareto_run)
            if args.pareto_template:
                path, catalogue = create_templates(root, run, args.pareto_criteria)
                print(f'Criteria CSV: {path}\nAvailable parameters: {catalogue}')
            else:
                if args.pareto_criteria is None: raise ValueError('Use --pareto-criteria with --pareto-run')
                result = run_pareto(root, run, args.pareto_criteria, target=args.pareto_target,
                                    protocol_id=args.pareto_protocol)
                print(f'Candidates: {result["total"]}; feasible: {result["feasible"]}; front: {result["front"]}')
                print(f'Pareto results: {result["directory"]}')
                print(f'HTML: {result["report_html"]}')
                if args.export_zip is not None:
                    from src.core.project import ProjectUtils
                    destination = args.export_zip if args.export_zip.is_absolute() else root / args.export_zip
                    ProjectUtils(root).export_results_to_zip(output_file=destination,run_dir=run,
                        include_docking_pdbqt=False,overwrite=args.overwrite_zip)
                    print(f'Result ZIP: {destination}')
            return 0
        if args.admet_run or args.combined_report:
            from src.admet.workflow import prepare_run
            selected = args.admet_run or args.combined_report
            run_dir = prepare_run(root, selected)
            if args.admet_run:
                from src.admet.workflow import enrich_run
                python = args.admet_python
                if python is not None and not python.is_absolute(): python = root / python
                result = enrich_run(root, run_dir, python_executable=python,
                    batch_size=args.admet_batch_size, timeout=args.admet_timeout,
                    top_n=args.admet_top, target=args.admet_target)
                print(f'ADMET results retained: {run_dir / "admet.json"}')
                print(f'ADMET successful rows: {result.get("successful_rows", 0)}; failed: {result.get("failed", 0)}; '
                      f'cached structures: {result.get("cache_hits", 0)}; new: {result.get("new_predictions", 0)}')
                if result.get('error'): print(f'ADMET error: {result["error"]}. Docking files are retained.')
            from src.reporting.combined import generate_combined_report
            print(f'Interactive report: {generate_combined_report(root, run_dir)}')
            if (run_dir / 'admet.json').is_file():
                from src.reporting.admet import generate_run_reports
                for report_path in generate_run_reports(root, run_dir):
                    print(f'Docking + ADMET report: {report_path}')
            if args.export_zip is not None:
                from src.core.project import ProjectUtils
                destination = args.export_zip if args.export_zip.is_absolute() else root / args.export_zip
                ProjectUtils(root).export_results_to_zip(output_file=destination, run_dir=run_dir,
                    overwrite=args.overwrite_zip)
                print(f'Result ZIP: {destination}')
            return 2 if args.admet_run and result.get('failed', 0) else 0
        pool=project_budget(root)
        if args.cpu_budget is not None or args.cpu_per_job is not None:
            configure_project_cpu(root,args.cpu_budget if args.cpu_budget is not None else pool.total,
                                  args.cpu_per_job if args.cpu_per_job is not None else pool.per_job,save=False)
        if args.run or args.check:
            from src.docking.vina import AutoDockVina
            from src.preparation.inputs import read_ligand_rows_bytes, csv_options
            from src.core.app_settings import vina_path
            vina=args.vina
            if vina:
                candidate=Path(vina).expanduser()
                if not candidate.is_absolute() and (len(candidate.parts)>1 or (root/candidate).is_file()):
                    vina=str(root/candidate)
            docker=AutoDockVina(root,vina_executable=vina or vina_path(root),seed=args.seed,timeout=args.timeout)
            csv_path=args.ligands or Path('data/ligands.csv')
            if not csv_path.is_absolute(): csv_path=root/csv_path
            csv_bytes=csv_path.read_bytes()
            import_options=csv_options(root,csv_path,csv_bytes)
            for key,value in [('smiles_column',args.smiles_column),('name_column',args.name_column),
                              ('naming',args.name_mode),('name_prefix',args.name_prefix),('delimiter',args.delimiter)]:
                if value is not None: import_options[key]=value
            rows=read_ligand_rows_bytes(csv_bytes,**import_options)
            proteins=(args.targets if args.targets is not None else args.receptors if args.receptors is not None
                      else [p.stem for p in docker.get_proteins()])
            if args.targets is None and args.receptors is None:
                for receptor in proteins:
                    if docker.get_config(receptor) is None:
                        profiles=[target['id'] for target in docker.get_targets() if target['receptor']==receptor]
                        if profiles:
                            raise ValueError(f'{receptor} has profiles but no default configuration. '
                                             f'Select the intended site/protocol with --targets: {", ".join(profiles)}')
            proteins=list(dict.fromkeys(proteins))
            readiness=check_run(root,proteins=proteins,rows=rows,docker=docker,
                exhaustiveness=args.exhaustiveness,num_workers=args.workers,dependencies=False)
            display(readiness)
            if not readiness.ready: return 1
            if args.check: return 0
            from src.screening import run_screen
            report=run_screen(root,rows,proteins,docker,exhaustiveness=args.exhaustiveness,
                workers=args.workers,preparation_seed=args.preparation_seed,
                force_preparation=args.force_preparation,force_docking=args.force_docking,html=not args.no_html,
                input_csv=csv_path,input_csv_bytes=csv_bytes,input_options=import_options)
            print(f"Results: {report['run_dir']}")
            print(f"Successful pairs: {report['successful_pairs']}; failed pairs: {report['failed_pairs']}")
            for warning in report.get('reporting_errors',[]):
                print(f"Warning: {warning['format']} report failed: {warning['error']}. CSV/JSON results are retained.")
            if args.export_zip is not None:
                from src.core.project import ProjectUtils
                destination=args.export_zip if args.export_zip.is_absolute() else root/args.export_zip
                ProjectUtils(root).export_results_to_zip(output_file=destination,run_dir=Path(report['run_dir']),
                    overwrite=args.overwrite_zip)
                print(f'Result ZIP: {destination}')
            return 2 if report['failed_pairs'] else 0
        if any(value is not None for value in (args.vina,args.ligands,args.receptors,args.targets,
               args.smiles_column,args.name_column,args.name_mode,args.name_prefix,args.delimiter)):
            raise ValueError('Use --run or --check with --vina, --ligands or --receptors')
        from src.ui.application import DockScreenApp
        app=DockScreenApp(root)
        app.run()
        return 0
    except KeyboardInterrupt:
        print('Прервано. Незавершённый SMAA не опубликован как успешный. Сохранённые результаты расчётов сохранены.')
        return 130
    except Exception as error:
        print(f'Error: {error}')
        return 1
    finally:
        if app is not None: app.close()

if __name__=='__main__':
    raise SystemExit(main())

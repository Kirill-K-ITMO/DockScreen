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
    parser.add_argument('--ligands',type=Path,help='CSV path, relative to --project unless absolute')
    parser.add_argument('--receptors',nargs='+',help='Receptor filename stems; default: all in data/proteins')
    parser.add_argument('--targets',nargs='+',help='Explicit targets: receptor or receptor@profile (data/configs/receptor/profile.txt)')
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
        if args.export_zip is not None and not args.run:
            raise ValueError('Use --run with --export-zip')
        if args.overwrite_zip and args.export_zip is None:
            raise ValueError('Use --export-zip with --overwrite-zip')
        if not 1<=args.seed<=2147483647:
            raise ValueError('seed must be in 1..2147483647')
        if not 0<=args.preparation_seed<=2147483647:
            raise ValueError('preparation-seed must be in 0..2147483647')
        if not math.isfinite(args.timeout) or args.timeout<=0:
            raise ValueError('timeout must be finite and positive')
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
        print('Interrupted. Completed cache entries are retained. Repeat the same command to reuse them.')
        return 130
    except Exception as error:
        print(f'Error: {error}')
        return 1
    finally:
        if app is not None: app.close()

if __name__=='__main__':
    raise SystemExit(main())

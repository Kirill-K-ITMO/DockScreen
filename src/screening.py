"""Batch orchestration using the existing preparation and Vina implementations."""
from pathlib import Path
import hashlib
import uuid
from src.core.calculation_cache import atomic_json, atomic_write
from src.preparation.ligands import LigandConverter
from src.ui.progress import WorkProgress
from src.version import APP_NAME,__version__
from src.reporting.csv_safety import load_export_metadata, write_csv

def run_screen(root,rows,proteins,docker,*,exhaustiveness=8,workers=4,preparation_seed=42,
               force_preparation=False,force_docking=False,html=True,input_csv=None,input_csv_bytes=None,input_options=None):
    root=Path(root).resolve()
    rows=list(rows)
    input_options=dict(input_options or {})
    if input_csv_bytes is None and input_csv is not None:
        input_csv_bytes=Path(input_csv).read_bytes()
    if input_csv is not None and input_csv_bytes is not None and 'export_metadata' not in input_options:
        input_options['export_metadata']=load_export_metadata(input_csv,input_csv_bytes)
    if input_csv_bytes is not None:
        from src.preparation.inputs import read_ligand_rows_bytes
        if read_ligand_rows_bytes(input_csv_bytes,**input_options) != rows:
            raise ValueError('Input CSV snapshot does not match the requested rows')
    run_dir=root/'output/runs'/('screening-'+uuid.uuid4().hex)
    run_dir.mkdir(parents=True)
    if input_csv_bytes is not None:
        atomic_write(run_dir/'input.csv',input_csv_bytes)
        if input_options.get('export_metadata') is not None:
            atomic_json(run_dir/'input.csv.notes.json',{'csv_safety':input_options['export_metadata']})
    converter=LigandConverter(root)
    converter.preparation_seed=preparation_seed
    inputs=[];prepared={}
    with WorkProgress('Ligand preparation',len(rows)) as progress:
        for i,(name,smiles) in enumerate(rows,1):
            # Input labels are metadata, never filesystem paths or cache keys.
            label=f'row_{i:06d}'
            entry={'row_id':i,'label':label,'name':name,'smiles':smiles}
            try:
                record=converter.prepare_cached(smiles,force=force_preparation)
                prepared[label]=record['path']
                entry.update(status='prepared',preparation=record)
            except Exception as error:
                entry.update(status='preparation_failed',error=str(error))
            inputs.append(entry)
            progress.advance()
    atomic_json(run_dir/'preparation.json',inputs)
    results=docker.run_docking(proteins=proteins,ligand_paths=prepared,
        exhaustiveness=exhaustiveness,num_workers=workers,force=force_docking)
    for entry in inputs:
        for data in results.get(entry['label'],{}).values():
            data.update(smiles=entry['smiles'],input_name=entry['name'],selection_row_id=entry['row_id'],
                preparation_id=entry.get('preparation',{}).get('preparation_id'),
                molecule_id=entry.get('preparation',{}).get('molecule_id'))
    # Preserve input identities for subsequent reports opened from the terminal menu.
    docker._save_results_json()
    atomic_json(run_dir/'results.json',results)
    outcomes=getattr(docker,'task_outcomes',{})
    for entry in inputs:
        if entry['status'] == 'preparation_failed':
            outcomes[entry['label']] = {target: {'status':'preparation_failed','error':entry['error']} for target in proteins}
    atomic_json(run_dir/'task_outcomes.json',outcomes)
    from src.reporting.hits import export_hits
    hits=export_hits(results,run_dir/'hits',targets=proteins)
    successful=sum(len(values) for values in results.values())
    summary={'application':APP_NAME,'version':__version__,'run_dir':str(run_dir),
        'input_csv':str(input_csv) if input_csv else None,
        'input_csv_sha256':hashlib.sha256(input_csv_bytes).hexdigest() if input_csv_bytes is not None else None,
        'input_csv_snapshot':str(run_dir/'input.csv') if input_csv_bytes is not None else None,
        'csv_import_options':input_options,'hits':hits,
        'input_rows':len(rows),'receptors':proteins,'successful_pairs':successful,
        'failed_pairs':len(rows)*len(proteins)-successful,'vina':docker.vina_version,
        'exhaustiveness':exhaustiveness,'workers':workers,'default_vina_seed':docker.seed,
        'preparation_seed':preparation_seed,'timeout':docker.timeout,
        'force_preparation':force_preparation,'force_docking':force_docking,
        'cpu':docker.cpu_pool.snapshot(),'docking_statistics':docker.stats,
        'docking_batch_dir':str(docker.last_batch_dir)}
    headers=['row_id','name','smiles','receptor','status','affinity_kcal_mol','error',
        'scoring','score_units','ranking_direction','evaluation_id','preparation_id','molecule_id','target_id','config_id']
    score_rows=[]
    for entry in inputs:
        for receptor in proteins:
            data=results.get(entry['label'],{}).get(receptor)
            outcome=outcomes.get(entry['label'],{}).get(receptor,{})
            score_rows.append({'row_id':entry['row_id'],'name':entry['name'],'smiles':entry['smiles'],
                'receptor':data.get('receptor',receptor.split('@')[0]) if data else receptor.split('@')[0],
                'target_id':receptor,'config_id':data.get('config_id','default') if data else receptor.split('@',1)[1] if '@' in receptor else 'default',
                'status':'success' if data else entry['status'] if entry['status']!='prepared' else outcome.get('status','docking_failed'),
                'affinity_kcal_mol':data['affinity'] if data else '',
                'error':entry.get('error','') if entry['status']!='prepared' else '' if data else outcome.get('error','See docking statistics and logs'),
                'scoring':data.get('spec',{}).get('options',{}).get('scoring','') if data else '',
                'score_units':'kcal/mol','ranking_direction':'lower_is_better',
                'evaluation_id':data.get('evaluation_id','') if data else '',
                'preparation_id':entry.get('preparation',{}).get('preparation_id',''),
                'molecule_id':entry.get('preparation',{}).get('molecule_id','')})
    write_csv(run_dir/'scores.csv',headers,score_rows,
        text_columns=[h for h in headers if h not in ('row_id','affinity_kcal_mol')],
        notes={'kind':'screening_scores','units':'kcal/mol','ranking_direction':'lower_is_better'})
    summary['reporting_errors'] = []
    summary['html_report'] = None
    atomic_json(run_dir/'summary.json',summary)
    if html and results:
        temporary_report = run_dir / '.report.html.part'
        try:
            from src.docking.affinity import AffinityCalculator
            from src.reporting.docking import ReportGenerator
            enriched=AffinityCalculator().process_docking_results(results)
            ReportGenerator(root).generate_html_report(enriched,
                smiles_dict={e['label']:e['smiles'] for e in inputs},output_file=temporary_report,
                title='Screening results',exhaustiveness=exhaustiveness)
            temporary_report.replace(run_dir/'report.html')
            summary['html_report'] = str(run_dir/'report.html')
        except Exception as error:
            summary['reporting_errors'].append({'format':'html','error':str(error)})
            try:
                temporary_report.unlink(missing_ok=True)
            except OSError:
                pass
    atomic_json(run_dir/'summary.json',summary)
    return summary

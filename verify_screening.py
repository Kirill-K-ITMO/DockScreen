"""Separate technical check with an installed, real Vina executable."""
import argparse
import csv
import json
from pathlib import Path
import shutil
import tempfile
from src.core.calculation_cache import atomic_json,validate_pdbqt
from src.core.cpu_budget import configure_project_cpu
from src.docking.vina import AutoDockVina
from src.screening import run_screen

def verify(vina,data,output):
    output=Path(output).resolve()
    report={'status':'failed','checks':{},'error':None}
    try:
        with tempfile.TemporaryDirectory(prefix='dockscreen-verification-') as folder:
            root=Path(folder)
            for sub in ['proteins','configs']:
                shutil.copytree(Path(data)/sub,root/'data'/sub)
            proteins=sorted(p.stem for p in (root/'data/proteins').glob('*.pdbqt'))
            if len(proteins)<2: raise ValueError('Verification requires at least two real receptor files')
            proteins=proteins[:2]
            configure_project_cpu(root,2,1)
            docker=AutoDockVina(root,vina_executable=vina,seed=42,timeout=180)
            rows=[('ethanol','CCO'),('ethylamine','CCN')]
            first=run_screen(root,rows,proteins,docker,exhaustiveness=1,workers=4)
            a=json.loads((Path(first['run_dir'])/'results.json').read_text(encoding='utf-8'))
            pairs=len(rows)*len(proteins)
            report['checks']['all_pairs_successful']=first['successful_pairs']==pairs
            report['checks']['real_calculations']=first['docking_statistics']['executed']==pairs
            report['checks']['cpu_budget_respected']=0<docker.cpu_pool.peak<=docker.cpu_pool.total
            pose_ok=True
            for targets in a.values():
                for result in targets.values():
                    pose=Path(result['output_file']).read_bytes()
                    validate_pdbqt(pose)
                    pose_ok &= b'REMARK VINA RESULT:' in pose
            report['checks']['real_pose_files']=pose_ok
            second=run_screen(root,rows,proteins,docker,exhaustiveness=1,workers=4)
            b=json.loads((Path(second['run_dir'])/'results.json').read_text(encoding='utf-8'))
            energies=lambda r:{(lig,prot):v['affinity'] for lig,targets in r.items() for prot,v in targets.items()}
            report['checks']['same_scores_on_repeat']=energies(a)==energies(b)
            report['checks']['repeat_uses_cache']=second['docking_statistics']['cached']==pairs and second['docking_statistics']['executed']==0
            # One malformed receptor must not remove successful pairs for the other.
            broken=root/'data/proteins'/f'{proteins[1]}.pdbqt'
            broken.write_text('invalid receptor\n')
            partial=run_screen(root,rows,proteins,docker,exhaustiveness=1,workers=4,html=False)
            with (Path(partial['run_dir'])/'scores.csv').open(encoding='utf-8',newline='') as stream:
                table=list(csv.DictReader(stream))
            report['checks']['partial_failures_preserve_success']=partial['successful_pairs']==len(rows) and partial['failed_pairs']==len(rows)
            report['checks']['csv_keeps_failed_pairs']=len(table)==pairs and sum(x['status']=='docking_failed' for x in table)==len(rows)
            report.update(vina=docker.vina_version,first_new_dockings=first['docking_statistics']['executed'],
                repeat_cache_hits=second['docking_statistics']['cached'],repeat_new_dockings=second['docking_statistics']['executed'],
                scores=[{'ligand':lig,'receptor':prot,'affinity':value} for (lig,prot),value in energies(a).items()])
            report['status']='passed' if all(report['checks'].values()) else 'failed'
    except Exception as error:
        report['error']=str(error)
    atomic_json(output,report)
    return report

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vina',required=True,help='Path to an installed real Vina executable')
    parser.add_argument('--data',type=Path,default=Path(__file__).resolve().parent/'data')
    parser.add_argument('--output',type=Path,default=Path('screening_verification.json'))
    args=parser.parse_args()
    vina=shutil.which(args.vina)
    if vina is None: parser.error('Vina executable not found')
    report=verify(str(Path(vina).resolve()),args.data,args.output)
    print(json.dumps(report,indent=2))
    return 0 if report['status']=='passed' else 1

if __name__=='__main__':
    raise SystemExit(main())

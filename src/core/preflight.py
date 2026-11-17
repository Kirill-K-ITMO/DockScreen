"""Readiness checks for screening inputs; no preparation or docking is run."""
from dataclasses import dataclass, field
from pathlib import Path
import importlib
import sys
import tempfile

@dataclass
class Readiness:
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    summary: dict = field(default_factory=dict)

    @property
    def ready(self):
        return not self.errors

    def require(self):
        if self.errors:
            raise ValueError("Calculation is not ready:\n" + "\n".join(self.errors))

    def to_dict(self):
        return dict(ready=self.ready, errors=self.errors, warnings=self.warnings, summary=self.summary)

def check_dependencies():
    report = Readiness()
    report.summary['Python'] = sys.version.split()[0]
    if sys.version_info[:2] != (3, 12):
        report.warnings.append('This build is tested with Python 3.12; the current version differs.')
    for name in ('rdkit.Chem','rdkit.Chem.AllChem','meeko','gemmi','numpy','scipy','rich','filelock','jinja2'):
        try:
            importlib.import_module(name)
        except Exception as error:
            report.errors.append(f'{name}: {error}. Install requirements.txt in the active environment.')
    return report

def _probe_directory(path):
    path.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryFile(dir=path) as stream:
        stream.write(b'dockscreen-readiness')
        stream.flush()

def check_run(root, *, proteins=None, rows=None, ligands=None, exhaustiveness=8,
              num_workers=4, docker=None, dependencies=True):
    root = Path(root).resolve()
    report = check_dependencies() if dependencies else Readiness()
    report.summary['Project'] = str(root)
    if report.errors:
        return report
    from src.core.cpu_budget import positive
    try:
        positive(num_workers,'num_workers')
        if exhaustiveness is not None:
            positive(exhaustiveness,'exhaustiveness')
    except ValueError as error:
        report.errors.append(str(error))
        # Invalid API arguments must remain a readiness error; continuing could
        # fail in worker-count arithmetic or create directories unnecessarily.
        return report
    for path in (root/'output', root/'.calculation_cache/v1'):
        try:
            _probe_directory(path)
        except OSError as error:
            report.errors.append(f'Cannot write to {path}: {error}')
    if docker is None:
        try:
            from src.docking.vina import AutoDockVina
            docker = AutoDockVina(root)
        except Exception as error:
            report.errors.append(f'Vina/CPU: {error}. Check app_settings.json and cpu_settings.json.')
    if docker is not None:
        if proteins is None:
            try:
                proteins = [target['id'] for target in docker.get_targets()]
            except (ValueError, OSError) as error:
                report.errors.append(f'Targets: {error}')
                proteins = []
        report.summary.update({'Vina':docker.vina_version,'Exhaustiveness':exhaustiveness,
            'CPU budget':docker.cpu_pool.total,'Maximum CPU threads per Vina job':docker.cpu,
            'Concurrent jobs (upper limit)':min(num_workers,docker.cpu_pool.total)})
        from src.core.calculation_cache import validate_pdbqt
        if not proteins:
            report.errors.append('No receptors selected.')
        for name in proteins or []:
            try:
                target = docker.resolve_target(name)
                validate_pdbqt(target['receptor_path'].read_bytes())
                conf = target['config_path']
                docker._effective_options(conf,exhaustiveness)
            except Exception as error:
                report.errors.append(f'Receptor {name}: {error}')
    try:
        if rows is None:
            from src.preparation.inputs import read_ligand_rows, csv_options
            csv_path = Path(ligands) if ligands else Path('data/ligands.csv')
            if not csv_path.is_absolute():
                csv_path = root / csv_path
            rows = read_ligand_rows(csv_path, **csv_options(root,csv_path))
        if not rows:
            raise ValueError('The CSV or molecule selection is empty')
        from src.core.calculation_cache import molecule_identity
        from src.preparation.validation import validated_molecule
        seen = set()
        for name,smiles in rows:
            try:
                validated_molecule(smiles)
                seen.add(molecule_identity(smiles)[0])
            except Exception as error:
                report.errors.append(f'{name}: {error}')
        report.summary['Input rows / unique valid molecules'] = f'{len(rows)} / {len(seen)}'
        if len(rows)>len(seen) and not report.errors:
            report.warnings.append('Repeated structures retain separate input rows and reuse the calculation cache.')
        report.summary['Molecule-receptor pairs'] = len(rows)*len(proteins or [])
    except Exception as error:
        report.errors.append(f'Ligand input: {error}')
    report.summary['Results'] = str(root/'output/runs')
    return report

def check_project(root, *, ligands=None):
    return check_run(root,ligands=ligands)

def display(report,console=None):
    def emit(message):
        if console is None:
            print(message)
        else:
            console.print(message,markup=False)
    emit('DockScreen readiness check')
    for key,value in report.summary.items(): emit(f'{key}: {value}')
    for message in report.warnings: emit(f'Note: {message}')
    for message in report.errors: emit(f'Error: {message}')
    emit('Ready to run.' if report.ready else 'Calculation blocked. Resolve the errors and repeat the check.')

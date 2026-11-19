"""Compact result archives and project input/status utilities."""

import zipfile
from src.core.settings_paths import receptor_settings_dir
from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime
import logging

class ProjectUtils:
    """
    Project utility functions.
    """
    
    def __init__(self, project_root: Optional[Path] = None):
        """
        Initialize project utilities.
        
        Args:
            project_root: Project root directory (default: current directory)
        """
        self.project_root = project_root or Path.cwd()
        
        # Directory paths
        self.data_dir = self.project_root / "data"
        self.ligands_csv = self.data_dir / "ligands.csv"
        self.ligands_pdbqt_dir = self.project_root / "output" / "ligands_pdbqt"
        self.docking_results_dir = self.project_root / "output" / "docking_results"
        self.reports_dir = self.project_root / "output" / "reports"
        self.cache_dir = self.project_root / "output" / "cache"
        
        # Configure logging
        self.logger = logging.getLogger(__name__)
    
    def export_results_to_zip(self, output_file: Optional[Path] = None,
                              include_ligands_csv: bool = True,
                              include_ligands_pdbqt: bool = False,
                              include_docking_pdbqt: bool = True,
                              include_reports: bool = True,
                              include_logs: bool = False, run_dir=None, overwrite: bool = False) -> Path:
        """Export one completed run, with compact provenance and optional poses.

        No calculation cache, database, input/prepared trees or runtime is bundled.
        If no run is available, export standalone legacy reports only.
        """
        import hashlib
        import io
        import json
        import os
        import stat
        import tempfile

        root = Path(self.project_root).resolve()
        from src.reporting.document_names import document_stem
        from datetime import timezone
        import uuid
        output_file = Path(output_file) if output_file is not None else root / (
            document_stem(kind='RESULTS',target='all-targets',identity=uuid.uuid4().hex,created_utc=datetime.now(timezone.utc).isoformat())+'.zip')
        if not output_file.is_absolute():
            output_file = root / output_file
        # abspath normalizes '..' without following a destination symlink.
        output_file = Path(os.path.abspath(output_file))
        if not isinstance(overwrite, bool):
            raise ValueError('overwrite must be a boolean')
        if output_file.suffix.lower() != '.zip':
            raise ValueError('Result archive destination must have a .zip suffix')

        def no_destination_links():
            for path in (*reversed(output_file.parents), output_file):
                try:
                    info = path.lstat()
                except FileNotFoundError:
                    continue
                if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
                    raise ValueError(f'Archive destination must not contain symlinks or junctions: {path}')

        no_destination_links()
        protected = ('data', 'settings', 'src', 'docs', 'tests', 'scripts', 'assets', 'licenses',
                     '.git', '.venv', '.calculation_cache', 'output/runs', 'output/inputs',
                     'output/prepared', 'output/docking_results', 'output/cache')
        if any(output_file.is_relative_to(root / directory) for directory in protected):
            raise ValueError('Archive destination is inside a protected project directory')
        selected, missing = {}, []

        def protect_source(path):
            path = Path(path)
            if not path.is_absolute():
                path = root / path
            if path.resolve() == output_file or (path.exists() and output_file.exists()
                                                and os.path.samefile(path, output_file)):
                raise ValueError(f'Archive destination collides with an input or run artifact: {path}')

        def protect_references(value):
            if isinstance(value, dict):
                for key, item in value.items():
                    if key in ('input_csv', 'input_csv_snapshot', 'output_file', 'config_path',
                               'receptor_path', 'path') and isinstance(item, str) and item:
                        protect_source(item)
                    elif key == 'input_files' and isinstance(item, dict):
                        for source in item.values():
                            if isinstance(source, str) and source:
                                protect_source(source)
                    protect_references(item)
            elif isinstance(value, list):
                for item in value:
                    protect_references(item)

        def checked(path):
            path = Path(path)
            if not path.is_absolute():
                path = root / path
            if not path.resolve().is_relative_to(root):
                raise ValueError(f'Export source escapes the project: {path}')
            return path

        def add(path, name):
            path = checked(path)
            protect_source(path)
            if path.is_file():
                if name in selected:
                    raise ValueError(f'Duplicate archive member: {name}')
                selected[name] = (path.read_bytes(), str(path.resolve()))

        def read_json(path):
            path = checked(path)
            # Invalid metadata must fail visibly, never masquerade as an empty run.
            protect_source(path)
            value = json.loads(path.read_text(encoding='utf-8'))
            protect_references(value)
            return value

        runs = root / 'output/runs'
        if run_dir is not None:
            chosen = checked(run_dir)
            if chosen.resolve() == runs.resolve() or not chosen.resolve().is_relative_to(runs.resolve()):
                raise ValueError('Choose a run directory inside output/runs')
            if not chosen.is_dir() or not (chosen / 'results.json').is_file():
                raise ValueError('Choose a run directory containing results.json')
        else:
            screening = list(runs.glob('screening-*/summary.json'))
            docking = list(runs.glob('docking-*/results.json'))
            candidates = screening + docking
            chosen = max(candidates, key=lambda p: (p.stat().st_mtime_ns, str(p))).parent if candidates else None

        results, preparation = {}, []
        if chosen is not None:
            chosen = checked(chosen)
            results = read_json(chosen / 'results.json')
            if not isinstance(results, dict) or any(not isinstance(v, dict) for v in results.values()):
                raise ValueError('Invalid results.json structure')
            for filename in ('results.json', 'preparation.json', 'summary.json', 'outcomes.json', 'task_outcomes.json', 'statistics.json', 'admet.json'):
                path = chosen / filename
                if path.is_file():
                    value = read_json(path)
                    if filename == 'preparation.json':
                        if not isinstance(value, list):
                            raise ValueError('Invalid preparation.json structure')
                        preparation = value
                    add(path, 'run/' + filename)
            if include_ligands_csv:
                add(chosen / 'input.csv', 'run/input.csv')
                add(chosen / 'input.csv.notes.json', 'run/input.csv.notes.json')
            if include_reports:
                for name in ('scores.csv', 'report.html', 'scores.csv.notes.txt', 'scores.csv.notes.json',
                             'admet.csv', 'admet.csv.notes.json', 'combined_report.html',
                             'pareto_criteria.csv', 'pareto_parameters.csv'):
                    path = chosen / name
                    if path.is_file(): add(path, 'run/' + path.name)
                for folder in ('hits', 'reports', 'pareto', 'settings'):
                    for path in sorted((chosen / folder).rglob('*')):
                        if (path.is_file() and path.suffix.lower() in ('.csv', '.html', '.json', '.txt')
                                and not any(part.startswith('.') or part.lower() in ('tmp','temp','cache','__pycache__')
                                            for part in path.relative_to(chosen / folder).parts)):
                            add(path, 'run/' + folder + '/' + path.relative_to(chosen / folder).as_posix())
                # Only published complete SMAA analyses; cancellation/staging are never exported.
                for analysis in sorted((chosen / 'smaa').glob('analysis-*')):
                    if not analysis.is_dir(): continue
                    marker = analysis / 'status.json'
                    if not marker.is_file() or read_json(marker).get('status') != 'complete': continue
                    for path in sorted(analysis.rglob('*')):
                        if (path.is_file() and path.suffix.lower() in ('.csv', '.json', '.txt', '.html')
                                and not any(p.startswith('.') for p in path.relative_to(analysis).parts)):
                            add(path, 'run/smaa/' + analysis.name + '/' + path.relative_to(analysis).as_posix())
            if include_logs:
                for path in sorted(chosen.rglob('*.log')):
                    add(path, 'run/logs/' + path.relative_to(chosen).as_posix())
        elif include_reports:
            for path in sorted(Path(self.reports_dir).rglob('*')):
                if (path.is_file() and path.suffix.lower() in ('.csv', '.html', '.txt', '.json')
                        and not any(part.startswith('.') or part.lower() in ('tmp','temp','cache','__pycache__')
                                    for part in path.relative_to(self.reports_dir).parts)):
                    add(path, 'reports/' + path.relative_to(self.reports_dir).as_posix())

        provenance = {'kind': 'compact_result_provenance', 'run': str(chosen) if chosen else None,
            'note': 'Results export; source structures and prepared inputs are not bundled. Hashes identify them but do not reconstruct them.',
            'results': [], 'preparation': []}
        pose_members = {}
        for label, targets in results.items():
            for target, data in targets.items():
                if not isinstance(data, dict):
                    raise ValueError(f'Invalid result for {label}/{target}')
                record = {'label': label, 'target_id': target}
                record.update({key: data[key] for key in ('input_name', 'smiles', 'affinity', 'spec',
                    'evaluation_id', 'artifact_sha', 'config_sha256', 'receptor', 'config_id',
                    'preparation_id', 'molecule_id', 'cache_hit') if key in data})
                if include_docking_pdbqt:
                    path_value = data.get('output_file')
                    if not path_value:
                        missing.append({'label': label, 'target_id': target, 'role': 'pose', 'reason': 'No output_file reference'})
                    else:
                        path = checked(path_value)
                        if not path.is_file():
                            missing.append({'label': label, 'target_id': target, 'role': 'pose', 'source_path': str(path), 'reason': 'File missing'})
                        else:
                            resolved = str(path.resolve())
                            if resolved not in pose_members:
                                content = path.read_bytes()
                                sha = hashlib.sha256(content).hexdigest()
                                expected = data.get('artifact_sha')
                                if expected and expected != sha:
                                    raise ValueError(f'Pose checksum mismatch: {path}')
                                member = 'poses/' + sha + '.pdbqt'
                                if member not in selected:
                                    selected[member] = (content, resolved)
                                pose_members[resolved] = member
                            record['pose_member'] = pose_members[resolved]
                provenance['results'].append(record)
        for entry in preparation:
            if not isinstance(entry, dict):
                raise ValueError('Invalid preparation record')
            item = {key: entry[key] for key in ('row_id', 'label', 'name', 'smiles', 'status', 'error') if key in entry}
            prep = entry.get('preparation', {})
            if not isinstance(prep, dict):
                raise ValueError('Invalid preparation metadata')
            item['preparation'] = {key: prep[key] for key in ('preparation_id', 'molecule_id',
                'canonical_smiles', 'artifact_sha', 'spec', 'preparation_details') if key in prep}
            provenance['preparation'].append(item)
        if include_ligands_pdbqt:
            for path in sorted(Path(self.ligands_pdbqt_dir).glob('*.pdbqt')):
                add(path, 'legacy_ligands/' + path.name)
        selected['PROVENANCE.json'] = (json.dumps(provenance, ensure_ascii=False, indent=2, allow_nan=False).encode('utf-8'), None)
        manifest = {'format': 2, 'kind': 'result_export', 'selected_run': str(chosen) if chosen else None,
            'created_at': datetime.now().isoformat(), 'missing_artifacts': missing,
            'options': dict(include_ligands_csv=include_ligands_csv,
                include_ligands_pdbqt=include_ligands_pdbqt, include_docking_pdbqt=include_docking_pdbqt,
                include_reports=include_reports, include_logs=include_logs), 'files': {}}
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
            for name, (content, source) in sorted(selected.items()):
                archive.writestr(name, content)
                manifest['files'][name] = {'sha256': hashlib.sha256(content).hexdigest(),
                    'size': len(content), 'source_path': source}
            archive.writestr('MANIFEST.json', json.dumps(manifest, ensure_ascii=False, indent=2))
            archive.writestr('CONTENTS.txt', 'DockScreen result export; not a runnable project or cache backup.\n\n' +
                '\n'.join(sorted([*selected, 'MANIFEST.json', 'CONTENTS.txt'])) + '\n')
        def check_existing():
            no_destination_links()
            try:
                info = output_file.lstat()
            except FileNotFoundError:
                return
            if not overwrite:
                raise FileExistsError(f'Archive already exists; choose another name or explicit overwrite: {output_file}')
            if not stat.S_ISREG(info.st_mode) or not zipfile.is_zipfile(output_file):
                raise ValueError('Explicit overwrite is allowed only for an existing regular ZIP archive')
            # Check the central directory too, not just the ZIP signature.
            with zipfile.ZipFile(output_file) as previous:
                if previous.testzip() is not None:
                    raise ValueError('Existing archive is damaged; refusing to overwrite it')

        # Metadata validation precedes the existing-destination policy.
        check_existing()
        output_file.parent.mkdir(parents=True, exist_ok=True)
        no_destination_links()
        descriptor, temporary = tempfile.mkstemp(prefix='.archive-', suffix='.tmp', dir=output_file.parent)
        try:
            with os.fdopen(descriptor, 'wb') as stream:
                stream.write(buffer.getvalue())
                stream.flush()
                os.fsync(stream.fileno())
            check_existing()
            if overwrite:
                os.replace(temporary, output_file)
            else:
                # Atomic no-clobber publication, even if a competing writer has
                # created the destination since the existence check above.
                os.link(temporary, output_file)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        self.logger.info('ZIP archive created: %s', output_file)
        return output_file

    def load_ligands_from_csv(self, csv_path: Optional[Path] = None) -> List[Dict[str, str]]:
        """
        Load ligands from a CSV file.
        
        Args:
            csv_path: CSV file path
            
        Returns:
            List of ligand data dictionaries
        """
        if csv_path is None:
            csv_path = self.ligands_csv
        
        if not csv_path.exists():
            self.logger.error(f"CSV file not found: {csv_path}")
            return []
        
        ligands = []
        
        try:
            from src.preparation.inputs import read_ligand_rows, unambiguous_rows, csv_options
            ligands=[{"name":name,"smiles":smiles} for name,smiles in unambiguous_rows(
                read_ligand_rows(csv_path, **csv_options(self.project_root,csv_path)))]

            self.logger.info(f"Ligands loaded: {len(ligands)}")
        
        except Exception as e:
            self.logger.error(f"Failed to read CSV: {e}")
        
        return ligands

    def validate_project_structure(self) -> Dict[str, bool]:
        """
        Check the project structure and required files.
        
        Returns:
            Dictionary of check results
        """
        checks = {
            'data_dir': self.data_dir.exists(),
            'proteins_dir': (self.data_dir / "proteins").exists(),
            'configs_dir': receptor_settings_dir(self.project_root).exists(),
            'ligands_csv': self.ligands_csv.exists(),
            'output_dir': (self.project_root / "output").exists(),
            'src_dir': (self.project_root / "src").exists()
        }
        
        # Additional checks
        if checks['proteins_dir']:
            proteins = list((self.data_dir / "proteins").glob("*.pdbqt"))
            checks['proteins_count'] = len(proteins)
        else:
            checks['proteins_count'] = 0
        
        if checks['configs_dir']:
            configs = list(receptor_settings_dir(self.project_root).glob("*.txt"))
            checks['configs_count'] = len(configs)
        else:
            checks['configs_count'] = 0
        
        return checks
    
    def print_project_status(self):
        """Display project status."""
        checks = self.validate_project_structure()
        
        print("PROJECT STATUS")
        
        print("\nStructure:")
        print(f"  {'✓' if checks['data_dir'] else '✗'} Directory data/")
        print(f"  {'✓' if checks['proteins_dir'] else '✗'} Directory data/proteins/ (receptors: {checks['proteins_count']})")
        print(f"  {'✓' if checks['configs_dir'] else '✗'} Directory settings/receptors/ (configurations: {checks['configs_count']})")
        print(f"  {'✓' if checks['ligands_csv'] else '✗'} File data/ligands.csv")
        print(f"  {'✓' if checks['output_dir'] else '✗'} Directory output/")
        print(f"  {'✓' if checks['src_dir'] else '✗'} Directory src/")
        
        # Statistics
        ligands = self.load_ligands_from_csv()
        ligands_pdbqt = list(self.ligands_pdbqt_dir.glob("*.pdbqt")) if self.ligands_pdbqt_dir.exists() else []
        docking_results = list(self.docking_results_dir.rglob("*.pdbqt")) if self.docking_results_dir.exists() else []
        reports = list(self.reports_dir.glob("*.html")) if self.reports_dir.exists() else []
        
        print("\nStatistics:")
        print(f"  Ligands in CSV: {len(ligands)}")
        print(f"  PDBQT files generated: {len(ligands_pdbqt)}")
        print(f"  Docking results: {len(docking_results)}")
        print(f"  Reports: {len(reports)}")

    def get_available_proteins(self) -> List[str]:
        """
        Return available receptors.
        
        Returns:
            List of receptor names (without extensions)
        """
        proteins_dir = self.data_dir / "proteins"
        
        if not proteins_dir.exists():
            return []
        
        proteins = [p.stem for p in proteins_dir.glob("*.pdbqt")]
        return sorted(proteins)

def export_results(output_file: Optional[Path] = None,
                  include_all: bool = True,
                  project_root: Optional[Path] = None) -> Path:
    """
    Convenience function to export results to ZIP.
    
    Args:
        output_file: ZIP file path
        include_all: Include all available data
        project_root: Project root directory
        
    Returns:
        Path to the created ZIP file
    """
    utils = ProjectUtils(project_root=project_root)
    
    return utils.export_results_to_zip(
        output_file=output_file,
        include_ligands_csv=True,
        include_ligands_pdbqt=False,
        include_docking_pdbqt=True,
        include_reports=True,
        include_logs=include_all
    )


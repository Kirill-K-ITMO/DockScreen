"""External Vina execution, per-pair outcomes and reproducible calculation caching."""

import math
import shutil
import tempfile
import platform
import uuid
from threading import Lock, local
from src.core.cpu_budget import project_budget, positive, child_environment
from src.core.calculation_cache import (CalculationCache, digest, atomic_write, atomic_json,
                                   validate_pdbqt)
import subprocess
import json
from pathlib import Path
from typing import List, Dict, Tuple, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
import logging
from datetime import datetime
import time

def validate_timeout(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise ValueError('timeout must be finite and positive')
    return value

class AutoDockVina:
    """
    Perform molecular docking with AutoDock Vina.
    
    Supports:
    - Multi-target docking (multiple receptors)
    - Parallel processing
    - Configurable exhaustiveness
    - Saving results
    - Progress bars and timers
    """
    
    def __init__(self, project_root: Optional[Path] = None, *, vina_executable=None,
                 seed: int = 42, cpu: int | None = None, timeout: float = 3600,
                 cpu_budget: int | None = None):
        """
        Initialize the docking module.
        
        Args:
            project_root: Project root directory (default: current directory)
        """
        self.project_root = Path(project_root or Path.cwd()).resolve()
        from src.core.app_settings import vina_path
        self.vina_executable = str(vina_executable) if vina_executable is not None else vina_path(self.project_root)
        self.cpu_pool = project_budget(self.project_root, total=cpu_budget)
        self._cpu_override = positive(cpu,"cpu") if cpu is not None else None
        self.seed, self.timeout = seed, validate_timeout(timeout)
        self._task_local = local()
        self.task_outcomes = {}
        self._stats_lock = Lock()
        self.calculation_cache = CalculationCache(self.project_root / ".calculation_cache" / "v1")
        self.last_batch_dir = None
        
        # Directory paths
        self.data_dir = self.project_root / "data"
        self.proteins_dir = self.data_dir / "proteins"
        self.configs_dir = self.data_dir / "configs"
        self.ligands_dir = self.project_root / "output" / "ligands_pdbqt"
        self.results_dir = self.project_root / "output" / "docking_results"
        self.cache_dir = self.project_root / "output" / "cache"
        
        # Create the required directories
        self.results_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        # Docking statistics
        self.stats = {
            'total_dockings': 0,
            'successful': 0,
            'failed': 0,
            'cached': 0,
            'errors': [],
            'elapsed_time': 0
        }
        
        # Docking results
        self.docking_results = {}  # {ligand_name: {protein_name: {affinity, energy, ...}}}
        
        # Configure logging
        self._setup_logging()
        
        # Check the Vina installation
        self._check_vina()
    
    @property
    def cpu(self):
        return min(self._cpu_override or self.cpu_pool.per_job,self.cpu_pool.total)

    def _setup_logging(self):
        """Configure logging for docking."""
        logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
        self.logger = logging.getLogger(__name__)
    
    def _check_vina(self):
        executable = shutil.which(self.vina_executable)
        if executable is None:
            raise RuntimeError("AutoDock Vina executable not found")
        self.vina_executable = str(Path(executable).resolve())
        result = subprocess.run([self.vina_executable, "--version"],
                                capture_output=True, text=True, check=True, timeout=30)
        self.vina_version = (result.stdout or result.stderr).strip()
        if not self.vina_version:
            raise RuntimeError("Vina did not report a version")
        self.logger.info("Vina: %s", self.vina_version)

    def get_proteins(self) -> List[Path]:
        """
        Return all receptor PDBQT files.
        
        Returns:
            List of receptor file paths
        """
        proteins = sorted(self.proteins_dir.glob("*.pdbqt"))
        
        if not proteins:
            self.logger.warning(f"No receptors found in: {self.proteins_dir}")
        
        return proteins
    
    def get_ligands(self) -> List[Path]:
        """
        Return all ligand PDBQT files.
        
        Returns:
            List of ligand file paths
        """
        ligands = sorted(self.ligands_dir.glob("*.pdbqt"))
        
        if not ligands:
            self.logger.warning(f"No ligands found in: {self.ligands_dir}")
        
        return ligands
    
    def get_config(self, protein_name: str) -> Optional[Path]:
        """
        Return the receptor configuration file.
        
        Args:
            protein_name: Receptor name (without extension)
            
        Returns:
            Configuration file path or None
        """
        try:
            return self.resolve_target(protein_name)['config_path']
        except FileNotFoundError:
            return None

    def get_targets(self):
        from src.docking.targets import get_targets
        return get_targets(self.project_root)

    def resolve_target(self, target_id):
        from src.docking.targets import resolve_target
        return resolve_target(self.project_root, target_id)
    
    def parse_config(self, config_path: Path, content=None) -> Dict[str, str]:
        params = {}
        text = Path(config_path).read_text(encoding="utf-8-sig") if content is None else content.decode('utf-8-sig')
        for raw in text.splitlines():
            line = raw.split("#", 1)[0].strip()
            if not line:
                continue
            if "=" not in line:
                raise ValueError(f"Invalid Vina config line: {raw}")
            key, value = (part.strip() for part in line.split("=", 1))
            if not key or not value or key in params:
                raise ValueError(f"Empty or duplicate Vina option: {key}")
            params[key] = value
        return params

    def _effective_options(self, config_path, exhaustiveness, config_bytes=None):
        params = self.parse_config(config_path, config_bytes)
        # The supplied receptor and exhaustiveness override the config values.
        params.pop("receptor", None)
        if exhaustiveness is not None:
            positive(exhaustiveness, 'exhaustiveness')
            params["exhaustiveness"] = str(exhaustiveness)
        params.setdefault('exhaustiveness', '8')
        params.setdefault("seed", str(self.seed))
        params.setdefault("cpu", str(self.cpu))
        params.setdefault("scoring", "vina")
        integers = {"seed", "cpu", "exhaustiveness", "num_modes", "max_evals", "verbosity"}
        floats = {"center_x", "center_y", "center_z", "size_x", "size_y", "size_z",
                  "energy_range", "min_rmsd", "spacing"}
        # Unknown options fail closed: e.g. --maps/--flex would add unhashed inputs.
        unknown = set(params) - integers - floats - {"scoring"}
        if unknown:
            raise ValueError(f"Unsupported config options: {sorted(unknown)}")
        for key in integers & params.keys():
            params[key] = str(int(params[key]))
        for key in floats & params.keys():
            number = float(params[key])
            if not math.isfinite(number):
                raise ValueError(f"Non-finite option: {key}")
            params[key] = format(number, ".17g")
        required = {"center_x", "center_y", "center_z", "size_x", "size_y", "size_z"}
        if not required <= params.keys():
            raise ValueError("Docking box requires center_x/y/z and size_x/y/z")
        if any(float(params[k]) <= 0 for k in ("size_x", "size_y", "size_z")):
            raise ValueError("Docking box sizes must be positive")
        if not -2147483648 <= int(params["seed"]) <= 2147483647:
            raise ValueError("Vina seed must fit a signed 32-bit integer")
        if int(params["seed"]) == 0:
            raise ValueError("Use a nonzero explicit seed; seed=0 requests an uncontrolled replicate")
        if int(params["cpu"]) < 1 or int(params["exhaustiveness"]) < 1:
            raise ValueError("cpu and exhaustiveness must be positive")
        if params["scoring"] not in ("vina", "vinardo"):
            raise ValueError("This cache integration supports rigid receptor Vina/Vinardo docking")
        requested_cpu = int(params["cpu"])
        effective_cpu = min(requested_cpu, self.cpu, self.cpu_pool.total)
        if effective_cpu != requested_cpu:
            self.logger.warning("Config cpu=%s limited to %s by application CPU settings",requested_cpu,effective_cpu)
        params["cpu"] = str(effective_cpu)
        return params

    def _count(self, field, error=None):
        with self._stats_lock:
            self.stats[field] = self.stats.get(field, 0) + 1
            if error is not None:
                self.stats['errors'].append(error)

    def run_single_docking(self, ligand_path: Path, protein_path: Path,
                           config_path: Path, exhaustiveness: int = 8,
                           force: bool = False) -> Optional[Dict]:
        ligand_path, protein_path = Path(ligand_path), Path(protein_path)
        ligand_name, protein_name = ligand_path.stem, protein_path.stem
        self._task_local.outcome = None
        try:
            validate_timeout(self.timeout)
            # Read once and execute on these snapshots, so the key describes the
            # exact input bytes even if someone edits an original during docking.
            ligand_bytes, protein_bytes = ligand_path.read_bytes(), protein_path.read_bytes()
            validate_pdbqt(ligand_bytes)
            validate_pdbqt(protein_bytes)
            config_bytes = Path(config_path).read_bytes()
            options = self._effective_options(config_path, exhaustiveness, config_bytes)
            executable_sha = digest(Path(self.vina_executable).read_bytes())
            spec = {"ligand_sha": digest(ligand_bytes), "receptor_sha": digest(protein_bytes),
                    "config_sha": digest(config_bytes),
                    "options": options, "engine_sha": executable_sha,
                    "engine_version": self.vina_version, "platform": platform.platform(),
                    "implementation_sha": digest(Path(__file__).read_bytes())}
            def compute():
                with tempfile.TemporaryDirectory(prefix="vina-") as directory:
                    temp = Path(directory)
                    ligand, receptor, pose = (temp / n for n in ("ligand.pdbqt", "receptor.pdbqt", "pose.pdbqt"))
                    ligand.write_bytes(ligand_bytes)
                    receptor.write_bytes(protein_bytes)
                    command = [self.vina_executable, "--ligand", str(ligand),
                               "--receptor", str(receptor), "--out", str(pose)]
                    for key, value in sorted(options.items()):
                        command.extend(["--" + key, value])
                    if digest(Path(self.vina_executable).read_bytes()) != executable_sha:
                        raise RuntimeError("Vina executable changed while preparing the task")
                    with self.cpu_pool.reserve(int(options['cpu'])):
                        self._count('executed')
                        process = subprocess.run(command, capture_output=True, text=True,
                                                 check=True, timeout=self.timeout,
                                                 env=child_environment(int(options['cpu'])))
                    artifact = pose.read_bytes()
                    validate_pdbqt(artifact)
                    parsed = self._parse_docking_output(pose, ligand_name, protein_name)
                    if parsed is None or not math.isfinite(parsed['affinity']):
                        raise ValueError("No finite Vina score in the produced PDBQT")
                    return {"affinity": parsed['affinity'], "mode": parsed['mode'],
                            "timestamp": parsed['timestamp'], "spec": spec,
                            "stdout": process.stdout, "stderr": process.stderr}, artifact
            entry = self.calculation_cache.get_or_compute("docking", spec, compute, force=force)
            output_file = self.results_dir / "by_id" / entry.key / (digest(entry.artifact) + ".pdbqt")
            if not output_file.exists() or digest(output_file.read_bytes()) != digest(entry.artifact):
                atomic_write(output_file, entry.artifact)
            inputs = {}
            for role, content in (("ligand", ligand_bytes), ("receptor", protein_bytes)):
                saved_input = self.project_root / "output" / "inputs" / (digest(content) + ".pdbqt")
                if not saved_input.exists() or digest(saved_input.read_bytes()) != digest(content):
                    atomic_write(saved_input, content)
                inputs[role] = str(saved_input)
            saved_config = self.project_root / 'output/inputs' / (digest(config_bytes) + '.config')
            if not saved_config.exists() or saved_config.read_bytes() != config_bytes:
                atomic_write(saved_config, config_bytes)
            inputs['config'] = str(saved_config)
            self._count('cached' if entry.hit else 'successful')
            self._task_local.outcome = dict(status='success', error='', cache_hit=entry.hit)
            profile = (Path(config_path).stem if Path(config_path).parent.resolve() ==
                       (self.configs_dir / protein_name).resolve() else 'default')
            target_id = protein_name + '@' + profile if profile != 'default' or Path(config_path).parent.resolve() == (self.configs_dir / protein_name).resolve() else protein_name
            return {**entry.payload, 'input_files': inputs, 'ligand': ligand_name, 'protein': protein_name,
                    'receptor': protein_name, 'config_id': profile, 'target_id': target_id,
                    'config_sha256': digest(config_bytes),
                    'evaluation_id': entry.key, 'artifact_sha': digest(entry.artifact),
                    'output_file': str(output_file), 'cache_hit': entry.hit}
        except Exception as error:
            status = 'timeout' if isinstance(error, subprocess.TimeoutExpired) else 'docking_failed'
            self._task_local.outcome = dict(status=status, error=str(error), error_type=type(error).__name__)
            if status == 'timeout':
                self._count('timeouts')
            self._count('failed', (ligand_name, protein_name, str(error)))
            self.logger.error("Docking %s / %s: %s", ligand_name, protein_name, error)
            return None

    def _run_task(self, ligand, receptor, config, exhaustiveness, force):
        self._task_local.outcome = None
        try:
            result = self.run_single_docking(ligand, receptor, config, exhaustiveness, force)
            outcome = self._task_local.outcome
            if outcome is None:
                outcome = dict(status='success' if result is not None else 'docking_failed',
                               error='' if result is not None else 'Docking returned no result')
            return result, outcome
        except Exception as error:
            self._count('failed', (Path(ligand).stem, Path(receptor).stem, str(error)))
            return None, dict(status='docking_failed', error=str(error), error_type=type(error).__name__)

    
    def _parse_docking_output(self, output_file: Path, ligand_name: str, protein_name: str) -> Optional[Dict]:
        """
        Parse the output PDBQT file to extract the docking score.
        
        Args:
            output_file: Output PDBQT file path
            ligand_name: Ligand name
            protein_name: Receptor name
            
        Returns:
            Result dictionary or None
        """
        try:
            with open(output_file, 'r') as f:
                for line in f:
                    if line.startswith('REMARK VINA RESULT:'):
                        parts = line.split()
                        if len(parts) >= 4:
                            try:
                                affinity = float(parts[3])
                                
                                return {
                                    'ligand': ligand_name,
                                    'protein': protein_name,
                                    'mode': 1,
                                    'affinity': affinity,
                                    'timestamp': datetime.now().isoformat()
                                }
                            except (ValueError, IndexError) as e:
                                self.logger.error(f"Failed to parse PDBQT: {e}")
        except Exception as e:
            self.logger.error(f"Failed to read {output_file}: {e}")
        
        return None
    
    def run_docking(self, ligands: Optional[List[str]] = None,
                    proteins: Optional[List[str]] = None, exhaustiveness: int = 8,
                    num_workers: int = 4, force: bool = False, *,
                    ligand_paths: Optional[Dict[str, Path]] = None) -> Dict:
        """Batch API preserved; explicit paths avoid mutable generation-name aliases.

        None means all available inputs; an empty list means no inputs.
        One instance runs one batch at a time. Task-level work is parallel.
        """
        positive(num_workers,"num_workers")
        effective_workers=min(num_workers,self.cpu_pool.total)
        self.logger.info("CPU budget=%s; requested jobs=%s; worker cap=%s; max CPU/job=%s",
                         self.cpu_pool.total,num_workers,effective_workers,self.cpu)
        started = time.monotonic()
        self.stats = {'total_dockings': 0, 'successful': 0, 'failed': 0,
                      'cached': 0, 'executed': 0, 'errors': [], 'elapsed_time': 0,
                      'cpu_budget': self.cpu_pool.total, 'cpu_per_job_cap': self.cpu,
                      'requested_workers': num_workers, 'effective_workers': effective_workers}
        self.docking_results = {}
        self.task_outcomes = {}
        targets = [t['id'] for t in self.get_targets()] if proteins is None else list(dict.fromkeys(proteins))
        if ligand_paths is None:
            available_ligands = {p.stem: p for p in self.get_ligands()}
        else:
            available_ligands = {name: Path(path) for name, path in ligand_paths.items()}
        labels = list(available_ligands) if ligands is None else list(dict.fromkeys(ligands))
        self.stats['total_dockings'] = len(targets) * len(labels)
        tasks = []
        for protein in targets:
            try:
                target = self.resolve_target(protein)
                config, target_error = target['config_path'], None
            except (ValueError, OSError) as error:
                target, config, target_error = None, None, str(error)
            for label in labels:
                if config is None or label not in available_ligands:
                    error = target_error or 'Missing ligand input'
                    self._count('failed', (label, protein, error))
                    self.task_outcomes.setdefault(label, {})[protein] = dict(status='docking_failed', error=error)
                    continue
                tasks.append((label, protein, available_ligands[label], target['receptor_path'], config, target))
        from src.ui.progress import WorkProgress
        with WorkProgress("Docking", self.stats['total_dockings']) as progress:
            progress.update(completed=self.stats['failed'])
            with ThreadPoolExecutor(max_workers=effective_workers) as executor:
                futures = {executor.submit(self._run_task, lig, prot, conf, exhaustiveness, force):
                           (label, protein, target) for label, protein, lig, prot, conf, target in tasks}
                for future in as_completed(futures):
                    label, protein, target = futures[future]
                    try:
                        result, outcome = future.result()
                        self.task_outcomes.setdefault(label, {})[protein] = outcome
                        if result is not None:
                            result = {**result, 'ligand': label, 'protein': protein,
                                      'target_id': protein, 'receptor': target['receptor'],
                                      'config_id': target['config_id']}
                            self.docking_results.setdefault(label, {})[protein] = result
                    except Exception as error:
                        self._count('failed', (label, protein, str(error)))
                        self.task_outcomes.setdefault(label, {})[protein] = dict(status='docking_failed', error=str(error))
                    finally:
                        progress.advance()
                        progress.update(description=f"Docking: cached {self.stats['cached']}; failed {self.stats['failed']}")
        self.stats['elapsed_time'] = time.monotonic() - started
        self._save_results_json()
        return self.docking_results

    def _save_results_json(self):
        # Preserve an immutable batch record; docking_results.json is a latest-result
        # export for existing callers, never an input to the calculation cache.
        self.last_batch_dir = self.project_root / "output" / "runs" / ("docking-" + uuid.uuid4().hex)
        atomic_json(self.last_batch_dir / "results.json", self.docking_results)
        atomic_json(self.last_batch_dir / "statistics.json", self.stats)
        atomic_json(self.last_batch_dir / "task_outcomes.json", self.task_outcomes)
        atomic_json(self.cache_dir / "docking_results.json", self.docking_results)

    def load_results_json(self) -> Dict:
        """
        Load docking results from a JSON file.
        
        Returns:
            Result dictionary
        """
        json_file = self.cache_dir / "docking_results.json"
        
        if not json_file.exists():
            self.logger.warning("Results file not found")
            return {}
        
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                results = json.load(f)
            
            self.docking_results = results
            self.logger.info(f"Loaded results for {len(results)} ligands")
            return results
        
        except Exception as e:
            self.logger.error(f"Failed to load JSON: {e}")
            return {}
    
    def get_top_ligands(self, protein: str, n: int = 10) -> List[Tuple[str, float]]:
        """
        Return the top N ligands for a receptor ranked by docking score.
        
        Args:
            protein: Receptor name
            n: Number of ligands
            
        Returns:
            List of (ligand_name, affinity) tuples
        """
        ligands_affinities = []
        
        for ligand_name, proteins_data in self.docking_results.items():
            if protein in proteins_data:
                affinity = proteins_data[protein]['affinity']
                ligands_affinities.append((ligand_name, affinity))
        
        # Sort by docking score (lower is better)
        ligands_affinities.sort(key=lambda x: x[1])
        
        return ligands_affinities[:n]


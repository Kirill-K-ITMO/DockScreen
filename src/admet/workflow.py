"""Public CLI integration for local post-screening enrichment."""
from pathlib import Path
import hashlib
import json
import uuid
from .pipeline import enrich_run
from src.core.calculation_cache import atomic_json, atomic_write


def completed_run(root, path):
    root = Path(root).resolve()
    chosen = Path(path)
    if not chosen.is_absolute():
        chosen = root / chosen
    chosen = chosen.resolve()
    runs = root / 'output/runs'
    if chosen == runs or not chosen.is_relative_to(runs):
        raise ValueError('Choose a screening run inside this project output/runs')
    if not chosen.is_dir() or any(not (chosen / name).is_file() for name in
                                  ('preparation.json', 'results.json', 'summary.json')):
        raise ValueError('Choose a completed screening run containing preparation.json, results.json and summary.json')
    return chosen


def _legacy_snapshot(run):
    """Recover only identities actually saved by the interactive menu."""
    raw = {name: (run / name).read_bytes() for name in
           ('results.json', 'task_outcomes.json', 'statistics.json') if (run / name).is_file()}
    results = json.loads(raw['results.json'].decode('utf-8'))
    outcomes = json.loads(raw.get('task_outcomes.json', b'{}').decode('utf-8'))
    if not isinstance(results, dict) or not results or not isinstance(outcomes, dict):
        raise ValueError('No recoverable interactive docking rows')
    if set(outcomes) - set(results):
        raise ValueError('Some failed rows have no saved SMILES; cannot reconstruct this run without losing rows')
    rows, seen, targets = [], set(), set()
    for label, records in results.items():
        if not isinstance(records, dict) or not records:
            raise ValueError('Missing interactive result metadata')
        identities = []
        for target, record in records.items():
            if not isinstance(record, dict): raise ValueError('Invalid interactive result')
            identity = (record.get('selection_row_id'), record.get('input_name'), record.get('smiles'))
            i, name, smiles = identity
            if type(i) is not int or i < 1 or not isinstance(name, str) or not isinstance(smiles, str) or not smiles:
                raise ValueError('Interactive results do not contain saved row IDs, names and SMILES')
            identities.append(identity)
            targets.add(target)
        if len(set(identities)) != 1 or identities[0][0] in seen:
            raise ValueError('Conflicting or duplicate interactive row identities')
        i, name, smiles = identities[0]
        seen.add(i)
        rows.append({'row_id': i, 'label': label, 'name': name, 'smiles': smiles,
                     'status': 'prepared', 'identity_source': 'saved_interactive_results'})
    for record in outcomes.values():
        if not isinstance(record, dict): raise ValueError('Invalid interactive outcomes')
        targets.update(record)
    # Old interactive menus did not retain preparation-failed rows. Fail closed
    # if row numbers reveal a gap instead of pretending the library was complete.
    if seen != set(range(1, max(seen) + 1)):
        raise ValueError('Interactive row IDs have gaps; original failed input rows are unavailable')
    return raw, sorted(rows, key=lambda r: r['row_id']), sorted(targets), results


def available_runs(root):
    """List completed CLI/menu runs, excluding the pre-enrichment raw duplicate."""
    root = Path(root).resolve()
    found = []
    for run in (root / 'output/runs').iterdir() if (root / 'output/runs').is_dir() else []:
        if not run.is_dir() or not run.resolve().is_relative_to(root / 'output/runs'):
            continue
        if all((run / n).is_file() for n in ('preparation.json', 'summary.json', 'results.json')):
            found.append(run)
        elif run.name.startswith('docking-') and (run / 'results.json').is_file():
            try:
                _legacy_snapshot(run)
            except (ValueError, KeyError, TypeError, OSError):
                continue
            found.append(run)
    return sorted(found, key=lambda p: ((p / 'results.json').stat().st_mtime_ns, p.name), reverse=True)


def prepare_run(root, path):
    """Adapt a legacy menu run in a NEW directory, never recalculate docking."""
    root = Path(root).resolve()
    run = Path(path)
    if not run.is_absolute(): run = root / run
    run = run.resolve()
    if run == root / 'output/runs' or not run.is_relative_to(root / 'output/runs'):
        raise ValueError('Choose a run inside this project output/runs')
    if all((run / n).is_file() for n in ('preparation.json', 'summary.json', 'results.json')):
        return completed_run(root, run)
    if not run.name.startswith('docking-'):
        return completed_run(root, run)
    raw, rows, targets, results = _legacy_snapshot(run)
    destination = root / 'output/runs' / ('screening-import-' + uuid.uuid4().hex)
    destination.mkdir()
    for name, content in raw.items():
        atomic_write(destination / name, content)
    atomic_json(destination / 'preparation.json', rows)
    atomic_json(destination / 'summary.json', {
        'kind': 'imported_interactive_docking', 'run_dir': str(destination),
        'source_run': str(run), 'source_sha256': {n: hashlib.sha256(b).hexdigest() for n, b in raw.items()},
        'receptors': targets, 'input_rows': len(rows),
        'successful_pairs': sum(len(v) for v in results.values()),
        'failed_pairs': len(rows) * len(targets) - sum(len(v) for v in results.values()),
        'warnings': ['Recovered from saved menu result identities; no new docking or preparation.',
                     'Legacy menu saved canonical SMILES; original raw CSV bytes and preparation-failed rows were not retained.'],
    })
    return destination


__all__ = ['enrich_run', 'completed_run', 'available_runs', 'prepare_run']

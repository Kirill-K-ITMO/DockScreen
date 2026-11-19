"""Per-target computational shortlists; no measured-affinity claims."""
import hashlib
from datetime import datetime, timezone
import uuid
from src.reporting.document_names import document_stem
import math
from pathlib import Path
import re

from src.reporting.csv_safety import write_csv, notes_path
from src.docking.affinity import AffinityCalculator


def export_hits(results, output_dir: Path, *, targets=None):
    """Export four-column CSVs and scientific/provenance notes for each target."""
    grouped = {target: [] for target in (targets or [])}
    for label, target_results in results.items():
        for target, data in target_results.items():
            if data.get('target_id', target) != target:
                raise ValueError(f'Target metadata disagrees with result key: {target}')
            grouped.setdefault(target, []).append((label, data))
    calculator = AffinityCalculator(298.15)
    exports = {}
    pending = []
    for target, entries in grouped.items():
        entries = sorted(entries, key=lambda item: (
            item[1].get('selection_row_id') if isinstance(item[1].get('selection_row_id'), int) else 0,
            str(item[0])))
        if not isinstance(target, str) or not target:
            raise ValueError('Target identifiers must be nonempty strings')
        scorings = {data.get('spec', {}).get('options', {}).get('scoring', 'vina')
                    for _, data in entries}
        if len(scorings) > 1:
            raise ValueError(f'Mixed scoring functions for target {target}')
        rows, provenance, excluded = [], [], []
        for label, data in entries:
            score = data.get('affinity')
            provenance.append({'label': label, **{key: data[key] for key in (
                'evaluation_id', 'preparation_id', 'molecule_id', 'config_sha256',
                'target_id', 'receptor', 'config_id', 'spec') if key in data}})
            if data.get('status', 'success') != 'success':
                excluded.append({'label': label, 'reason': 'unsuccessful result'})
                continue
            try:
                if isinstance(score, bool) or not isinstance(score, (float, int)):
                    raise ValueError('missing or nonnumeric score')
                ki = calculator.calculate_ki(score)
                if ki is None or not math.isfinite(ki) or ki <= 0:
                    raise ValueError('Ki outside representable positive range')
            except (ValueError, OverflowError, TypeError) as error:
                excluded.append({'label': label, 'reason': str(error)})
                continue
            if ki <= 1e-6 or math.isclose(ki, 1e-6, rel_tol=1e-14, abs_tol=0):
                rows.append([data.get('input_name', label), data.get('smiles', ''), score, ki * 1e6])
        slug = re.sub(r'[^A-Za-z0-9_-]+', '_', target).strip('_')[:48] or 'target'
        stem = document_stem(kind='HITS',target=target,identity=uuid.uuid4().hex,created_utc=datetime.now(timezone.utc).isoformat())+'__table'
        table = Path(output_dir) / (stem + '.csv')
        notes = notes_path(table)
        note = dict(kind='computational_shortlist', target_id=target,
            interpretation='Score-derived estimates, not experimental affinity or confirmed biological hits.',
            columns={'name': 'input label', 'smiles': 'input SMILES',
                     'dG': 'docking score in kcal/mol, lower is better', 'Ki': 'score-derived estimate in micromol/L (uM)'},
            temperature_K=298.15, threshold_Ki_M=1e-6, boundary_relative_tolerance=1e-14,
            formula='Ki_M = exp(dG_kcal_mol * 4184 / (8.314463 * 298.15)); Ki_uM = Ki_M * 1e6',
            selection='Successful finite scores with representable positive Ki <= 1 uM, before rounding.',
            scoring=next(iter(scorings), None), count=len(rows),
            provenance=provenance, excluded=excluded)
        pending.append((table, rows, note))
        exports[target] = dict(csv=str(table), notes=str(notes), count=len(rows))
    # Validate every target before publishing any file (including mixed scoring).
    for table, rows, note in pending:
        write_csv(table, ['name', 'smiles', 'dG', 'Ki'], rows,
                  text_columns=['name', 'smiles'], notes=note)
    return exports

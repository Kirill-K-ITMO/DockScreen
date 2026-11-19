"""Validated row-identity join for ordinary docking reports with optional ADMET."""
import json
from pathlib import Path

from src.reporting.combined import build_combined_data

NOTE = ('ADMET classification outputs are model scores, not calibrated clinical risk probabilities. '
        'Bioavailability_Ma is not percent bioavailability. Individual uncertainty is not estimated. '
        'Docking scores are not experimental activity. ADMET is calculated once per structure, independently of receptor.')


def report_context(root, run_dir):
    run_dir = Path(run_dir)
    if not (run_dir / 'admet.json').is_file(): return None
    # This verifies source hashes and raw row IDs/names/SMILES before any join.
    data = build_combined_data(root, run_dir)
    return {'endpoints': {k:v for k,v in data['endpoints'].items() if k != 'docking_score'},
            'metadata': data['admet_metadata'], 'source_sha256': data['source_sha256'],
            'by_label': {r['label']: {'row_id': r['row_id'], 'name': r['name'], 'smiles': r['smiles'],
                'status': r['admet_status'], 'error': r.get('admet_error'), 'values': r['values']}
                for r in data['rows']}}


def validate_join(results, context):
    if context is None: return
    for label, records in results.items():
        row = context['by_label'].get(label)
        if row is None: raise ValueError('ADMET report is missing a docking row identity')
        for record in records.values():
            if (record.get('selection_row_id') != row['row_id'] or record.get('input_name') != row['name']
                    or record.get('smiles') != row['smiles']):
                raise ValueError('ADMET report row identity/SMILES mismatch')


def generate_run_reports(root, run_dir):
    from src.docking.affinity import AffinityCalculator
    from src.reporting.docking import ReportGenerator
    run_dir = Path(run_dir)
    results = json.loads((run_dir / 'results.json').read_text(encoding='utf-8'))
    enriched = AffinityCalculator().process_docking_results(results)
    return ReportGenerator(root).generate_reports(enriched, title='Docking + ADMET',
        admet=report_context(root, run_dir), output_dir=run_dir / 'reports')

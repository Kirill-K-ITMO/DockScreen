"""Enrich an existing screening run without starting or importing docking engines."""
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import tempfile
import time

from src.core.calculation_cache import atomic_json, fingerprint, molecule_identity
from src.reporting.csv_safety import write_csv

POLICY = {
    'version': 1, 'canonicalization': 'RDKit canonical isomeric SMILES; atom-map labels removed',
    'salts': 'disconnected graphs rejected, no fragment stripping',
    'protonation': 'preserved; no adjustment', 'tautomers': 'preserved; no enumeration',
    'stereochemistry': 'specified stereochemistry preserved; unspecified not enumerated',
    'isotopes': 'preserved', 'original_smiles': 'retained unchanged in each row',
}


def _finite(value):
    return isinstance(value, (float, int)) and not isinstance(value, bool) and math.isfinite(value)


def _invoke(python, request, timeout, work_dir):
    """File responses plus sanitized progress; worker stdout stays in its log."""
    worker = Path(__file__).with_name('worker.py')
    callback=request.get('_progress_callback')
    payload={key:value for key,value in request.items() if key!='_progress_callback'}
    with tempfile.TemporaryDirectory(prefix='admet-', dir=work_dir) as folder:
        req, resp, log = (Path(folder) / name for name in ('request.json', 'response.json', 'worker.log'))
        status=Path(folder)/'progress.json'
        req.write_text(json.dumps(payload, ensure_ascii=False, allow_nan=False), encoding='utf-8')
        env = dict(os.environ, CUDA_VISIBLE_DEVICES='', OMP_NUM_THREADS='1', MKL_NUM_THREADS='1',
                   OPENBLAS_NUM_THREADS='1', PYTHONUTF8='1', PYTHONDONTWRITEBYTECODE='1',
                   MPLCONFIGDIR=str(Path(folder) / 'matplotlib'), TEMP=str(folder), TMP=str(folder))
        last_event=None
        last_prediction_done=-1
        def notify():
            nonlocal last_event,last_prediction_done
            if callback is None or not status.is_file(): return
            try:
                if status.stat().st_size>1024: return
                event=json.loads(status.read_text(encoding='utf-8'))
            except (OSError,ValueError): return
            if not isinstance(event,dict) or event.get('stage') not in ('checking_environment','loading_models','predicting','complete'): return
            expected=len(payload.get('smiles',[]))
            completed,total,failed=event.get('completed'),event.get('total'),event.get('failed',0)
            if total is not None and (type(total) is not int or total!=expected): return
            if completed is not None and (type(completed) is not int or completed<0 or (total is not None and completed>total)): return
            if type(failed) is not int or failed<0 or (total is not None and failed>total): return
            if event['stage'] in ('predicting','complete') and (type(completed) is not int or total!=expected): return
            if event['stage'] in ('predicting','complete') and completed is not None:
                if completed<last_prediction_done:return
                last_prediction_done=completed
            safe={'stage':event['stage'],'completed':completed,'total':total,'failed':failed}
            if safe!=last_event:
                callback(safe);last_event=safe
        try:
            with log.open('wb') as stream:
                process=subprocess.Popen([str(python), '-B', str(worker), str(req), str(resp)],
                    stdout=stream, stderr=subprocess.STDOUT, env=env,
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                started=time.monotonic()
                try:
                    while process.poll() is None:
                        notify()
                        if time.monotonic()-started>timeout:
                            raise RuntimeError(f'ADMET worker timed out after {timeout:g} seconds; input files retained')
                        time.sleep(.1)
                    notify()
                except BaseException:
                    if process.poll() is None: process.kill()
                    process.wait()
                    raise
                process.wait()
        except FileNotFoundError as error:
            raise RuntimeError('ADMET Python is unavailable. Run python scripts/install.py --admet and select .venv-admet Python.') from error
        if process.returncode != 0 or not resp.is_file():
            detail = log.read_text(encoding='utf-8', errors='replace')[-4000:]
            raise RuntimeError(f'ADMET worker failed (exit {process.returncode}): {detail}')
        document = json.loads(resp.read_text(encoding='utf-8'))
        if document.get('error'):
            raise RuntimeError('ADMET environment/model error: ' + str(document['error']) +
                               '. Use the separate environment from python scripts/install.py --admet.')
        return document


def _selected_rows(rows, results, top_n, target):
    if top_n is None:
        return {row['row_id'] for row in rows}
    if type(top_n) is not int or top_n <= 0:
        raise ValueError('top_n must be a positive integer')
    if not target:
        raise ValueError('top_n requires an explicit receptor/profile target')
    scores = []
    protocols = set()
    for row in rows:
        data = results.get(row.get('label', f"row_{row['row_id']:06d}"), {}).get(target)
        if not data or not _finite(data.get('affinity')):
            continue
        # Match the report: compare all recorded protocol provenance, including
        # receptor/config/engine hashes; only ligand identity varies per candidate.
        spec = dict(data.get('spec', {}))
        spec.pop('ligand_sha', None)
        if not spec:
            spec = {'legacy_protocol': 'unknown; original protocol not recorded',
                    'scoring': data.get('scoring', 'unknown')}
        protocols.add(json.dumps(spec, ensure_ascii=False, sort_keys=True, allow_nan=False))
        scores.append((data['affinity'], row['row_id']))
    known_targets = {key for values in results.values() for key in values}
    if target not in known_targets:
        raise ValueError(f'No successful docking results for target {target!r}')
    if len(protocols) > 1:
        raise ValueError('Top-N selection mixes protocols; choose a homogeneous screening run')
    return {row_id for _, row_id in sorted(scores)[:top_n]}


def _save(run_dir, document):
    atomic_json(run_dir / 'admet.json', document)
    fields = ['row_id', 'name', 'smiles', 'structure_id', 'canonical_smiles', 'status', 'error', 'cache_hit']
    endpoints = sorted(document['endpoints'])
    records = [{**{key: row.get(key, '') for key in fields},
                **{key: row.get('values', {}).get(key) for key in endpoints}} for row in document['rows']]
    write_csv(run_dir / 'admet.csv', fields + endpoints, records,
        text_columns=[key for key in fields if key not in ('row_id', 'cache_hit')],
        notes={'kind': 'admet_predictions', 'metadata': document['metadata'], 'endpoints': document['endpoints']})


    # Human-facing dated copies; stable admet.json/csv remain the scientific interface.
    from src.reporting.document_names import document_stem
    import uuid
    stem=document_stem(kind='ADMET',target='molecular-properties',identity=uuid.uuid4().hex,
                       created_utc=datetime.now(timezone.utc).isoformat())
    reports=run_dir/'reports'
    reports.mkdir(exist_ok=True)
    for source, name in [(run_dir/'admet.json',stem+'__predictions.json'),
                         (run_dir/'admet.csv',stem+'__predictions.csv'),
                         (run_dir/'admet.csv.notes.json',stem+'__predictions.csv.notes.json')]:
        with (reports/name).open('xb') as output:
            with source.open('rb') as original:
                import shutil
                shutil.copyfileobj(original,output)


def _enrich_run(root, run_dir, *, python_executable=None, batch_size=16, timeout=600,
               top_n=None, target=None, progress=None):
    """Append independent ADMET artifacts. Returns paths/counts; errors stay in ADMET.

    timeout applies to each worker invocation (probe, then prediction of all missing
    structures). No molecular structures are sent to an external service.
    """
    root = Path(root).resolve()
    run_dir = Path(run_dir)
    if not run_dir.is_absolute():
        run_dir = root / run_dir
    run_dir = run_dir.resolve()
    if run_dir == root / 'output/runs' or not run_dir.is_relative_to(root / 'output/runs'):
        raise ValueError('Choose a screening run inside this project output/runs')
    if type(batch_size) is not int or not 1 <= batch_size <= 256:
        raise ValueError('ADMET batch_size must be in 1..256')
    if not _finite(timeout) or timeout <= 0:
        raise ValueError('ADMET timeout must be finite and positive')
    rows = json.loads((run_dir / 'preparation.json').read_text(encoding='utf-8'))
    results = json.loads((run_dir / 'results.json').read_text(encoding='utf-8'))
    if not isinstance(rows, list) or any(not isinstance(row, dict) or
        type(row.get('row_id')) is not int or not isinstance(row.get('smiles'), str) or
        not isinstance(row.get('name'), str) for row in rows):
        raise ValueError('Invalid screening preparation.json')
    if len({row['row_id'] for row in rows}) != len(rows):
        raise ValueError('Screening row IDs must be unique')
    selected = _selected_rows(rows, results, top_n, target)
    python = python_executable or root / '.venv-admet' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    work_dir = root / '.calculation_cache/admet-v1'
    work_dir.mkdir(parents=True, exist_ok=True)
    from rdkit import rdBase
    document = {'schema_version': 1, 'metadata': {
        'created_utc': datetime.now(timezone.utc).isoformat(), 'structure_policy': POLICY,
        'input_rdkit': rdBase.rdkitVersion, 'input_identity_policy_version': 2,
        'selection': {'mode': 'all' if top_n is None else 'top_n', 'top_n': top_n, 'target': target},
        'input_sha256': {name: hashlib.sha256((run_dir / name).read_bytes()).hexdigest()
                         for name in ('preparation.json', 'results.json', 'summary.json') if (run_dir / name).is_file()},
        'batch_size': batch_size, 'timeout_seconds_per_worker': timeout,
        'uncertainty': 'not estimated', 'network': 'no structures submitted; local inference only'},
        'endpoints': {}, 'rows': []}
    progress.update('validation',completed=0,total=len(rows))
    groups = {}
    from src.preparation.validation import validated_molecule
    for original in rows:
        row = {key: original[key] for key in ('row_id', 'name', 'smiles')}
        row.update(status='not_selected', values={}, cache_hit=False)
        document['rows'].append(row)
        if row['row_id'] not in selected:
            continue
        try:
            validated_molecule(row['smiles'])
            canonical, structure_id = molecule_identity(row['smiles'])
            row.update(structure_id=structure_id, canonical_smiles=canonical, status='pending')
            groups.setdefault(canonical, []).append(row)
        except Exception as error:
            row.update(status='invalid_structure', error=str(error))
    invalid_count=sum(r['status']=='invalid_structure' for r in document['rows'])
    progress.update('validation',completed=len(rows),total=len(rows),failed=invalid_count)
    fatal_error = None
    cache_hits = 0
    predicted = 0
    if groups:
        try:
            progress.update('checking_environment')
            provenance = _invoke(python, {'action': 'probe', '_progress_callback': lambda event: progress.update(event['stage'])}, timeout, work_dir)
            if not isinstance(provenance.get('metadata'), dict) or not isinstance(provenance.get('endpoints'), dict):
                raise RuntimeError('Invalid ADMET worker provenance')
            document['metadata'].update(provenance['metadata'])
            document['endpoints'] = provenance['endpoints']
            missing, keys = [], {}
            progress.update('cache',completed=0,total=len(groups))
            for ordinal,(canonical, linked) in enumerate(groups.items(),1):
                key = fingerprint({'structure_id': linked[0]['structure_id'], 'policy': POLICY,
                                   'provenance': provenance})
                keys[canonical] = key
                cache = work_dir / (key + '.json')
                cached = None
                try:
                    cached = json.loads(cache.read_text(encoding='utf-8'))
                    if (not isinstance(cached, dict) or cached.get('key') != key or not _valid_prediction(cached.get('prediction'))
                            or cached.get('prediction_sha256') != fingerprint(cached['prediction'])):
                        cached = None
                except (OSError, ValueError, TypeError):
                    pass
                if cached:
                    cache_hits += 1
                    for row in linked:
                        row.update(cached['prediction'], cache_hit=True)
                else:
                    missing.append(canonical)
                progress.update('cache',completed=ordinal,total=len(groups),cache_hits=cache_hits)
            if missing:
                def worker_progress(event):
                    if event['stage'] in ('predicting','complete') and event['completed'] is not None:
                        progress.update('predicting',completed=cache_hits+event['completed'],total=len(groups),cache_hits=cache_hits,failed=invalid_count+event['failed'])
                    else: progress.update(event['stage'],cache_hits=cache_hits)
                progress.update('checking_environment',cache_hits=cache_hits)
                response = _invoke(python, {'_progress_callback':worker_progress,'action': 'predict', 'smiles': missing,
                    'batch_size': batch_size, 'provenance': provenance}, timeout, work_dir)
                if any(response.get(k) != provenance[k] for k in ('metadata', 'endpoints')):
                    raise RuntimeError('ADMET prediction provenance differs from probe')
                predictions = response.get('predictions', {})
                for ordinal,canonical in enumerate(missing,1):
                    prediction = predictions.get(canonical)
                    if not _valid_prediction(prediction):
                        prediction = {'status': 'prediction_failed', 'values': {},
                                      'error': (prediction or {}).get('error', 'Missing or non-finite ADMET output')}
                    else:
                        predicted += 1
                        atomic_json(work_dir / (keys[canonical] + '.json'),
                                    {'key': keys[canonical], 'prediction': prediction,
                                     'prediction_sha256': fingerprint(prediction)})
                    for row in groups[canonical]:
                        row.update(prediction)
                progress.update('predicting',completed=len(groups),total=len(groups),cache_hits=cache_hits)
        except Exception as error:
            fatal_error = str(error)
            for linked in groups.values():
                for row in linked:
                    if row['status'] == 'pending':
                        row.update(status='prediction_failed', error=fatal_error)
    document['metadata']['error'] = fatal_error
    document['metadata']['counts'] = {'rows': len(rows), 'selected_rows': len(selected),
        'unique_structures': len(groups), 'cache_hits': cache_hits, 'new_predictions': predicted,
        'successful_rows': sum(row['status'] == 'success' for row in document['rows']),
        'failed': sum(row['status'] in ('prediction_failed', 'invalid_structure') for row in document['rows'])}
    counts=document['metadata']['counts']
    progress.update('saving',completed=len(groups),total=len(groups),cache_hits=cache_hits,failed=counts['failed'])
    _save(run_dir, document)
    progress.update('failed' if fatal_error or counts['failed'] else 'complete',completed=len(groups),total=len(groups),cache_hits=cache_hits,failed=counts['failed'])
    return {'json': str(run_dir / 'admet.json'), 'csv': str(run_dir / 'admet.csv'),
            **document['metadata']['counts'], 'error': fatal_error}


def _valid_prediction(prediction):
    if not isinstance(prediction, dict) or prediction.get('status') != 'success':
        return False
    values = prediction.get('values')
    return isinstance(values, dict) and bool(values) and any(_finite(v) for v in values.values()) and all(
        isinstance(k, str) and (v is None or _finite(v)) for k, v in values.items())


def enrich_run(root, run_dir, *, python_executable=None, batch_size=16, timeout=600,
               top_n=None, target=None):
    from src.ui.admet_progress import AdmetProgress
    with AdmetProgress() as progress:
        return _enrich_run(root, run_dir, python_executable=python_executable,
            batch_size=batch_size,timeout=timeout,top_n=top_n,target=target,progress=progress)

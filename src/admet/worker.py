"""Standalone worker. Only this process imports ADMET-AI and PyTorch.

File protocol avoids stdout interference from Lightning/tqdm and supports Windows.
"""
import csv
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import sys


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def probe():
    # Do not initialize/load the model for a cache-only request.
    from admet_ai.constants import DEFAULT_MODELS_DIR, DEFAULT_ADMET_PATH
    import importlib.util
    from rdkit import rdBase
    files = {p.relative_to(DEFAULT_MODELS_DIR).as_posix(): sha(p)
             for p in sorted(Path(DEFAULT_MODELS_DIR).rglob('*')) if p.is_file()}
    if not any(name.endswith('.pt') for name in files):
        raise RuntimeError('ADMET-AI model weights are absent')
    code_files = {}
    for package in ('admet_ai', 'chemprop'):
        package_dir = Path(importlib.util.find_spec(package).origin).parent
        code_files.update({package + '/' + p.relative_to(package_dir).as_posix(): sha(p)
                           for p in sorted(package_dir.rglob('*.py'))})
    endpoints = {}
    with Path(DEFAULT_ADMET_PATH).open(encoding='utf-8-sig', newline='') as stream:
        for row in csv.DictReader(stream):
            endpoint = dict(row)
            endpoint['type'] = row['task_type']
            endpoint['uncertainty'] = 'not estimated'
            endpoint['warnings'] = []
            if row['task_type'] == 'classification':
                endpoint['warnings'].append('Model class score, not a calibrated clinical risk probability or percentage.')
            if row['id'] == 'Bioavailability_Ma':
                endpoint['warnings'].append('Classification score, not percent oral bioavailability.')
            if row.get('R^2') and float(row['R^2']) < 0:
                endpoint['warnings'].append('Published metadata has negative R²: weak predictive performance on that evaluation.')
            if row['category'] == 'Physicochemical':
                endpoint['type'] = 'descriptor'
            endpoints[row['id']] = endpoint
    return {'metadata': {
        'package': 'admet-ai', 'version': importlib.metadata.version('admet-ai'),
        'worker_rdkit': rdBase.rdkitVersion,
        'dependencies': dict(sorted((dist.metadata['Name'], dist.version)
                                    for dist in importlib.metadata.distributions() if dist.metadata.get('Name'))),
        'inference_code_sha256': code_files,
        'model_files_sha256': files, 'endpoint_metadata_sha256': sha(DEFAULT_ADMET_PATH),
        'worker_sha256': sha(__file__), 'device': 'cpu', 'num_workers': 0,
        'include_physchem': True, 'drugbank_reference': None,
        'uncertainty': 'not estimated',
        'warning': 'ADMET-AI v2 results can differ from the v1 paper/web application. Ensemble means are model estimates, not molecule-specific accuracy.'},
        'endpoints': endpoints}


def write_progress(path, stage, *, completed=None, total=None, failed=0):
    if path is None: return
    document={'stage':stage,'completed':completed,'total':total,'failed':failed}
    temporary=path.with_suffix('.tmp')
    temporary.write_text(json.dumps(document,allow_nan=False),encoding='utf-8')
    os.replace(temporary,path)


def predict(request, provenance, progress_path=None):
    write_progress(progress_path,'loading_models')
    import torch
    torch.set_num_threads(1)
    from admet_ai import ADMETModel
    model = ADMETModel(drugbank_path=None, num_workers=0)
    model.device = 'cpu'
    output = {}
    smiles = request['smiles']
    size = request['batch_size']
    failures=0
    write_progress(progress_path,'predicting',completed=0,total=len(smiles))
    for offset in range(0, len(smiles), size):
        batch = smiles[offset:offset + size]
        try:
            frame = model.predict(smiles=batch)
            if not frame.index.is_unique:
                raise RuntimeError('ADMET output has duplicate SMILES indices')
            for item in batch:
                if item not in frame.index:
                    output[item] = {'status': 'prediction_failed', 'error': 'ADMET omitted this SMILES', 'values': {}}
                    continue
                values = {}
                for key, value in frame.loc[item].items():
                    try:
                        number = float(value)
                    except (ValueError, TypeError):
                        number = float('nan')
                    values[str(key)] = number if math.isfinite(number) else None
                output[item] = {'status': 'success' if any(v is not None for v in values.values()) else 'prediction_failed',
                                'values': values}
        except Exception as error:
            for item in batch:
                output[item] = {'status': 'prediction_failed', 'error': str(error), 'values': {}}

        failures+=sum(output[item]['status']!='success' for item in batch)
        write_progress(progress_path,'predicting',completed=offset+len(batch),total=len(smiles),failed=failures)
    write_progress(progress_path,'complete',completed=len(smiles),total=len(smiles),failed=failures)
    return {**provenance, 'predictions': output}


def main():
    request_path, response_path = map(Path, sys.argv[1:3])
    request = json.loads(request_path.read_text(encoding='utf-8'))
    progress_path=request_path.parent/'progress.json'
    write_progress(progress_path,'checking_environment')
    try:
        provenance = probe()
        if provenance['metadata']['version'] != '2.0.1':
            raise RuntimeError('This integration requires admet-ai==2.0.1; other versions need verification')
        if request.get('action') == 'predict':
            expected = request['provenance']
            if provenance != expected:
                raise RuntimeError('ADMET environment/model provenance changed since probe; rerun enrichment')
            result = predict(request, provenance, progress_path)
        else:
            result = provenance
    except Exception as error:
        result = {'error': f'{type(error).__name__}: {error}'}
    response_path.write_text(json.dumps(result, ensure_ascii=False, allow_nan=False), encoding='utf-8')


if __name__ == '__main__':
    # Hide CUDA devices before importing torch, even on a GPU-capable machine.
    os.environ['CUDA_VISIBLE_DEVICES'] = ''
    main()

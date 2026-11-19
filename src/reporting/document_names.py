"""Readable, collision-safe copies of important result documents.

Canonical files keep their stable machine-facing names. Scientific copies and
CSV safety sidecars retain exact bytes; HTML local links point to named copies.
"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import unicodedata
import uuid


def _slug(value, limit=48):
    value = unicodedata.normalize('NFKC', str(value))
    value = re.sub(r'[^\w-]+', '-', value, flags=re.UNICODE).strip('-_')
    return value[:limit].rstrip('-_') or 'unspecified'


def document_stem(*, kind, target, identity, created_utc):
    timestamp = datetime.fromisoformat(str(created_utc).replace('Z', '+00:00'))
    if timestamp.tzinfo is None:
        raise ValueError('Document date must include a timezone')
    date = timestamp.astimezone(timezone.utc).strftime('%Y-%m-%d_%H-%M-%SZ')
    short = hashlib.sha256(str(identity).encode('utf-8')).hexdigest()[:8]
    return f'{_slug(kind,16).upper()}__{date}__{_slug(target,24)}__{short}'


def publish_documents(folder, *, kind, target, identity, created_utc, filenames):
    folder = Path(folder)
    destination = folder / 'documents'
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(f'Documents already published: {destination}')
    stem = document_stem(kind=kind, target=target, identity=identity, created_utc=created_utc)
    mapping = {}
    for name in filenames:
        if not isinstance(name,str) or Path(name).name != name or '/' in name or '\\' in name or name.startswith('.'):
            raise ValueError('Document source must be a plain filename')
        source = folder / name
        if not source.is_file() or source.is_symlink() or not source.resolve().is_relative_to(folder.resolve()):
            raise ValueError(f'Invalid document source: {name}')
        if name in mapping: raise ValueError(f'Duplicate document source: {name}')
        role = _slug(Path(name).stem,28)
        mapping[name] = f'documents/{stem}__{role}{Path(name).suffix.lower()}'
    for name in list(mapping):
        sidecar = name + '.notes.json'
        if name.endswith('.csv') and (folder / sidecar).is_file():
            source=folder/sidecar
            if source.is_symlink() or not source.resolve().is_relative_to(folder.resolve()):
                raise ValueError('CSV notes must be inside the document folder')
            mapping[sidecar] = mapping[name] + '.notes.json'
    if len({v.casefold() for v in mapping.values()}) != len(mapping): raise ValueError('Document names collide')
    staging=folder/('.docs-'+uuid.uuid4().hex[:8])
    staging.mkdir()
    try:
        for name, relative in mapping.items():
            source=folder/name;output=staging/Path(relative).name
            if source.suffix.lower()=='.html':
                text=source.read_text(encoding='utf-8')
                def link(match):
                    path=match.group(2)
                    replacement=Path(mapping[path]).name if path in mapping else path
                    return 'href='+match.group(1)+replacement+match.group(1)
                text=re.sub(r'href=([\"\'])([^\"\']+)\1',link,text)
                output.write_text(text,encoding='utf-8')
            else:shutil.copyfile(source,output)
        index={'schema_version':1,'kind':kind,'target':target,'identity':identity,'created_utc':created_utc,
               'filename_timezone':'UTC (Z)','files':{name:{'filename':Path(path).name,
                    'sha256':hashlib.sha256((staging/Path(path).name).read_bytes()).hexdigest()} for name,path in mapping.items()}}
        (staging/'INDEX.json').write_text(json.dumps(index,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        staging.rename(destination)
    except BaseException:
        if staging.is_dir() and staging.resolve().parent==folder.resolve():shutil.rmtree(staging)
        raise
    return mapping

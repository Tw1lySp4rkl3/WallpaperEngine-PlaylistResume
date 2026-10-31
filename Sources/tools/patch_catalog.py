"""Read the current patch bundle and the single historical-release catalogue.

No originals are included. An alias can refer to the current version or to an
archived release, so it remains valid when that current version becomes legacy.
"""
from pathlib import Path
import hashlib,json,re

PATCHES=Path(__file__).resolve().parents[1]/'patches'
FILENAMES=('wallpaper32.exe','wallpaper64.exe','ui/dist/scripts/scripts.js',
           'PlaylistResume32.dll','PlaylistResume64.dll')

def receipt_bytes(value):
    fields=('project','version','engine','payload')
    if set(value)!=set(fields):raise ValueError('Unexpected installation receipt fields')
    return json.dumps({key:value[key] for key in fields},ensure_ascii=False,separators=(',',':')).encode()+b'\r\n'

def load_catalog(directory=PATCHES):
    directory=Path(directory)
    current=json.loads((directory/'patches.json').read_text(encoding='utf-8'))
    legacy=json.loads((directory/'legacy.json').read_text(encoding='utf-8'))
    for bundle in (current,legacy):
        if bundle.get('schema_version')!=1 or bundle.get('project')!='PlaylistResume':
            raise ValueError('Unsupported patch catalogue schema or project')
    version=current['version']
    if not re.fullmatch(r'[A-Za-z0-9._-]+',version):raise ValueError('Invalid project version')
    files=current['files']
    if len(files)!=5 or {m['filename'] for m in files}!=set(FILENAMES):
        raise ValueError('Current catalogue must contain exactly the five runtime files')
    files=sorted(files,key=lambda m:FILENAMES.index(m['filename']))
    current['files']=files
    for m in files:
        if m.get('revision')!=version or m.get('version')!=current['engine_version']:
            raise ValueError('Runtime recipe version does not match its catalogue')
    records=legacy['releases'];versions={version:current};ids=set()
    for release in records:
        name=release['version'];code=release['compatibility_id']
        if not re.fullmatch(r'[A-Za-z0-9._-]+',name) or name in versions:
            raise ValueError('Invalid or duplicate legacy version')
        if type(code) is not int or code<2 or code==6 or code in ids:
            raise ValueError('Legacy compatibility IDs must be unique; 1 and 6 are reserved')
        if type(release.get('preview')) is not bool:
            raise ValueError('Each legacy release must declare preview true or false')
        if ('files' in release)==('same_as' in release):
            raise ValueError('Each legacy release needs files or same_as, exclusively')
        ids.add(code);versions[name]=release
    def resolve(name,chain=()):
        if name in chain:raise ValueError('Cyclic legacy alias')
        if name not in versions:raise ValueError('Legacy alias refers to a missing version')
        value=versions[name]
        if 'same_as' in value:return resolve(value['same_as'],chain+(name,))
        result=value['files']
        if not result or len({m['filename'] for m in result})!=len(result):
            raise ValueError('Empty legacy release or duplicate filenames')
        return result
    resolved=[]
    for release in sorted(records,key=lambda r:r['compatibility_id']):
        value=dict(release);value['files']=resolve(release['version'])
        if value.get('receipt') is not None:
            receipt=value['receipt']
            if receipt.get('project')!='PlaylistResume' or receipt.get('version')!=value['version']:
                raise ValueError('Legacy receipt does not match its release')
            by_name={m['filename']:m for m in value['files']}
            if set(by_name)!=set(FILENAMES):raise ValueError('A receipted release needs all five runtime recipes')
            fingerprint=hashlib.sha256(''.join(by_name[name]['patched_sha256'] for name in FILENAMES).encode()).hexdigest()
            if receipt.get('payload')!=fingerprint:raise ValueError('Legacy receipt payload fingerprint does not match')
            value['receipt_bytes']=receipt_bytes(receipt)
        else:value['receipt_bytes']=b''
        resolved.append(value)
    fingerprint=hashlib.sha256(''.join(m['patched_sha256'] for m in files).encode()).hexdigest()
    receipt={'project':'PlaylistResume','version':version,'engine':current['engine_version'],'payload':fingerprint}
    return {'current':current,'legacy':resolved,'receipt':receipt,'receipt_bytes':receipt_bytes(receipt)}

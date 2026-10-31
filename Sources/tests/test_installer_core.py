"""Execute the actual portable C installer with an instrumented filesystem.

The Windows executable compiles the same engine and generated payloads. This
test substitutes filesystem/process APIs, not transforms, hashes or transactions.
"""
from pathlib import Path
import ctypes as c
import hashlib,json,os,struct,subprocess,sys,tempfile,unittest,zlib

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from patch_catalog import load_catalog
INPUT=Path(os.environ.get('WE_ORIGINALS',ROOT/'upload'))
OUT=Path(os.environ.get('WE_INSTALLER_BUILD',ROOT/'build'));OUT.mkdir(parents=True,exist_ok=True)
sources=[ROOT/'installer'/name for name in ['installer_core.c','sha256.c','payloads.c','test_allocator.c']]
subprocess.run(['gcc','-shared','-fPIC','-O2','-Wall','-Wextra','-Werror','-Wno-misleading-indentation','-o',str(OUT/'installer-core.so'),*map(str,sources)],check=True)
lib=c.CDLL(str(OUT/'installer-core.so'))

class Buffer(c.Structure):_fields_=[('data',c.c_void_p),('size',c.c_size_t),('exists',c.c_int)]
READ=c.CFUNCTYPE(c.c_int,c.c_void_p,c.c_char_p,c.POINTER(Buffer))
WRITE=c.CFUNCTYPE(c.c_int,c.c_void_p,c.c_char_p,c.c_void_p,c.c_size_t)
REPLACE=c.CFUNCTYPE(c.c_int,c.c_void_p,c.c_char_p,c.c_char_p)
REMOVE=c.CFUNCTYPE(c.c_int,c.c_void_p,c.c_char_p)
STOPPED=c.CFUNCTYPE(c.c_int,c.c_void_p)
LOG=c.CFUNCTYPE(None,c.c_void_p,c.c_char_p)
class FS(c.Structure):_fields_=[('context',c.c_void_p),('read',READ),('write',WRITE),('replace',REPLACE),('remove',REMOVE),('stopped',STOPPED),('log',LOG)]
class Status(c.Structure):_fields_=[('found',c.c_int),('supported',c.c_int),('can_install',c.c_int),('can_restore',c.c_int),('version',c.c_int),('label',c.c_char*256),('detail',c.c_char*512)]
lib.pr_alloc.argtypes=[c.c_size_t];lib.pr_alloc.restype=c.c_void_p
lib.pr_hash.argtypes=[c.c_void_p,c.c_size_t,c.c_void_p]
lib.pr_run.argtypes=[c.POINTER(FS),c.c_int]
lib.pr_status.argtypes=[c.POINTER(FS),c.POINTER(Status)]
lib.pr_test_allocations.restype=c.c_long
lib.pr_vdf_paths.argtypes=[c.c_void_p,c.c_size_t,c.c_void_p,c.c_uint]

CATALOG=load_catalog();CURRENT=CATALOG['current']['files']
LEGACY={r['version']:r['files'] for r in CATALOG['legacy']}
ORIGINALS={m['filename']:(INPUT/Path(m['filename']).name).read_bytes() for m in CURRENT[:3]}
def apply(data,m):
    if m['kind']=='new':out=bytes.fromhex(m['contents_hex'])
    elif m['kind']=='text':
        out=data
        for r in m['replacements']:
            before,after=r['before'].encode(),r['after'].encode();assert out.count(before)==1
            out=out.replace(before,after)
    else:
        out=bytearray(data+bytes.fromhex(m['append_hex']))
        for ch in m['changes']:
            at=ch['offset'];old,new=bytes.fromhex(ch['before']),bytes.fromhex(ch['after'])
            assert out[at:at+len(old)]==old;out[at:at+len(old)]=new
        out=bytes(out)
    assert hashlib.sha256(out).hexdigest()==m['patched_sha256'];return out

class Disk:
    def __init__(self,version='original',engine=lib):
        self.engine=engine
        self.files=dict(ORIGINALS);self.logs=[];self.events=[];self.running=False
        self.rename_count=0;self.fail_rename=0;self.fail_delete=None;self.failed=False;self.fail_write_stage=0;self.stage_count=0
        self.fail_read=None;self.fail_all_rollback=False;self.callback_errors=[]
        if version!='original':
            for m in (CURRENT if version=='current' else LEGACY[version]):
                self.files[m['filename']]=apply(self.files.get(m['filename']),m)
        def read(ctx,path,out):
            name=path.decode();out.contents.data=None;out.contents.size=0;out.contents.exists=0
            if name==self.fail_read:return 0
            data=self.files.get(name)
            if data is not None:
                pointer=engine.pr_alloc(len(data) or 1);assert pointer
                if data:c.memmove(pointer,data,len(data))
                out.contents.data=pointer;out.contents.size=len(data);out.contents.exists=1
            return 1
        def write(ctx,path,pointer,size):
            name=path.decode();self.events.append(('write',name))
            if '.playlist-resume-' in name:
                self.stage_count+=1
                if self.stage_count==self.fail_write_stage:return 0
            if name in self.files:return 0
            self.files[name]=c.string_at(pointer,size);return 1
        def replace(ctx,src,dest):
            src,dest=src.decode(),dest.decode();self.rename_count+=1;self.events.append(('replace',dest))
            if self.rename_count==self.fail_rename:self.failed=True;return 0
            if self.failed and self.fail_all_rollback:return 0
            self.files[dest]=self.files.pop(src);return 1
        def remove(ctx,path):
            name=path.decode();self.events.append(('remove',name))
            if name==self.fail_delete and not self.failed:self.failed=True;return 0
            self.files.pop(name,None);return 1
        self.callbacks=[READ(read),WRITE(write),REPLACE(replace),REMOVE(remove),STOPPED(lambda ctx:int(not self.running)),LOG(lambda ctx,msg:self.logs.append(msg.decode()))]
        self.fs=FS(None,*self.callbacks)
    def status(self):
        status=Status();self.engine.pr_status(c.byref(self.fs),c.byref(status));return status
    def run(self,action=1):return self.engine.pr_run(c.byref(self.fs),action)
    def runtime(self):return {k:v for k,v in self.files.items() if not k.startswith('playlist-resume-backup/') and '.playlist-resume-' not in k}
    def assert_no_temps(self,test):test.assertFalse([k for k in self.files if '.playlist-resume-' in k])
    def legacy_state(self):
        self.files['bin/pi-playlist-resume-r03.bin']=(ROOT/'tests/cache-format-fixture.bin').read_bytes()
        self.files['bin/pi-playlist-resume-r03.log']=b'checkpoint monitor=0000000000000001 position=4 detail=10\r\n'
    def check_installed(self,test):
        for m in CURRENT:test.assertEqual(hashlib.sha256(self.files[m['filename']]).hexdigest(),m['patched_sha256'])
        test.assertIn('bin/playlist-resume-install.json',self.files)
        test.assertNotIn('PiPlaylistResume32.dll',self.files);test.assertNotIn('PiPlaylistResume64.dll',self.files)
        test.assertEqual(self.status().version,1)
    def check_original(self,test):
        for name,data in ORIGINALS.items():test.assertEqual(self.files[name],data)
        for name in ['PlaylistResume32.dll','PlaylistResume64.dll','PiPlaylistResume32.dll','PiPlaylistResume64.dll','bin/playlist-resume-install.json']:test.assertNotIn(name,self.files)
        test.assertEqual(self.status().version,0)

class InstallerTests(unittest.TestCase):
    def tearDown(self):self.assertEqual(lib.pr_test_allocations(),0,'C installer leaked an owned buffer')
    def test_sha256(self):
        for n in [0,1,3,55,56,63,64,65,127,128,129,1000000]:
            data=bytes(i%251 for i in range(n));out=c.create_string_buffer(32);lib.pr_hash(data,n,out)
            self.assertEqual(out.raw,hashlib.sha256(data).digest())
    def test_version_detection(self):
        for version,expected in [('original',0),('R01',5),('R02',4),('R03',3),('R04',2)]:
            with self.subTest(version=version):
                d=Disk(version);before=dict(d.files);s=d.status();self.assertEqual(s.version,expected,s.label)
                self.assertTrue(s.supported);self.assertEqual(d.files,before);self.assertFalse(d.events)
    def test_all_versions_install_idempotent_restore(self):
        for version in ['original','R01','R02','R03','R04']:
            with self.subTest(version=version):
                d=Disk(version);d.files['config.json']=b'preserve configuration';d.files['bin/playliststate.bin']=b'preserve native state'
                self.assertEqual(d.run(),0,d.logs);d.check_installed(self)
                before=dict(d.files);self.assertEqual(d.run(),0);self.assertEqual(d.files,before)
                self.assertEqual(d.run(2),0);d.check_original(self)
                self.assertEqual(d.files['config.json'],b'preserve configuration')
                self.assertEqual(d.files['bin/playliststate.bin'],b'preserve native state');d.assert_no_temps(self)
    def test_r04_upgrade_does_not_rewrite_runtime(self):
        d=Disk('R04');self.assertEqual(d.run(),0);d.check_installed(self)
        self.assertEqual([p for op,p in d.events if op=='replace'],['bin/playlist-resume-install.json'])
    def test_archived_v1_receipt_upgrade_and_restore(self):
        # Simulate a later release with v1.0 archived in the SAME legacy.json.
        # Compile the real core and freshly generated payload; no version/hash
        # detection or transaction code is substituted.
        with tempfile.TemporaryDirectory(prefix='playlist-resume-legacy-') as temp:
            folder=Path(temp);current=json.loads((ROOT/'patches/patches.json').read_text())
            legacy=json.loads((ROOT/'patches/legacy.json').read_text())
            legacy['releases'].append({'version':'1.0','compatibility_id':7,'preview':False,
                'files':json.loads(json.dumps(current['files'])),'receipt':CATALOG['receipt']})
            current['version']='1.1'
            for m in current['files']:m['revision']='1.1'
            (folder/'patches.json').write_text(json.dumps(current))
            (folder/'legacy.json').write_text(json.dumps(legacy))
            subprocess.run([sys.executable,str(ROOT/'tools/generate_installer_payloads.py'),
                '--catalog',str(folder),'--output',str(folder/'payloads.c')],check=True)
            binary=folder/'future-core.so'
            subprocess.run(['gcc','-shared','-fPIC','-O2','-Wall','-Wextra','-Werror','-Wno-misleading-indentation',
                '-I',str(ROOT/'installer'),'-o',str(binary),str(ROOT/'installer/installer_core.c'),
                str(ROOT/'installer/sha256.c'),str(ROOT/'installer/test_allocator.c'),str(folder/'payloads.c')],check=True)
            future=c.CDLL(str(binary))
            for name in ['pr_alloc','pr_hash','pr_run','pr_status','pr_test_allocations','pr_vdf_paths']:
                getattr(future,name).argtypes=getattr(lib,name).argtypes
                getattr(future,name).restype=getattr(lib,name).restype
            disk=Disk('current',engine=future)
            disk.files['bin/playlist-resume-install.json']=CATALOG['receipt_bytes']
            disk.files['bin/playlist-resume.bin']=b'preserve positions'
            status=disk.status();self.assertEqual(status.version,7);self.assertEqual(status.label.decode(),'Installiert – v1.0')
            before=disk.runtime();self.assertEqual(disk.run(),0,disk.logs)
            self.assertEqual(json.loads(disk.files['bin/playlist-resume-install.json'])['version'],'1.1')
            self.assertEqual(disk.status().version,1)
            self.assertEqual([p for op,p in disk.events if op=='replace'],['bin/playlist-resume-install.json'])
            self.assertEqual(disk.files['bin/playlist-resume.bin'],before['bin/playlist-resume.bin'])
            self.assertEqual(disk.run(2),0);disk.check_original(self)
            self.assertEqual(disk.files['bin/playlist-resume.bin'],b'preserve positions')
            # Restoring an archived v1.0 directly must also work, without an update.
            disk=Disk('current',engine=future);disk.files['bin/playlist-resume-install.json']=CATALOG['receipt_bytes']
            self.assertEqual(disk.run(2),0);disk.check_original(self)
            self.assertEqual(future.pr_test_allocations(),0)
    def test_r03_cache_and_log_migrate_and_are_preserved_on_restore(self):
        d=Disk('R03');d.legacy_state();old=d.files['bin/pi-playlist-resume-r03.bin'];self.assertEqual(d.run(),0,d.logs)
        new=d.files['bin/playlist-resume.bin'];self.assertEqual(new[:8],b'WPRS0001');self.assertEqual(new[8:],old[8:])
        self.assertNotIn('bin/pi-playlist-resume-r03.bin',d.files);self.assertNotIn('bin/pi-playlist-resume-r03.log',d.files)
        self.assertEqual(d.files['playlist-resume-backup/bin/pi-playlist-resume-r03.bin'],old)
        self.assertEqual(d.run(2),0);self.assertEqual(d.files['bin/playlist-resume.bin'],new)
    def test_neutral_cache_wins(self):
        d=Disk('R03');d.legacy_state();data=bytearray(d.files['bin/pi-playlist-resume-r03.bin']);data[:8]=b'WPRS0001'
        struct.pack_into('<I',data,36,6);struct.pack_into('<I',data,12,zlib.crc32(data[16:]));d.files['bin/playlist-resume.bin']=bytes(data)
        self.assertEqual(d.run(),0);self.assertEqual(d.files['bin/playlist-resume.bin'],bytes(data))
    def test_unknown_program_or_receipt_refused(self):
        for name in ['wallpaper64.exe','ui/dist/scripts/scripts.js','PlaylistResume32.dll','PiPlaylistResume64.dll','bin/playlist-resume-install.json']:
            with self.subTest(file=name):
                d=Disk();d.files[name]=b'unknown';before=dict(d.files);self.assertFalse(d.status().supported)
                self.assertNotEqual(d.run(),0);self.assertEqual(d.files,before)
    def test_read_errors_are_not_missing_files(self):
        d=Disk();d.fail_read='PlaylistResume32.dll';self.assertFalse(d.status().supported)
        self.assertNotEqual(d.run(),0);self.assertFalse(d.events)
    def test_missing_primary_refused_but_missing_dll_repaired(self):
        d=Disk();d.files.pop('wallpaper64.exe');self.assertFalse(d.status().supported);self.assertNotEqual(d.run(),0)
        d=Disk('R04');d.files.pop('PlaylistResume32.dll');self.assertEqual(d.status().version,6)
        self.assertEqual(d.run(),0);d.check_installed(self)
    def test_running_process_guard(self):
        d=Disk();d.running=True;before=dict(d.files);self.assertNotEqual(d.run(),0);self.assertEqual(d.files,before)
        self.assertTrue(any('läuft noch' in line for line in d.logs))
    def test_restore_without_backups(self):
        d=Disk();self.assertEqual(d.run(),0);d.files={k:v for k,v in d.files.items() if not k.startswith('playlist-resume-backup/')}
        self.assertEqual(d.run(2),0);d.check_original(self)
    def test_changed_backup_refused(self):
        d=Disk();d.files['playlist-resume-backup/wallpaper64.exe']=b'changed';before=dict(d.files)
        self.assertNotEqual(d.run(),0);self.assertEqual(d.files,before)
    def test_corrupt_cache_refused_before_mutation(self):
        d=Disk('R03');d.legacy_state();d.files['bin/pi-playlist-resume-r03.bin']+=b'bad';before=dict(d.files)
        self.assertNotEqual(d.run(),0);self.assertEqual(d.files,before)
    def test_each_r03_commit_rename_failure_rolls_back(self):
        for fail in range(1,9):
            with self.subTest(rename=fail):
                d=Disk('R03');d.legacy_state();before=d.runtime();d.fail_rename=fail
                self.assertEqual(d.run(),1,d.logs);self.assertEqual(d.runtime(),before);d.assert_no_temps(self)
    def test_each_r03_staging_failure_preserves_runtime(self):
        for fail in range(1,9):
            with self.subTest(write=fail):
                d=Disk('R03');d.legacy_state();before=d.runtime();d.fail_write_stage=fail
                self.assertEqual(d.run(),1,d.logs);self.assertEqual(d.runtime(),before);d.assert_no_temps(self)
    def test_each_retired_delete_failure_rolls_back(self):
        for name in ['PiPlaylistResume32.dll','PiPlaylistResume64.dll','bin/pi-playlist-resume-r03.bin','bin/pi-playlist-resume-r03.log']:
            with self.subTest(file=name):
                d=Disk('R03');d.legacy_state();before=d.runtime();d.fail_delete=name
                self.assertEqual(d.run(),1,d.logs);self.assertEqual(d.runtime(),before);d.assert_no_temps(self)
    def test_restore_deletion_failure_rolls_back(self):
        d=Disk();self.assertEqual(d.run(),0);before=d.runtime();d.fail_delete='PlaylistResume64.dll'
        self.assertEqual(d.run(2),1,d.logs);self.assertEqual(d.runtime(),before);d.assert_no_temps(self)
    def test_incomplete_rollback_is_reported(self):
        d=Disk();d.fail_rename=4;d.fail_all_rollback=True;self.assertEqual(d.run(),2)
        self.assertTrue(any('Rücknahme unvollständig' in line for line in d.logs))
    def test_vdf_paths(self):
        data=b'"libraryfolders" { // comment\n "0" { "path" "C:\\\\Program Files (x86)\\\\Steam" } "1" { "path" "G:\\\\Steam" } "2" { "path" "D:\\\\Spiele '+ '日本語'.encode()+b'" } }'
        paths=((c.c_char*1024)*8)();n=lib.pr_vdf_paths(data,len(data),paths,8)
        self.assertEqual(n,3);self.assertEqual(paths[0].value.decode(),'C:\\Program Files (x86)\\Steam')
        self.assertEqual(paths[1].value.decode(),'G:\\Steam');self.assertIn('日本語',paths[2].value.decode())
        n=lib.pr_vdf_paths(data,len(data),paths,1);self.assertEqual(n,1)

if __name__=='__main__':
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(InstallerTests)
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    (OUT/'INSTALLER-CORE-RESULTS.json').write_text(json.dumps({'tests':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'passed':result.wasSuccessful(),
        'scope':'Actual portable C core and embedded recipes with substituted filesystem/process APIs; Windows GUI is separate.'},indent=2)+'\n')
    raise SystemExit(not result.wasSuccessful())

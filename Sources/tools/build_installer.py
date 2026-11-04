"""Build the native Windows installer with all patch recipes embedded."""
from pathlib import Path
import hashlib,json,os,subprocess,sys,shutil
import pefile
ROOT=Path(__file__).resolve().parents[1]
OUT=Path(os.environ.get('WE_INSTALLER_BUILD',ROOT/'build'));OUT.mkdir(parents=True,exist_ok=True)
zig_input=os.environ.get('PIRS_ZIG') or shutil.which('zig')
if not zig_input:raise SystemExit('Zig 0.17.0 bereitstellen und PIRS_ZIG auf die Zig-Datei setzen.')
ZIG=Path(zig_input).resolve()
HEADERS=ZIG.parent/'lib/libc/include/any-windows-any'
def main():
    subprocess.run([sys.executable,str(ROOT/'tools/generate_installer_payloads.py')],check=True)
    obj=OUT/'installer-resources.o'
    subprocess.run([str(ZIG),'rc','/:no-preprocess','/:target','X86','/:output-format','coff','/fo',str(obj),'installer.rc'],cwd=ROOT/'installer',check=True)
    dest=ROOT.parent/'PlaylistResumeSetup.exe'
    sources=['installer_gui.c','installer_language.c','installer_windows.c','installer_core.c','sha256.c','payloads.c']
    args=[str(ZIG),'cc','-target','x86-windows-gnu','-isystem',str(HEADERS),'-O2','-ffreestanding','-fno-builtin',
          '-fno-stack-protector','-mstackrealign','-nostdlib','-Wl,--entry,WinMainCRTStartup','-Wl,--subsystem,windows',
          '-o',str(dest),*[str(ROOT/'installer'/f) for f in sources],str(obj),'-lkernel32','-luser32','-lgdi32','-lshell32','-lole32','-ladvapi32']
    subprocess.run(args,check=True)
    data=bytearray(dest.read_bytes());p=pefile.PE(data=data)
    import struct
    struct.pack_into('<I',data,p.FILE_HEADER.get_field_absolute_offset('TimeDateStamp'),0)
    struct.pack_into('<I',data,p.OPTIONAL_HEADER.get_field_absolute_offset('CheckSum'),0)
    # Zig/LLD adds a nondeterministic CodeView/PDB build ID although no PDB is
    # distributed. It is debug-only metadata; keep the section layout and all
    # executable bytes intact while removing the directory and its raw data.
    for section in p.sections:
        if section.Name.rstrip(b'\0')==b'.buildid':
            start=section.PointerToRawData;end=start+section.SizeOfRawData
            for item in getattr(p,'DIRECTORY_ENTRY_DEBUG',[]):
                assert start<=item.struct.get_file_offset()<end
                assert not item.struct.SizeOfData or start<=item.struct.PointerToRawData<end
            data[start:end]=b'\0'*(end-start)
    debug=p.OPTIONAL_HEADER.DATA_DIRECTORY[6]
    struct.pack_into('<II',data,debug.get_file_offset(),0,0)
    checksum=pefile.PE(data=data).generate_checksum()
    struct.pack_into('<I',data,p.OPTIONAL_HEADER.get_field_absolute_offset('CheckSum'),checksum)
    dest.write_bytes(data);p=pefile.PE(data=data)
    # The matching PDB is a compiler intermediate, not a runtime dependency.
    pdb=dest.with_suffix('.pdb')
    if pdb.exists():pdb.unlink()
    assert p.verify_checksum() and p.OPTIONAL_HEADER.Subsystem==2
    assert not p.OPTIONAL_HEADER.DATA_DIRECTORY[6].VirtualAddress
    assert not any(s.Characteristics&0x20000000 and s.Characteristics&0x80000000 for s in p.sections)
    assert p.VS_FIXEDFILEINFO[0].FileVersionMS==0x10000
    report={'filename':dest.name,'project_version':'1.0.1-test','architecture':'x86 (also runs on x64 Windows)',
            'installer_languages':['de','en'],'default_language':'German for German Windows display languages, otherwise English',
            'size':len(data),'sha256':hashlib.sha256(data).hexdigest(),'subsystem':'Windows GUI',
            'imports':[i.dll.decode() for i in p.DIRECTORY_ENTRY_IMPORT],
            'runtime_payload':'Preview with transient playlist click requests and guarded checkpoints.'}
    (OUT/'INSTALLER-BUILD.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
if __name__=='__main__':main()

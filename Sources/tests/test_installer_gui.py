"""Boot the compiled x86 GUI with substituted Win32 APIs in Unicorn.

Checks the real entry point, stdcall argument cleanup, Unicode Steam discovery,
control creation, status and button gating. This does not render a Windows UI.
"""
from pathlib import Path
import copy,hashlib,json,ntpath,os,struct,sys,time
import pefile
from unicorn import Uc,UC_ARCH_X86,UC_MODE_32,UC_HOOK_CODE
from unicorn.x86_const import UC_X86_REG_ESP,UC_X86_REG_EIP,UC_X86_REG_EAX
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from patch_catalog import load_catalog
VERSION=load_catalog()['current']['version']
OUT=Path(os.environ.get('WE_INSTALLER_BUILD',ROOT/'build'))
INPUT=Path(os.environ.get('WE_ORIGINALS',ROOT/'upload'))
COUNTS={
'CloseHandle':1,'CreateDirectoryW':2,'CreateFileW':7,'CreateMutexW':3,'CreateThread':6,'CreateToolhelp32Snapshot':2,
'DeleteFileW':1,'ExitProcess':1,'FlushFileBuffers':1,'FormatMessageW':7,'GetEnvironmentVariableW':3,
'GetFileAttributesW':1,'GetFileSizeEx':2,'GetFullPathNameW':4,'GetLastError':0,'GetModuleFileNameW':3,
'GetModuleHandleW':1,'GetProcessHeap':0,'GetUserDefaultUILanguage':0,'HeapAlloc':3,'HeapFree':3,'MoveFileExW':3,'MulDiv':3,
'MultiByteToWideChar':6,'Process32FirstW':2,'Process32NextW':2,'ReadFile':5,'WideCharToMultiByte':8,'WriteFile':5,
'AdjustWindowRectEx':4,'CreateWindowExW':12,'DefWindowProcW':4,'DestroyWindow':1,'DispatchMessageW':1,
'EnableMenuItem':3,'EnableWindow':2,'FindWindowW':2,'GetDC':1,'GetMessageW':4,'GetSystemMenu':2,
'GetWindowTextLengthW':1,'GetWindowTextW':3,'IsDialogMessageW':2,'KillTimer':2,'LoadCursorW':2,
'LoadIconW':2,'MessageBoxW':4,'PostMessageW':4,'PostQuitMessage':1,'RegisterClassW':1,'ReleaseDC':2,
'SendMessageW':4,'SetCursor':1,'SetFocus':1,'SetForegroundWindow':1,'SetProcessDPIAware':0,'SetTimer':4,
'SetWindowTextW':2,'ShowWindow':2,'SystemParametersInfoW':4,'TranslateMessage':1,'UpdateWindow':1,
'CreateFontW':14,'DeleteObject':1,'GetDeviceCaps':2,'SHBrowseForFolderW':1,'SHGetPathFromIDListW':2,
'CoInitializeEx':2,'CoTaskMemFree':1,'CoUninitialize':0,'RegCloseKey':1,'RegOpenKeyExW':5,'RegQueryValueExW':6}
API,STACK,HEAP=0x50000000,0x20000000,0x30000000

def canonical(path):
    if path.startswith('\\\\?\\UNC\\'):path='\\\\'+path[8:]
    elif path.startswith('\\\\?\\'):path=path[4:]
    return ntpath.normpath(path).casefold()

class Gui:
    def __init__(self,files=None,steam='C:\\Program Files (x86)\\Steam',dpi=96,message_error=False,language_id=0x0407,events=None,thread_mode=None):
        p=pefile.PE(str(ROOT.parent/'PlaylistResumeSetup.exe'));self.p=p;self.base=p.OPTIONAL_HEADER.ImageBase
        self.u=Uc(UC_ARCH_X86,UC_MODE_32);self.u.mem_map(self.base,(p.OPTIONAL_HEADER.SizeOfImage+4095)&~4095)
        self.u.mem_write(self.base,p.get_memory_mapped_image());self.u.mem_map(STACK,0x200000);self.u.mem_map(HEAP,0x8000000);self.u.mem_map(API,0x10000)
        self.u.reg_write(UC_X86_REG_ESP,STACK+0x1f0000);self.next=HEAP;self.allocations={};self.last_error=0
        self.files={canonical(k):v for k,v in (files or {}).items()};self.steam=steam;self.dpi=dpi
        self.controls={};self.handles={};self.next_handle=100;self.apis={};self.exit=None;self.message_error=message_error
        self.language_id=language_id;self.events=list(events or []);self.posted=[];self.snapshots={};self.boxes=[];self.folder_titles=[]
        self.thread_mode=thread_mode;self.worker=None;self.read_error=False;self.format_languages=[];self.read_count=0
        for table in p.DIRECTORY_ENTRY_IMPORT:
            for item in table.imports:
                name=item.name.decode();assert name in COUNTS,name
                address=API+len(self.apis)*16;self.apis[address]=name;self.u.mem_write(item.address,struct.pack('<I',address))
        self.u.hook_add(UC_HOOK_CODE,self.hook,begin=API,end=API+0xffff)
    def r(self,a,n):return bytes(self.u.mem_read(a,n))
    def w(self,a,b):self.u.mem_write(a,bytes(b))
    def r32(self,a):return struct.unpack('<I',self.r(a,4))[0]
    def w32(self,a,v):self.w(a,struct.pack('<I',v&0xffffffff))
    def wide(self,a):
        if not a:return ''
        b=bytearray()
        for i in range(32768):
            v=self.r(a+2*i,2)
            if v==b'\0\0':return b.decode('utf-16-le')
            b.extend(v)
        raise AssertionError('unterminated wide string')
    def narrow(self,a):
        b=bytearray()
        while True:
            v=self.r(a+len(b),1)
            if v==b'\0':return bytes(b)
            b.extend(v)
    def put_wide(self,a,s,capacity):
        b=s.encode('utf-16-le')
        assert len(b)//2<capacity,(s,capacity)
        self.w(a,b+b'\0\0');return len(b)//2
    def new_handle(self,value):
        h=self.next_handle;self.next_handle+=1;self.handles[h]=value;return h
    def ret(self,value,args):
        sp=self.u.reg_read(UC_X86_REG_ESP);target=self.r32(sp)
        self.u.reg_write(UC_X86_REG_EAX,value&0xffffffff);self.u.reg_write(UC_X86_REG_ESP,sp+4+4*args);self.u.reg_write(UC_X86_REG_EIP,target)
    def hook(self,u,address,size,opaque):
        name=self.apis[address];count=COUNTS[name];sp=u.reg_read(UC_X86_REG_ESP);a=[self.r32(sp+4+4*i) for i in range(count)];v=1
        if name=='ExitProcess':self.exit=a[0];u.emu_stop();return
        if name=='HeapAlloc':
            n=a[2];v=self.next;self.next+=(n+15)&~15;assert self.next<HEAP+0x8000000
            self.allocations[v]=n
        elif name=='HeapFree':assert a[2] in self.allocations;self.allocations.pop(a[2])
        elif name=='GetProcessHeap':v=1
        elif name=='GetLastError':v=self.last_error
        elif name=='GetModuleHandleW':v=self.base
        elif name=='GetUserDefaultUILanguage':v=self.language_id
        elif name=='GetModuleFileNameW':v=self.put_wide(a[1],'C:\\Downloads\\PlaylistResume_v1.0\\PlaylistResumeSetup.exe',a[2])
        elif name=='GetEnvironmentVariableW':v=self.put_wide(a[1],'C:\\Program Files (x86)' if self.wide(a[0])=='ProgramFiles(x86)' else 'C:\\Program Files',a[2])
        elif name=='GetFullPathNameW':v=self.put_wide(a[2],ntpath.normpath(self.wide(a[0])),a[1])
        elif name=='GetFileAttributesW':
            p=canonical(self.wide(a[0]));v=128 if p in self.files else 16 if any(k.startswith(p+'\\') for k in self.files) else 0xffffffff
            if v==0xffffffff:self.last_error=2
        elif name=='CreateFileW':
            assert a[4]==3,'Startup must be read-only';p=canonical(self.wide(a[0]))
            self.read_count+=1
            if self.read_error and p.endswith('\\wallpaper32.exe'):v=0xffffffff;self.last_error=5
            elif p not in self.files:v=0xffffffff;self.last_error=2
            else:v=self.new_handle({'file':p,'at':0})
        elif name=='GetFileSizeEx':self.w(a[1],struct.pack('<q',len(self.files[self.handles[a[0]]['file']])))
        elif name=='ReadFile':
            h=self.handles[a[0]];data=self.files[h['file']][h['at']:h['at']+a[2]];h['at']+=len(data)
            self.w(a[1],data);self.w32(a[3],len(data))
        elif name=='CloseHandle':self.handles.pop(a[0],None)
        elif name=='CreateMutexW':v=self.new_handle({'kind':'mutex'});self.last_error=0
        elif name=='RegOpenKeyExW':
            if self.steam:v=0;self.w32(a[4],self.new_handle({'kind':'registry'}))
            else:v=2
        elif name=='RegQueryValueExW':
            key=self.wide(a[1]);text=self.steam if key in ['SteamPath','InstallPath'] else ''
            if not text:v=2
            else:
                self.w32(a[3],1);n=self.put_wide(a[4],text,self.r32(a[5])//2);self.w32(a[5],(n+1)*2);v=0
        elif name=='RegCloseKey':self.handles.pop(a[0]);v=0
        elif name=='MultiByteToWideChar':
            data=self.narrow(a[2]) if a[3]==0xffffffff else self.r(a[2],a[3]);text=data.decode('utf-8')
            v=len(text.encode('utf-16-le'))//2+(a[3]==0xffffffff)
            if a[4]:self.w(a[4],text.encode('utf-16-le')+(b'\0\0' if a[3]==0xffffffff else b''))
        elif name=='WideCharToMultiByte':
            text=self.wide(a[2]) if a[3]==0xffffffff else self.r(a[2],2*a[3]).decode('utf-16-le');data=text.encode();v=len(data)+(a[3]==0xffffffff)
            if a[4]:self.w(a[4],data+(b'\0' if a[3]==0xffffffff else b''))
        elif name=='MulDiv':v=(a[0]*a[1])//a[2]
        elif name=='GetDeviceCaps':v=self.dpi
        elif name=='RegisterClassW':self.procedure=self.r32(a[0]+4)
        elif name=='AdjustWindowRectEx':
            left,top,right,bottom=struct.unpack('<iiii',self.r(a[0],16));self.w(a[0],struct.pack('<iiii',left-8,top-31,right+8,bottom+8))
        elif name=='SystemParametersInfoW':self.w(a[2],struct.pack('<iiii',0,0,2560,1440))
        elif name=='CreateWindowExW':
            v=self.new_handle({'kind':'window'});self.controls[v]={'class':self.wide(a[1]),'text':self.wide(a[2]),'style':a[3],
                'rect':a[4:8],'parent':a[8],'id':a[9],'enabled':True}
        elif name=='GetWindowTextW':v=self.put_wide(a[1],self.controls[a[0]]['text'],a[2])
        elif name=='SetWindowTextW':self.controls[a[0]]['text']=self.wide(a[1])
        elif name=='GetWindowTextLengthW':v=len(self.controls[a[0]]['text'])
        elif name=='EnableWindow':self.controls[a[0]]['enabled']=bool(a[1])
        elif name=='SendMessageW':
            if a[1]==0xc2:self.controls[a[0]]['text']+=self.wide(a[3])
            elif a[1]==0x143:
                items=self.controls[a[0]].setdefault('items',[]);items.append(self.wide(a[3]));v=len(items)-1
            elif a[1]==0x14e:self.controls[a[0]]['selection']=a[2];v=a[2]
            elif a[1]==0x147:v=self.controls[a[0]].get('selection',0xffffffff)
        elif name=='GetMessageW':
            message=None
            while not message and (self.posted or self.events):
                if self.posted:message=self.posted.pop(0);break
                event=self.events.pop(0);kind=event['kind']
                if kind=='snapshot':
                    self.snapshots[event['name']]={'controls':copy.deepcopy(self.controls),'reads':self.read_count,'boxes':list(self.boxes)}
                elif kind=='language':
                    handle=next(h for h,c in self.controls.items() if c['id']==106)
                    self.controls[handle]['selection']=event['index'];message=(self.main_window,0x111,(1<<16)|106,handle)
                elif kind=='click':message=(self.main_window,0x111,event['id'],0)
                elif kind=='done':message=(self.main_window,0x8002,event['result'],0)
                elif kind=='worker':
                    assert self.worker;self.read_error=self.thread_mode=='read_error'
                    target,arg=self.worker;sp2=sp-8;self.w(sp2,struct.pack('<II',address,arg))
                    self.u.reg_write(UC_X86_REG_ESP,sp2);self.u.reg_write(UC_X86_REG_EIP,target);return
                else:raise AssertionError(event)
            if message:self.w(a[0],struct.pack('<IIIIIII',*message,0,0,0));v=1
            else:v=0xffffffff if self.message_error else 0
        elif name=='IsDialogMessageW':v=0
        elif name=='DispatchMessageW':
            hwnd,message,wp,lp=struct.unpack('<IIII',self.r(a[0],16))
            # Tail-call the actual compiled WndProc; keep DispatchMessage's
            # caller return/stack position and let stdcall pop four arguments.
            target=self.r32(sp);sp2=sp-12;self.w(sp2,struct.pack('<IIIII',target,hwnd,message,wp,lp))
            self.u.reg_write(UC_X86_REG_ESP,sp2);self.u.reg_write(UC_X86_REG_EIP,self.procedure);return
        elif name=='PostMessageW':self.posted.append(tuple(a));v=1
        elif name=='CreateThread':
            assert self.thread_mode
            if self.thread_mode=='fail':v=0
            else:self.worker=(a[2],a[3]);v=self.new_handle({'kind':'worker'})
        elif name=='FormatMessageW':
            self.format_languages.append(a[3]);language=a[3] or self.language_id
            if a[2]==5:text='Zugriff verweigert.\r\n' if language&0x3ff==7 else 'Access is denied.\r\n';v=self.put_wide(a[4],text,a[5])
            else:v=0
        elif name=='SHBrowseForFolderW':self.folder_titles.append(self.wide(self.r32(a[0]+12)));v=0
        elif name=='MessageBoxW':self.boxes.append(self.wide(a[1]));v=1
        elif name=='CoInitializeEx':v=0
        elif name in ['CreateDirectoryW','DeleteFileW','MoveFileExW','WriteFile','CreateToolhelp32Snapshot','Process32FirstW','Process32NextW','SHGetPathFromIDListW']:
            raise AssertionError('Unexpected startup operation '+name)
        self.ret(v,count)
    def run(self):
        start=time.monotonic();self.u.emu_start(self.base+self.p.OPTIONAL_HEADER.AddressOfEntryPoint,0,count=4000000000,timeout=120000000)
        assert self.exit is not None,'GUI startup did not finish'
        assert not self.allocations,('Leaked GUI heap allocations',len(self.allocations))
        return round(time.monotonic()-start,3)
    def by_id(self,number):return next(x for x in self.controls.values() if x['id']==number)
    @property
    def main_window(self):return next(h for h,c in self.controls.items() if not c['parent'])
    def validate_layout(self):
        for child in self.controls.values():
            if child['parent']:
                x,y,w,h=child['rect'];assert x>=0 and y>=0 and w>0 and h>0
                assert x+w<=720*self.dpi//96 and y+h<=564*self.dpi//96,(child,self.dpi)

def main():
    results=[]
    for dpi,language_id,install_label in [(96,0x0407,'Installieren'),(144,0x0409,'Install'),(96,0x0807,'Installieren'),(96,0x040c,'Install')]:
        g=Gui(steam=None,dpi=dpi,language_id=language_id);seconds=g.run();g.validate_layout();assert g.exit==0
        assert not g.by_id(103)['enabled'] and not g.by_id(104)['enabled']
        assert g.by_id(100)['text']=='C:\\Program Files (x86)\\Steam\\steamapps\\common\\wallpaper_engine'
        assert any(x['text']==f'PlaylistResume v{VERSION}' for x in g.controls.values())
        assert g.by_id(103)['text']==install_label
        assert g.by_id(106)['items']==['Deutsch','English']
        assert g.by_id(106)['selection']==(0 if language_id&0x3ff==7 else 1)
        results.append({'case':'display-language default, standard path and disabled buttons','language_id':language_id,'dpi':dpi,'passed':True,'seconds':seconds})
    events=[{'kind':'snapshot','name':'de'},{'kind':'click','id':101},{'kind':'language','index':1},
            {'kind':'snapshot','name':'en'},{'kind':'click','id':101},{'kind':'done','result':1},
            {'kind':'language','index':0},{'kind':'done','result':2},{'kind':'snapshot','name':'de_again'}]
    g=Gui(steam=None,events=events);seconds=g.run();g.validate_layout()
    def saved(g,name,number):return next(x for x in g.snapshots[name]['controls'].values() if x['id']==number)
    assert saved(g,'de',103)['text']=='Installieren' and saved(g,'en',103)['text']=='Install'
    assert saved(g,'en',101)['text']=='Browse …' and saved(g,'en',102)['text']=='Check status'
    assert saved(g,'en',104)['text']=='Restore original' and saved(g,'en',105)['text']=='Close'
    assert saved(g,'de_again',103)['text']=='Installieren'
    assert g.snapshots['de']['reads']==g.snapshots['en']['reads'],'Language switch reread program files'
    assert g.folder_titles[0].startswith('Den Ordner') and g.folder_titles[1].startswith('Select the')
    assert g.boxes[0].startswith('The operation did not complete.') and g.boxes[1].startswith('Die automatische Rücknahme')
    english_text=[x['text'] for x in g.snapshots['en']['controls'].values()]
    assert 'Not found' in english_text and 'Installation status' in english_text and 'Log' in english_text
    assert any(x.startswith('Default location: C:\\') for x in english_text)
    assert any(x.startswith('Complete installer') for x in english_text)
    assert any(x.startswith('Select the folder containing') for x in english_text)
    assert any(x.startswith('See README.md') for x in english_text)
    results.append({'case':'live DE / EN / DE switch; controls, status, folder picker, dialogs; no file rereads','passed':True,'seconds':seconds})
    steam='C:\\Program Files (x86)\\Steam';root='G:\\Steam 日本語\\steamapps\\common\\wallpaper_engine'
    files={steam+'\\steamapps\\libraryfolders.vdf':('"libraryfolders" { "1" { "path" "G:\\\\Steam 日本語" } }').encode()}
    for name in ['wallpaper32.exe','wallpaper64.exe','ui\\dist\\scripts\\scripts.js']:files[root+'\\'+name]=b'unknown version'
    g=Gui(files);seconds=g.run();g.validate_layout();assert g.exit==0
    assert g.by_id(100)['text']==root
    assert not g.by_id(103)['enabled'] and not g.by_id(104)['enabled']
    assert any('Unbekannte oder nicht unterstützte' in x['text'] for x in g.controls.values())
    results.append({'case':'Unicode Steam library and refusal of unknown binaries','passed':True,'seconds':seconds})
    g=Gui(steam=None,message_error=True);g.run();assert g.exit==1
    results.append({'case':'GetMessage error exits safely','passed':True})
    # Real pinned files go through the actual Windows read adapter, C SHA-256
    # and C status engine. No version/status or digest substitutes are used.
    manifests=load_catalog()['current']['files']
    root='C:\\Program Files (x86)\\Steam\\steamapps\\common\\wallpaper_engine'
    files={}
    for m in manifests:
        if m['kind']=='new':data=bytes.fromhex(m['contents_hex'])
        else:
            data=(INPUT/Path(m['filename']).name).read_bytes()
            if m['kind']=='pe':
                b=bytearray(data+bytes.fromhex(m['append_hex']))
                for ch in m['changes']:
                    before,after=bytes.fromhex(ch['before']),bytes.fromhex(ch['after']);at=ch['offset']
                    assert b[at:at+len(before)]==before;b[at:at+len(after)]=after
                data=bytes(b)
            else:
                for r in m['replacements']:
                    before,after=r['before'].encode(),r['after'].encode();assert data.count(before)==1;data=data.replace(before,after)
        assert hashlib.sha256(data).hexdigest()==m['patched_sha256']
        files[root+'\\'+m['filename'].replace('/','\\')]=data
    fingerprint=hashlib.sha256(''.join(m['patched_sha256'] for m in manifests).encode()).hexdigest()
    for receipt,label in [(False,'Unvollständige Installation – Reparatur möglich'),(True,f'Installiert – v{VERSION}')]:
        if receipt:files[root+'\\bin\\playlist-resume-install.json']=json.dumps({'project':'PlaylistResume','version':VERSION,'engine':'2.8.42','payload':fingerprint},separators=(',',':')).encode()+b'\r\n'
        events=[{'kind':'snapshot','name':'de'},{'kind':'language','index':1},{'kind':'snapshot','name':'en'},
                {'kind':'language','index':0},{'kind':'snapshot','name':'de_again'}]
        g=Gui(files,events=events);seconds=g.run();g.validate_layout();assert g.exit==0
        assert g.by_id(103)['enabled'] and g.by_id(104)['enabled']
        assert any(x['text']==label for x in g.controls.values())
        english_label=f'Installed – v{VERSION}' if receipt else 'Incomplete installation – repair available'
        assert any(x['text']==english_label for x in g.snapshots['en']['controls'].values())
        assert saved(g,'de',100)['text']==saved(g,'en',100)['text']==root
        assert all(saved(g,name,103)['enabled'] and saved(g,name,104)['enabled'] for name in ['de','en','de_again'])
        assert len({g.snapshots[n]['reads'] for n in ['de','en','de_again']})==1
        results.append({'case':label+'; real pinned runtime bytes, live translated status and preserved directory/button state','passed':True,'seconds':seconds})
        print(label,'passed',seconds,flush=True)
    # Exercise the actual worker, Windows error callback and posted log messages.
    # A simulated access error blocks the first read; no write API is permitted.
    files={root+'\\'+m['filename'].replace('/','\\'):(INPUT/Path(m['filename']).name).read_bytes() for m in manifests[:3]}
    events=[{'kind':'snapshot','name':'original'},{'kind':'click','id':103},{'kind':'snapshot','name':'locked'},
            {'kind':'worker'},{'kind':'snapshot','name':'error_en'},{'kind':'language','index':0},
            {'kind':'snapshot','name':'error_de'},{'kind':'language','index':1},{'kind':'snapshot','name':'error_en_again'}]
    g=Gui(files,language_id=0x0409,events=events,thread_mode='read_error');seconds=g.run();g.validate_layout();assert g.exit==0
    assert saved(g,'original',103)['enabled'] and not saved(g,'original',104)['enabled']
    assert not saved(g,'locked',106)['enabled'] and not saved(g,'locked',105)['enabled']
    assert any(x['text']=='Installing …' for x in g.snapshots['locked']['controls'].values())
    def log(g,name):return next(x['text'] for x in g.snapshots[name]['controls'].values() if x['class']=='EDIT' and x['style']&0x800)
    english='Read failed: Access is denied.\r\nFiles could not be read\r\nwallpaper32.exe\r\n'
    german='Lesen fehlgeschlagen: Zugriff verweigert.\r\nDateien konnten nicht gelesen werden\r\nwallpaper32.exe\r\n'
    assert log(g,'error_en')==english,repr(log(g,'error_en'))
    assert log(g,'error_de')==german,repr(log(g,'error_de'))
    assert log(g,'error_en_again')==english
    assert saved(g,'error_en',106)['enabled'] and g.boxes[0].startswith('The operation did not complete.')
    assert 0x0407 in g.format_languages and 0x0409 in g.format_languages
    assert len({g.snapshots[n]['reads'] for n in ['error_en','error_de','error_en_again']})==1
    results.append({'case':'actual worker access-error path, language lock, live retranslation of retained log and Windows error code, heap cleanup','passed':True,'seconds':seconds})
    print('worker and translated log passed',seconds,flush=True)
    (OUT/'INSTALLER-GUI-RESULTS.json').write_text(json.dumps({'passed':True,'cases':results,
        'scope':'Actual compiled x86 Windows GUI and event handlers with substituted Win32 APIs. DE/EN selection, OS-language default, status, dialogs, folder-picker text, worker access error, retained log retranslation, control locks, Unicode paths, DPI geometry, stdcall and heap cleanup. No real Windows rendering or mouse interaction.'},indent=2)+'\n')
    print(json.dumps(results,indent=2))
if __name__=='__main__':main()

"""Execute the actual built Windows DLLs, replacing only KERNEL32 calls.

Checks the PE export ABI, relocated images, UTF-16 paths, file serialization,
flush/rename order, profile recreation and DLL-memory restart. Still not a
Windows OS integration test: loader and filesystem APIs are a test platform.
"""
from pathlib import Path
import json
import os
import struct
import zlib
import pefile
from unicorn import Uc,UC_ARCH_X86,UC_MODE_32,UC_MODE_64,UC_HOOK_CODE
from unicorn.x86_const import *

ROOT=Path(__file__).resolve().parents[1]
OUT=Path(os.environ.get('WE_BUILD_OUTPUT',ROOT/'build'))
STACK,HEAP,SP,NODE,ITEMS,RENDERER=0x20000000,0x30000000,0x200f0000,0x30001000,0x30010000,0x30030000
API,RETURN=0x50000000,0x50001000
ROOT_PATH='G:\\Steam\\steamapps\\common\\wallpaper_engine\\'
CACHE=ROOT_PATH+'bin\\playlist-resume.bin'
TRACE=ROOT_PATH+'bin\\playlist-resume.log'
COUNTS={'CloseHandle':1,'CreateFileW':7,'DeleteFileW':1,'DisableThreadLibraryCalls':1,'FlushFileBuffers':1,
        'GetFileSizeEx':2,'GetLastError':0,'GetModuleFileNameW':3,'MoveFileExW':3,'ReadFile':5,'Sleep':1,'WriteFile':5}


class Dll:
    def __init__(self,bits,files,relocated=False):
        self.bits,self.ptr,self.files=bits,bits//8,files
        p=pefile.PE(str(OUT/f'PlaylistResume{bits}.dll'))
        original_base=p.OPTIONAL_HEADER.ImageBase
        self.base=original_base+(0x1000000 if relocated else 0)
        if relocated:p.relocate_image(self.base)
        self.u=Uc(UC_ARCH_X86,UC_MODE_64 if bits==64 else UC_MODE_32)
        self.u.mem_map(self.base,(p.OPTIONAL_HEADER.SizeOfImage+0xfff)&~0xfff)
        self.u.mem_write(self.base,p.get_memory_mapped_image())
        self.u.mem_map(STACK,0x100000);self.u.mem_map(HEAP,0x200000);self.u.mem_map(API,0x2000)
        self.api={};self.handles={};self.next_handle=100;self.last_error=0;self.events=[];self.fail_move=False
        for table in p.DIRECTORY_ENTRY_IMPORT:
            assert table.dll.lower()==b'kernel32.dll'
            for index,item in enumerate(table.imports):
                name=item.name.decode();assert name in COUNTS,name
                addr=API+len(self.api)*16;self.api[addr]=name;self.wp(self.base+table.struct.FirstThunk+index*self.ptr,addr)
        self.exports={x.name.decode():self.base+x.address for x in p.DIRECTORY_ENTRY_EXPORT.symbols}
        self.hook_id=self.u.hook_add(UC_HOOK_CODE,self.hook)
        # Execute the actual minimal DLL entry point too.
        assert self.call(self.base+p.OPTIONAL_HEADER.AddressOfEntryPoint,[self.base,1,0],stdcall=True)==1
        self.node('DISPLAY_TEST_1')

    def close(self):self.u.hook_del(self.hook_id);self.u=None
    def r(self,a,n):return bytes(self.u.mem_read(a,n))
    def w(self,a,b):self.u.mem_write(a,bytes(b))
    def wp(self,a,v):self.w(a,int(v).to_bytes(self.ptr,'little'))
    def rp(self,a):return int.from_bytes(self.r(a,self.ptr),'little')
    def w32(self,a,v):self.w(a,struct.pack('<I',v))
    def r32(self,a):return struct.unpack('<I',self.r(a,4))[0]
    def reg(self,n,v=None):
        reg=globals()['UC_X86_REG_'+n.upper()]
        if v is None:return self.u.reg_read(reg)
        self.u.reg_write(reg,v)
    def string(self,a,s):
        b=s.encode();assert len(b)<=15
        self.w(a,b.ljust(16,b'\0'));self.wp(a+16,len(b));self.wp(a+16+self.ptr,15)
    def wide(self,a):
        b=bytearray()
        for i in range(32768):
            c=self.r(a+2*i,2)
            if c==b'\0\0':return b.decode('utf-16-le')
            b.extend(c)
        raise AssertionError('Unterminated Windows path')
    def ret(self,v,pop=0):
        sp=self.reg('rsp' if self.bits==64 else 'esp');target=self.rp(sp)
        self.reg('rax' if self.bits==64 else 'eax',v&((1<<self.bits)-1))
        self.reg('rsp' if self.bits==64 else 'esp',sp+self.ptr+pop)
        self.reg('rip' if self.bits==64 else 'eip',target)
    def call(self,address,args,stdcall=False):
        if self.bits==64:
            start=SP-8;self.wp(start,RETURN);self.reg('rsp',start)
            for reg,v in zip(['rcx','rdx','r8','r9'],args):self.reg(reg,v)
        else:
            start=SP-4-4*len(args);self.wp(start,RETURN)
            for i,v in enumerate(args):self.wp(start+4+4*i,v)
            self.reg('esp',start)
        self.u.emu_start(address,RETURN,count=8000000)
        assert self.reg('rip' if self.bits==64 else 'eip')==RETURN
        expected=SP if self.bits==64 or stdcall else SP-4*len(args)
        assert self.reg('rsp' if self.bits==64 else 'esp')==expected,'Wrong exported calling convention/stack cleanup'
        return self.reg('rax' if self.bits==64 else 'eax')
    def hook(self,u,address,size,opaque):
        if address==RETURN:u.emu_stop();return
        name=self.api.get(address)
        if not name:return
        n=COUNTS[name];sp=self.reg('rsp' if self.bits==64 else 'esp')
        if self.bits==64:
            args=[self.reg(x) for x in ['rcx','rdx','r8','r9']][:n]
            args += [self.rp(sp+0x28+8*i) for i in range(max(0,n-4))]
        else:args=[self.rp(sp+4+4*i) for i in range(n)]
        value=1
        if name=='GetModuleFileNameW':
            module,dest,capacity=args;assert module==0
            text=ROOT_PATH+f'wallpaper{self.bits}.exe';data=text.encode('utf-16-le')+b'\0\0';assert len(text)<capacity
            self.w(dest,data);value=len(text)
        elif name=='CreateFileW':
            file,access,share,security,disposition,attributes,template=args;file=self.wide(file)
            assert file.startswith(ROOT_PATH+'bin\\') and not security and not template
            if disposition==3 and file not in self.files:self.last_error=2;value=-1
            else:
                if disposition==2:self.files[file]=b''
                self.files.setdefault(file,b'');value=self.next_handle;self.next_handle+=1
                self.handles[value]={'file':file,'at':len(self.files[file]) if access&4 else 0}
        elif name=='GetFileSizeEx':
            handle,out=args;self.w(out,struct.pack('<q',len(self.files[self.handles[handle]['file']])))
        elif name=='ReadFile':
            handle,dest,count,read,overlapped=args;assert overlapped==0
            h=self.handles[handle];data=self.files[h['file']][h['at']:h['at']+count]
            self.w(dest,data);self.w32(read,len(data));h['at']+=len(data)
        elif name=='WriteFile':
            handle,src,count,written,overlapped=args;assert overlapped==0
            h=self.handles[handle];data=self.r(src,count);old=self.files[h['file']]
            self.files[h['file']]=old[:h['at']]+data+old[h['at']+count:];h['at']+=count;self.w32(written,count)
            self.events.append(('write',h['file']))
        elif name=='FlushFileBuffers':self.events.append(('flush',self.handles[args[0]]['file']))
        elif name=='CloseHandle':self.handles.pop(args[0])
        elif name=='MoveFileExW':
            src,dest,flags=args;src,dest=self.wide(src),self.wide(dest);assert flags==9
            if self.fail_move:value=0;self.last_error=5
            else:self.files[dest]=self.files.pop(src);self.events.append(('rename',dest))
        elif name=='DeleteFileW':self.files.pop(self.wide(args[0]),None)
        elif name=='GetLastError':value=self.last_error
        elif name=='Sleep':value=0
        elif name=='DisableThreadLibraryCalls':assert args[0]==self.base
        self.ret(value,0 if self.bits==64 else 4*n)

    @property
    def flags_off(self):return 0x74 if self.bits==64 else 0x48
    @property
    def index_off(self):return 0x78 if self.bits==64 else 0x4c
    def node(self,monitor):
        self.w(NODE,b'\0'*0x200)
        self.string(NODE+(0x10 if self.bits==64 else 8),monitor)
        p=NODE+(0x38 if self.bits==64 else 0x24);desc=0x48 if self.bits==64 else 0x34
        self.wp(p,ITEMS);self.wp(p+self.ptr,ITEMS+desc*10)
        self.w32(NODE+(0x70 if self.bits==64 else 0x44),1);self.w32(NODE+(0x6c if self.bits==64 else 0x40),1)
        self.w32(NODE+self.flags_off,0x28)
        self.string(NODE+(0xa0 if self.bits==64 else 0x68),'')
        for i in range(10):self.string(ITEMS+desc*i,f'WP_{i+1:05}');self.string(ITEMS+desc*i+(0x28 if self.bits==64 else 0x1c),'')
    def prepare(self):self.call(self.exports['ResumePrepare'],[NODE,0x7777])
    def commit(self,position,intro=False,actual_position=None):
        if intro:self.w32(NODE+self.flags_off,self.r32(NODE+self.flags_off)|0x40)
        else:self.w32(NODE+self.flags_off,self.r32(NODE+self.flags_off)&~0x40);self.w32(NODE+self.index_off,position)
        self.string(RENDERER+(0xe0 if self.bits==64 else 0x94),f'WP_{actual_position or position:05}')
        self.string(RENDERER+(0x120 if self.bits==64 else 0xc4),'')
        self.call(self.exports['ResumeCommit'],[0x7777,RENDERER])


def main():
    results={}
    for bits in [64,32]:
        files={};d=Dll(bits,files)
        d.prepare();assert d.r32(NODE+d.index_off)==0;d.commit(1,intro=True);assert CACHE not in files
        d.prepare();d.commit(4)
        data=files[CACHE];assert data[:8]==b'WPRS0001' and len(data)==48 and struct.unpack_from('<I',data,36)[0]==3
        assert zlib.crc32(data[16:])==struct.unpack_from('<I',data,12)[0]
        write_events=[x[0] for x in d.events if 'playlist-resume.tmp' in x[1] or x[0]=='rename']
        assert write_events[-3:]==['write','flush','rename']
        d.node('DISPLAY_TEST_1');d.prepare();assert d.r32(NODE+d.index_off)==3;d.commit(4)
        d.close()
        # New PE image/BSS and a different image base. Only simulated files survive.
        d=Dll(bits,files,relocated=True);d.prepare();assert d.r32(NODE+d.index_off)==4
        before=files[CACHE];d.commit(1,intro=True);assert files[CACHE]==before
        d.node('DISPLAY_TEST_1');d.prepare();assert d.r32(NODE+d.index_off)==4
        d.commit(1,intro=True);assert files[CACHE]==before
        d.prepare();d.commit(4);assert b'startup' in files[TRACE] and b'activate' in files[TRACE]
        # Execute the actual Windows failure/cleanup branch as well.
        d.fail_move=True;d.prepare();d.commit(5);assert files[CACHE]!=b'' and struct.unpack_from('<I',files[CACHE],36)[0]==3
        assert b'write-failed' in files[TRACE]
        d.fail_move=False;d.node('DISPLAY_TEST_1');d.prepare();assert d.r32(NODE+d.index_off)==4;d.commit(5)
        assert struct.unpack_from('<I',files[CACHE],36)[0]==4
        # Actual DLL code consumes a UI mark, updates native state, and only
        # persists when the selected renderer really matches the requested row.
        d.w32(NODE+d.flags_off,d.r32(NODE+d.flags_off)|0x100|(2<<16));d.prepare()
        assert d.r32(NODE+d.index_off)==1 and not d.r32(NODE+d.flags_off)&0xffff0140
        assert d.r(NODE+(0xe1 if bits==64 else 0x99),1)==b'\0'
        d.commit(2);assert struct.unpack_from('<I',files[CACHE],36)[0]==1
        assert b'manual-checkpoint' in files[TRACE]
        before=files[CACHE]
        d.w32(NODE+d.flags_off,d.r32(NODE+d.flags_off)|0x100|(8<<16));d.prepare()
        d.commit(8,actual_position=9)
        assert files[CACHE]==before and b'renderer-mismatch' in files[TRACE]
        # Another monitor's checkpoint is not changed by a manual selection.
        d.node('DISPLAY_TEST_2');d.prepare();d.commit(1,intro=True);d.prepare();d.commit(6)
        d.node('DISPLAY_TEST_1')
        d.w32(NODE+d.flags_off,d.r32(NODE+d.flags_off)|0x100|(10<<16));d.prepare();d.commit(10)
        indexes=sorted(struct.unpack_from('<I',files[CACHE],36+32*i)[0] for i in range(2))
        assert indexes==[5,9]
        d.close()
        # Upgrade compatibility: old format content can still be read, and the
        # next regular write uses the neutral, independently versioned format.
        files[CACHE]=b'PIRS0003'+files[CACHE][8:]
        d=Dll(bits,files);d.prepare();assert d.r32(NODE+d.index_off)==10
        d.commit(1,intro=True);assert files[CACHE][:8]==b'PIRS0003'
        d.w32(NODE+d.flags_off,d.r32(NODE+d.flags_off)|0x100|(1<<16));d.prepare();d.commit(1)
        assert files[CACHE][:8]==b'WPRS0001'
        assert sorted(struct.unpack_from('<I',files[CACHE],36+32*i)[0] for i in range(2))==[0,5]
        d.close()
        results[str(bits)]={'status':'passed','actual_windows_dll_executed':True,
            'checks':['export ABI','DllMain','kernel32 argument ABI','UTF-16 paths','native binary cache','CRC32','flush then rename',
                      'profile recreation','DLL-memory restart','ASLR','intro checkpoint preservation','failed rename cleanup and retry',
                      'explicit manual selection','manual WP1 during prelude','renderer mismatch preserves checkpoint',
                      'separate monitor checkpoints','legacy state migration'],
            'limit':'KERNEL32 and PE loading are test substitutes. This is not a Windows OS run.'}
        print(bits,'compiled Windows DLL emulation passed',flush=True)
    (OUT/'R04-DLL-RESULTS.json').write_text(json.dumps(results,indent=2)+'\n')

if __name__=='__main__':main()

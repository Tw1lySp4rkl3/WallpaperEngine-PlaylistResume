"""Exercise R02 machine code and native load/select/capture slices in Unicorn.

This deliberately reports its seams: JSON access, file existence, heap/string
ownership and vector allocations are substitutes. Windows rendering, native
file flushing and process startup are not run here.
"""
from pathlib import Path
import json
import os
import struct
import pefile
from unicorn import Uc, UC_ARCH_X86, UC_MODE_32, UC_MODE_64, UC_HOOK_CODE
from unicorn.x86_const import *

ROOT = Path(__file__).resolve().parents[1]
INPUT = Path(os.environ.get('WE_ORIGINALS',ROOT / "upload"))
OUT = Path(os.environ.get('WE_BUILD_OUTPUT',ROOT / "analysis" / "r02"))
STACK, HEAP, SP = 0x20000000, 0x30000000, 0x200f0000
NODE, ITEMS, RENDERER, STATE = HEAP+0x1000, HEAP+0x10000, HEAP+0x30000, HEAP+0x40000
CONTAINER, SENTINEL, JSON_OBJECT, JSON_VALUE = HEAP+0x50000, HEAP+0x51000, HEAP+0x52000, HEAP+0x53000


def unpack_state(data):
    pos = 0
    def number():
        nonlocal pos
        value, = struct.unpack_from('<I', data, pos)
        pos += 4
        return value
    def string():
        nonlocal pos
        n = number()
        value = data[pos:pos+n].decode('utf8')
        assert len(data[pos:pos+n]) == n
        pos += n
        return value
    assert string() == 'PLPV0005'
    roots = []
    for _ in range(number()):
        name, records = string(), []
        for _ in range(number()):
            monitor, checkpoint, file, preset = string(), number(), string(), string()
            bag = [(string(), string()) for _ in range(number())]
            records.append(dict(monitor=monitor, checkpoint=checkpoint, file=file, preset=preset, bag=bag))
        roots.append((name, records))
    assert pos == len(data)
    return roots


def pack_state(roots):
    output = bytearray()
    def number(n): output.extend(struct.pack('<I', n))
    def string(s):
        b = s.encode('utf8')
        number(len(b)); output.extend(b)
    string('PLPV0005'); number(len(roots))
    for name, records in roots:
        string(name); number(len(records))
        for r in records:
            string(r['monitor']); number(r['checkpoint']); string(r['file']); string(r['preset'])
            number(len(r['bag']))
            for file, preset in r['bag']: string(file); string(preset)
    return bytes(output)


class Engine:
    images = {}
    def __init__(self, bits, count=10, checkpoint=0, flags=0x28, mode=1, order=1,
                 paths=None, presets=None, invalid=(), relocated=False, original=False):
        self.bits, self.ptr = bits, bits//8
        self.base = (0x140000000 if bits == 64 else 0x400000) + (0x1000000 if relocated else 0)
        name = f'wallpaper{bits}.exe'
        binary = (INPUT if original else OUT)/name
        key = (str(binary), self.base)
        if key not in self.images:
            pe = pefile.PE(str(binary))
            if pe.OPTIONAL_HEADER.ImageBase != self.base: pe.relocate_image(self.base)
            self.images[key] = pe.OPTIONAL_HEADER.SizeOfImage, pe.get_memory_mapped_image()
        size, image = self.images[key]
        self.u = Uc(UC_ARCH_X86, UC_MODE_64 if bits == 64 else UC_MODE_32)
        self.u.mem_map(self.base, (size+0xfff)&~0xfff)
        self.u.mem_write(self.base, image)
        self.u.mem_map(STACK, 0x100000)
        self.u.mem_map(HEAP, 0x1000000)
        self.heap_next = HEAP+0x80000
        self.count, self.invalid = count, set(invalid)
        self.playlist = NODE+(0x38 if bits == 64 else 0x24)
        self.desc = 0x48 if bits == 64 else 0x34
        self.preset_offset = 0x28 if bits == 64 else 0x1c
        self.flag_offset, self.index_offset = (0x3c,0x40) if bits == 64 else (0x24,0x28)
        self.mode_offset, self.order_offset = (0x38,0x34) if bits == 64 else (0x20,0x1c)
        self.start_offset, self.intro_offset = (0xe1,0xe2) if bits == 64 else (0x99,0x9a)
        self.paths = paths or [f'WP_{i+1:05}' for i in range(count)]
        self.presets = presets or ['']*count
        self.init_playlist(self.playlist, ITEMS, flags, checkpoint, mode, order)
        self.u.mem_write(NODE+self.start_offset, b'\1\0')
        self.settings = {}
        self.stop = None
        self.phase = ''
        self.handle = self.u.hook_add(UC_HOOK_CODE, self.hook)

    def close(self): self.u.hook_del(self.handle); self.u = None
    def alloc(self, n):
        p = self.heap_next; self.heap_next += (n+15)&~15
        assert self.heap_next < HEAP+0x1000000
        return p
    def write(self,a,b): self.u.mem_write(a,bytes(b))
    def read(self,a,n): return bytes(self.u.mem_read(a,n))
    def w32(self,a,v): self.write(a,struct.pack('<I',v))
    def r32(self,a): return struct.unpack('<I',self.read(a,4))[0]
    def wp(self,a,v): self.write(a,v.to_bytes(self.ptr,'little'))
    def rp(self,a): return int.from_bytes(self.read(a,self.ptr),'little')
    def reg(self,name,value=None):
        reg = globals()['UC_X86_REG_'+name.upper()]
        if value is None: return self.u.reg_read(reg)
        self.u.reg_write(reg,value)
    @property
    def spname(self): return 'rsp' if self.bits == 64 else 'esp'
    @property
    def bpname(self): return 'rbp' if self.bits == 64 else 'ebp'
    @property
    def ipname(self): return 'rip' if self.bits == 64 else 'eip'
    def ret(self,value=0,pop=0):
        sp = self.reg(self.spname)
        self.reg('rax' if self.bits == 64 else 'eax',value)
        target = self.rp(sp)
        self.reg(self.spname,sp+self.ptr+pop)
        self.reg(self.ipname,target)
    def string(self,a,s):
        data=s.encode('utf8')
        if len(data)<=15:
            self.write(a,data.ljust(16,b'\0'))
            cap=15
        else:
            ptr=self.alloc(len(data)+1); self.write(ptr,data+b'\0'); self.wp(a,ptr);cap=len(data)
        self.wp(a+0x10,len(data));self.wp(a+0x10+self.ptr,cap)
    def get_string(self,a):
        n=self.rp(a+0x10);cap=self.rp(a+0x10+self.ptr)
        return self.read(a if cap<=15 else self.rp(a),n).decode('utf8')
    def cstring(self,a):
        b=bytearray()
        while self.read(a+len(b),1)!=b'\0': b.extend(self.read(a+len(b),1))
        return b.decode('utf8')
    def init_playlist(self,p,items,flags,checkpoint,mode=1,order=1):
        self.wp(p,items); self.wp(p+self.ptr,items+self.count*self.desc); self.wp(p+self.ptr*2,items+self.count*self.desc)
        self.w32(p+self.flag_offset,flags); self.w32(p+self.index_offset,checkpoint)
        self.w32(p+self.mode_offset,mode);self.w32(p+self.order_offset,order)
        self.write(p+(0x30 if self.bits==64 else 0x18),struct.pack('<f',30.0))
        for i,(path,preset) in enumerate(zip(self.paths,self.presets)):
            self.string(items+i*self.desc,path);self.string(items+i*self.desc+self.preset_offset,preset)

    def run(self,start,end,phase):
        self.phase=phase; self.stop=self.base+end
        self.u.emu_start(self.base+start,self.stop,count=1000000)
        assert self.reg(self.ipname)==self.stop,(phase,hex(self.reg(self.ipname)))

    def hook(self,u,address,size,_):
        if address==self.stop: u.emu_stop();return
        a=address-self.base
        cx=self.reg('rcx' if self.bits==64 else 'ecx');sp=self.reg(self.spname)
        arg=lambda i:self.rp(sp+self.ptr*(i+1))
        if self.bits==64:
            dx=self.reg('rdx');r8=self.reg('r8')
            if a==0x86de0:
                key=self.read(dx,r8-dx).decode();value=self.settings.get(key)
                self.json_value(value)
                self.ret(JSON_VALUE);return
            if a==0x86300:self.ret(self.rp(cx));return
            if a==0x68f50:self.write(cx,self.read(dx,0x48));self.ret(cx);return
            if a==0x647b0:self.ret(int(self.get_string(cx) not in self.invalid));return
            if a==0xf880:self.string(cx,self.read(dx,r8).decode());self.ret(cx);return
            if a in (0xde00,0x16fc0):self.string(cx,self.get_string(dx));self.ret(cx);return
            if a==0x17170:self.string(cx,self.cstring(dx));self.ret(cx);return
            if a in (0x17240,0x38cc0):self.ret();return
            if a==0x31fa0:self.string(cx,'');self.ret(cx);return
            if a==0x79960 or a==0x79be0:self.ret(CONTAINER);return
            if a==0x313b0:self.wp(dx,STATE);self.ret(dx);return
            if a==0x79340:self.ret(NODE+0x30);return
            if a==0x7a780:self.wp(cx+self.ptr,self.rp(cx));self.ret();return
            if a==0x64990:self.ret((self.rp(cx+8)-self.rp(cx))//0x48);return
            if a==0x7a870:
                self.write(cx,self.read(dx,24));self.ret(cx);return
            if a==0x4210f0:self.write(cx,self.read(dx,r8));self.ret(cx);return
            if a==0x420ff0:self.ret(int(self.read(cx,r8)!=self.read(dx,r8)));return
            if a==0x68f20:
                self.write(cx,b'\0'*0x48);self.string(cx,'');self.string(cx+0x28,'');self.ret(cx);return
            if a==0x7ab90:
                # Bag contents do not affect sorted selection. Copy sufficient
                # descriptor storage so the loader's real loop can execute.
                self.ret();return
            allowed=[(0x67eb9,0x6839d),(0x6c181,0x6c187),(0x75e02,0x75e9d),
                     (0x6bc5a,0x6be56),(0x67250,0x674bb),(0x6effa,0x6f0a5),
                     (0x67070,0x67243),(0x66d11,0x66d16),(0xd0f0,0xd13c)]
            section=(0x525000,0x526000)
        else:
            if a==0x681a0:
                start,end=arg(0),arg(1);key=self.read(start,end-start).decode();v=self.settings.get(key)
                self.json_value(v)
                self.ret(JSON_VALUE,8);return
            if a==0x67b20:self.ret(self.rp(cx));return
            if a==0x52c00:self.write(cx,self.read(arg(0),0x34));self.ret(cx,4);return
            if a==0x14ea0:self.ret(int(self.get_string(cx) not in self.invalid));return
            if a==0xdbe0:self.string(cx,self.read(arg(0),arg(1)).decode());self.ret(cx,8);return
            if a==0xc050:self.string(cx,self.get_string(arg(0)));self.ret(cx,4);return
            if a==0x14460:self.string(cx,self.cstring(arg(0)));self.ret(cx,4);return
            if a in (0x14520,0x2da30):self.ret();return
            if a==0x29700:self.string(cx,'');self.ret(cx);return
            if a==0x5e510:self.ret(CONTAINER,4);return
            if a==0x29040:self.wp(arg(0),STATE);self.ret(arg(0),8);return
            if a==0x5e6e0:self.wp(cx+4,self.rp(cx));self.ret();return
            if a==0x4ff40:self.ret((self.rp(cx+4)-self.rp(cx))//0x34);return
            if a==0x5f880:self.wp(arg(0),NODE);self.ret(arg(0),8);return
            if a==0x5ff60:
                src,n=arg(0),arg(1);self.wp(cx,src);self.wp(cx+4,src+n*0x34);self.wp(cx+8,src+n*0x34)
                self.ret(cx,8);return
            if a==0x5e7d0:self.write(cx,self.read(arg(0),12));self.ret(cx,4);return
            if a==0x52bc0:
                self.write(cx,b'\0'*0x34);self.string(cx,'');self.string(cx+0x1c,'');self.ret(cx);return
            if a==0x5f0e0:self.ret(0,4);return
            if a==0x15020:self.ret(cx,4);return
            if a in (0x4d3e0,0x13b70):self.ret();return
            allowed=[(0x523a4,0x52847),(0x55705,0x5570a),(0x5c939,0x5c9b8),
                     (0x4fec0,0x4ff33),(0x551bd,0x55459),(0x51a20,0x51aaa),(0x518d3,0x518d8),
                     (0x116c0,0x11740),(0x57f4c,0x5801a)]
            section=(0x421000,0x422000)
        if not any(lo<=a<hi for lo,hi in allowed+[section]):
            raise AssertionError(f'{self.bits} unexpected {address:x} phase {self.phase}')

    @property
    def checkpoint(self):return self.r32(self.playlist+self.index_offset)
    def json_value(self,value):
        if isinstance(value,bool):kind,data=5,struct.pack('<Q',int(value))
        elif isinstance(value,int):kind,data=(1,struct.pack('<q',value)) if value<0 else (2,struct.pack('<Q',value))
        elif isinstance(value,float):kind,data=3,struct.pack('<d',value)
        else:kind,data=0,b'\0'*8
        self.write(JSON_VALUE,data+bytes([kind]))
    @property
    def flags(self):return self.r32(self.playlist+self.flag_offset)
    def parse_settings(self,settings,p=None):
        self.settings=settings;p=p or self.playlist
        self.write(JSON_OBJECT+8,b'\7')
        self.w32(p+self.flag_offset,0)
        self.reg(self.spname,SP)
        if self.bits==64:
            self.reg('rbx',JSON_OBJECT);self.reg('r14',p)
            self.run(0x75e02,0x75e9d,'parse settings')
        else:
            self.reg('esi',JSON_OBJECT);self.reg('edi',p)
            self.run(0x5c939,0x5c9b8,'parse settings')
        return self.r32(p+self.flag_offset)

    def select(self):
        self.reg(self.spname,SP)
        if self.bits==64:
            self.reg('rbp',SP+0xc8);self.reg('r14',NODE);self.reg('r13',self.flags>>4&1)
            self.reg('r15',0);self.reg('rdi',0);self.wp(SP+0x30,NODE)
            self.run(0x67eb9,0x6839d,'select')
            result=SP+0x40
        else:
            bp=SP+0x180
            self.reg('ebp',bp);self.reg('ebx',NODE);self.reg('edx',0);self.reg('ecx',self.flags>>4&1)
            self.wp(bp-8,NODE);self.w32(bp-0x10,self.flags>>4&1)
            self.run(0x523a4,0x52847,'select')
            result=bp-0x74
        path=self.get_string(result);preset=self.get_string(result+self.preset_offset)
        # Renderer creation is an external seam, represented by its actual
        # filepath/preset fields for the subsequent native capture slice.
        self.wp(NODE+(0x30 if self.bits==64 else 0x20),RENDERER)
        self.string(RENDERER+(0xe0 if self.bits==64 else 0x94),path)
        self.string(RENDERER+(0x120 if self.bits==64 else 0xc4),preset)
        return self.paths.index(path)+1

    def reconcile(self,selected=1):
        self.reg(self.spname,SP)
        if self.bits==64:
            self.reg('rbx',NODE);self.reg('rdi',selected-1)
            self.run(0x6c181,0x6c187,'startup reconcile')
        else:
            self.reg('esi',NODE);self.reg('ecx',self.playlist)
            text=HEAP+0x70000;self.string(text,self.paths[selected-1]);self.reg('edx',text)
            self.run(0x55705,0x5570a,'startup reconcile')

    def cold_load(self,record):
        """Run native restoration and struct-copy instructions, not a seeded index."""
        self.reg(self.spname,SP)
        if self.bits==64:
            bp=SP+0x100;self.reg('rbp',bp)
            temp=bp+0x148
            self.init_playlist(temp,self.alloc(self.count*self.desc),0x28,0)
            self.parse_settings({'beginfirst':True,'playintro':False,'rememberposition':True},temp)
            self.reg('rbp',bp);self.reg(self.spname,SP)
            self.w32(bp+0x3a0,1);self.wp(CONTAINER+8,SENTINEL)
            self.wp(self.base+0x4df5a0,HEAP+0x60000);self.write(HEAP+0x60000,b'wallpaperconfig\0')
            self.wp(self.base+0x4e5330,SENTINEL)
            self.wp(STATE+0x38,0);self.wp(STATE+0x40,0)
            self.w32(STATE+0x34,record['checkpoint']);self.write(STATE+0x30,struct.pack('<f',123.0))
            self.string(STATE+0x50,record['file']);self.string(STATE+0x70,record['preset'])
            self.string(bp+0x1b0,'');self.string(bp+0x1d0,'')
            self.reg('xmm6',int.from_bytes(struct.pack('<f',60.0).ljust(16,b'\0'),'little'))
            self.run(0x6bc5a,0x6be56,'cold restore')
        else:
            temp=SP+0x174
            self.init_playlist(temp,self.alloc(self.count*self.desc),0x28,0)
            self.parse_settings({'beginfirst':True,'playintro':False,'rememberposition':True},temp)
            self.reg(self.spname,SP)
            self.write(SP+0x3c,b'\1');self.wp(CONTAINER+4,SENTINEL)
            self.wp(self.base+0x3f3f70,HEAP+0x60000);self.write(HEAP+0x60000,b'wallpaperconfig\0')
            self.wp(STATE+0x28,0);self.wp(STATE+0x2c,0)
            self.w32(STATE+0x24,record['checkpoint']);self.write(STATE+0x20,struct.pack('<f',123.0))
            self.string(STATE+0x34,record['file']);self.string(STATE+0x4c,record['preset'])
            self.string(SP+0x1b8,'');self.string(SP+0x1d0,'')
            self.run(0x551bd,0x55459,'cold restore')
        assert self.checkpoint==record['checkpoint'],('loader',self.bits,self.checkpoint,record['checkpoint'])
        assert self.read(NODE+self.start_offset,1)==b'\1'

    def apply_same_playlist(self,changed=None,enabled=True):
        new=HEAP+0x62000;items=self.alloc(self.count*self.desc)
        self.init_playlist(new,items,0x28 if enabled else 8,0)
        if changed=='path':self.string(items+self.desc,self.paths[1]+'_changed')
        if changed=='preset':self.string(items+self.desc+self.preset_offset,'different preset')
        self.reg(self.spname,SP)
        if self.bits==64:
            self.reg('rcx',self.playlist);self.reg('rdx',new)
            self.run(0x66d11,0x66d16,'UI apply')
        else:
            self.reg('ecx',self.playlist);self.wp(SP,new)
            self.run(0x518d3,0x518d8,'UI apply')

    def capture(self):
        if self.bits!=64:
            self.reg(self.spname,SP);self.reg('esi',NODE);self.reg('ecx',SP+0x7c);self.reg('edx',SP+0x94)
            self.run(0x57f4c,0x5801a,'capture for save')
            return dict(checkpoint=self.r32(SP+0x6c),file=self.get_string(SP+0x7c),preset=self.get_string(SP+0x94))
        bp=SP+0x100
        self.reg(self.spname,SP);self.reg('rbp',bp);self.reg('rbx',NODE);self.reg('r12',0)
        self.run(0x6effa,0x6f0a5,'capture for save')
        return dict(checkpoint=self.r32(bp-0x4c),file=self.get_string(bp-0x30),preset=self.get_string(bp-0x10))


def main():
    state_bytes=(INPUT/'playliststate.bin').read_bytes()
    roots=unpack_state(state_bytes)
    assert pack_state(roots)==state_bytes
    results={}
    for bits in [64,32]:
        for remember in [False,True]:
            for intro in [False,True]:
                e=Engine(bits)
                flags=e.parse_settings({'beginfirst':True,'playintro':intro,'rememberposition':remember})
                assert bool(flags&0x20)==remember
                assert bool(flags&0x10)==(intro and not remember)
                e.close()
        checkpoints=0
        for n in [2,3,10,132,133]:
            for last in range(1,n+1):
                e=Engine(bits,n,last)
                assert e.select()==1
                assert e.checkpoint==last and e.flags&0x40
                assert e.read(NODE+e.intro_offset,1)==b'\0'
                e.reconcile();assert e.checkpoint==last
                assert e.select()==last,(bits,n,last)
                assert e.checkpoint==last and not e.flags&0x40
                assert e.select()==last%n+1
                e.close();checkpoints+=1
            print(bits,'checkpoint cases for',n,'passed',flush=True)
        e=Engine(bits,10,0)
        assert [e.select() for _ in range(13)]==[1,2,3,4,5,6,7,8,9,10,1,2,3]
        e.close()
        # Renderer reuse returns early for identical file/preset. Start and
        # resume still need a fresh timer, including the 1 -> 1 case.
        for last in [1,4,9,10]:
            e=Engine(bits)
            e.cold_load(dict(checkpoint=last,file=f'WP_{last:05}',preset=''))
            elapsed=NODE+(0x7c if bits==64 else 0x50)
            assert e.r32(elapsed)!=0
            assert e.select()==1 and e.r32(elapsed)==0
            e.write(elapsed,struct.pack('<f',1800.0))
            assert e.select()==last and e.r32(elapsed)==0
            e.close()
        for old_intro in [False,True]:
            e=Engine(bits,10,9)
            if old_intro:assert e.select()==1
            e.apply_same_playlist()
            assert e.checkpoint==9
            assert bool(e.flags&0x40)==old_intro
            e.close()
        for changed in ['path','preset']:
            e=Engine(bits,10,9)
            e.apply_same_playlist(changed=changed)
            assert e.checkpoint==0
            e.close()
        e=Engine(bits,10,9);e.apply_same_playlist(enabled=False);assert e.checkpoint==0;e.close()
        # Full fixture flow across state serialization and the native load
        # slice: manual-like repeated selector calls, capture, restart and wrap.
        record=dict(monitor='test',checkpoint=4,file='WP_00004',preset='',bag=[])
        for repeat in range(3):
            e=Engine(bits)
            e.cold_load(record)
            assert e.select()==1;e.reconcile()
            captured=e.capture();assert captured['checkpoint']==4
            record=unpack_state(pack_state([('wallpaperconfig',[dict(record,**captured)])]))[0][1][0]
            e.close()
        e=Engine(bits);e.cold_load(record)
        assert [e.select() for _ in range(10)]==[1,4,5,6,7,8,9,10,1,2]
        captured=e.capture();assert captured['checkpoint']==2 and captured['file']=='WP_00002'
        e.close()
        # Test the supplied three-monitor data with its real long paths, presets
        # and main playlist arrays, restoring each native checkpoint.
        config=json.loads((INPUT/'config.json').read_text())
        native_records=roots[0][1]
        matched=0
        active=next(user['general']['wallpaperconfig']['selectedwallpapers'] for user in config.values() if isinstance(user,dict) and 'wallpaperconfig' in user.get('general',{}))
        for record in native_records:
            playlist=active[record['monitor']]['playlist']
            paths=[i if isinstance(i,str) else i['file'] for i in playlist['items']]
            presets=['' if isinstance(i,str) else i.get('preset','') for i in playlist['items']]
            e=Engine(bits,len(paths),paths=paths,presets=presets)
            e.cold_load(record)
            assert e.select()==1;e.reconcile()
            assert e.select()==record['checkpoint']
            e.close();matched+=1
        # ASLR smoke test exercises new string addresses and branch targets.
        e=Engine(bits,10,9,relocated=True)
        assert e.parse_settings({'beginfirst':True,'playintro':False,'rememberposition':True})==0x28
        assert [e.select(),e.select(),e.select(),e.select()]==[1,9,10,1]
        e.apply_same_playlist();assert e.checkpoint==1;e.close()
        # Disabled feature follows the original startup path in all native modes.
        for flags in [0,1,2,8,0x18,0x20]:
            for mode in range(5):
                for order in [0,1]:
                    a=Engine(bits,flags=flags,mode=mode,order=order,checkpoint=4,original=True)
                    b=Engine(bits,flags=flags,mode=mode,order=order,checkpoint=4)
                    assert a.select()==b.select()==1
                    assert a.checkpoint==b.checkpoint==1
                    a.close();b.close()
        for mode in range(5):
            for order in [0,1]:
                if (mode,order)==(1,1):continue
                a=Engine(bits,flags=0x28,mode=mode,order=order,checkpoint=4,original=True)
                b=Engine(bits,flags=0x28,mode=mode,order=order,checkpoint=4)
                assert a.select()==b.select()==1 and a.checkpoint==b.checkpoint==1
                a.close();b.close()
        results[str(bits)]=dict(status='passed',checkpoint_cases=checkpoints,real_monitor_fixtures=matched,
                               scope='Native parser/load/select/reconciliation/UI-copy/save-capture instructions; substituted JSON, allocation, ownership and file checks. State-file round trips use the documented Python codec. No Windows run.')
        print(bits,'passed',flush=True)
    (OUT/'NATIVE-RESULTS.json').write_text(json.dumps(results,indent=2)+'\n')


if __name__=='__main__':main()

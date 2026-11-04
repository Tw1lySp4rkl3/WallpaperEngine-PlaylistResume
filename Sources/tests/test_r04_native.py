"""Native R04 selection hooks + the actual C checkpoint core, both layouts.

Unicorn runs the EXE hooks and native selector instructions. Calls at the DLL
import boundary execute the same resume_core.c as in the Windows DLL, compiled
for a Linux test host; only its file/lock platform is replaced. Renderer creation,
JSON/string ownership and Windows itself remain explicit seams.
"""
from pathlib import Path
import ctypes
import hashlib
import json
import os
import struct
import subprocess
import zlib

import test_r02_native as native

ROOT=Path(__file__).resolve().parents[1]
OUT=Path(os.environ.get('WE_BUILD_OUTPUT',ROOT/'build'))
SOURCE=Path(os.environ.get('PIRS_SOURCE',ROOT/'src'))
native.OUT=OUT
HEAP,NODE,SP=native.HEAP,native.NODE,native.SP
API_PREPARE,API_COMMIT=0x50000000,0x50000010


class Core:
    def __init__(self,bits):
        dest=OUT/f'core{bits}.so'
        args=['gcc','-shared','-fPIC','-O2','-Wall','-Wextra','-Werror','-DPIRS_TEST']
        if bits==32:args+=['-DPIRS_LAYOUT32']
        args+=['-o',str(dest),str(SOURCE/'resume_core.c'),str(SOURCE/'resume_test_platform.c')]
        subprocess.run(args,check=True)
        self.lib=ctypes.CDLL(str(dest))
        self.lib.ResumePrepare.argtypes=[ctypes.c_void_p,ctypes.c_size_t]
        self.lib.ResumeCommit.argtypes=[ctypes.c_size_t,ctypes.c_void_p]
        self.lib.ResumePrepare.restype=None;self.lib.ResumeCommit.restype=None
        self.lib.PirsResetForTest.restype=None;self.lib.PirsClearDiskForTest.restype=None
        self.lib.PirsDiskForTest.argtypes=[ctypes.c_void_p];self.lib.PirsDiskForTest.restype=ctypes.c_uint
        self.clear()

    def clear(self):self.lib.PirsResetForTest();self.lib.PirsClearDiskForTest()
    def restart(self):self.lib.PirsResetForTest()
    def records(self):
        buf=ctypes.create_string_buffer(16400);n=self.lib.PirsDiskForTest(buf)
        if not n:return []
        b=buf.raw[:n];assert b[:8]==b'WPRS0001'
        count,crc=struct.unpack_from('<II',b,8)
        assert n==16+count*32 and zlib.crc32(b[16:])==crc
        return [dict(zip(['a','b','count','index','used'],struct.unpack_from('<QQIIQ',b,16+i*32))) for i in range(count)]


class Engine(native.Engine):
    def __init__(self,core,bits,*args,monitor='DISPLAY_TEST_1',**kwargs):
        self.core=core
        self.dispatches=[]
        self.request_payload={}
        self.persisted_payload={}
        super().__init__(bits,*args,**kwargs)
        self.string(NODE+(0x10 if bits==64 else 8),monitor)
        self.u.mem_map(API_PREPARE,0x1000)
        self.u.mem_write(API_PREPARE,b'\xc3'*0x20)
        manifest=json.loads((OUT/f'wallpaper{bits}.patch.json').read_text())
        self.wp(self.base+manifest['callback_iat_rvas']['prepare'],API_PREPARE)
        self.wp(self.base+manifest['callback_iat_rvas']['commit'],API_COMMIT)

    def hook(self,u,address,size,opaque):
        if address in [API_PREPARE,API_COMMIT]:
            end=max(self.heap_next-HEAP,0x80000)
            ctypes.memmove(HEAP,self.read(HEAP,end),end)
            if self.bits==64:
                a,b=self.reg('rcx'),self.reg('rdx')
            else:
                sp=self.reg('esp');a,b=self.rp(sp+4),self.rp(sp+8)
            if address==API_PREPARE:
                self.core.lib.ResumePrepare(a,b)
                self.write(HEAP,ctypes.string_at(HEAP,end))
            else:self.core.lib.ResumeCommit(a,b)
            # Both ABIs permit the callee to overwrite these registers.
            for reg in (['rcx','rdx','r8','r9','r10','r11'] if self.bits==64 else ['ecx','edx']):self.reg(reg,0x12345678)
            self.ret(0)
            return
        rva=address-self.base
        if self.phase in ('UI request', 'UI copy'):
            copy, erase, parse, lookup = ((0x85520,0x878f0,0x75a90,0x87490) if self.bits==64
                                         else (0x67150,0x69370,0x5c6c0,0x683f0))
            cx=self.reg('rcx' if self.bits==64 else 'ecx')
            sp=self.reg(self.spname)
            arg=lambda i:self.rp(sp+self.ptr*(i+1))
            dx=self.reg('rdx') if self.bits==64 else arg(0)
            if rva==copy:
                assert dx==native.JSON_OBJECT
                self.persisted_payload=dict(self.request_payload)
                self.write(cx+8,b'\x07')
                self.wp(cx,cx)
                self.ret(cx,0 if self.bits==64 else 4);return
            if rva==erase:
                dest=native.JSON_OBJECT+0x100
                assert cx==dest
                view=dx
                key=self.read(self.rp(view),self.r32(view+self.ptr)>>2).decode()
                self.persisted_payload.pop(key,None)
                self.ret(1,0 if self.bits==64 else 4);return
            if rva==parse:
                assert dx==native.JSON_OBJECT
                self.ret(0,0 if self.bits==64 else 8);return
            if rva==lookup:
                assert cx==native.JSON_OBJECT
                start,end=(dx,self.reg('r8')) if self.bits==64 else (arg(0),arg(1))
                value=self.request_payload.get(self.read(start,end-start).decode())
                self.json_value(value)
                self.ret(native.JSON_VALUE if value is not None else 0,0 if self.bits==64 else 8);return
            if rva in (0x66cb6,0x66c1f,0x5188c,0x5182c):return
        if self.phase=='UI apply':
            if rva==(0x67a00 if self.bits==64 else 0x51fb0):
                if self.bits==64:
                    assert self.reg('rcx')==self.base+0x4e52e0
                    key=self.reg('rdx');assert self.reg('r8')==1
                else:
                    assert self.reg('ecx')==self.base+0x3f75a0
                    key=self.rp(self.reg('esp')+4);assert self.rp(self.reg('esp')+8)==1
                assert key==NODE+(0x10 if self.bits==64 else 8)
                self.dispatches.append(self.get_string(key));self.ret(0,0 if self.bits==64 else 8);return
            if rva==(0x6a030 if self.bits==64 else 0x53640):
                assert (self.reg('rdx')&255 if self.bits==64 else self.rp(self.reg('esp')+4))==1
                self.ret(0,0 if self.bits==64 else 4);return
        if address!=self.stop:
            if self.bits==64 and (0x67adc<=rva<0x67eb9 or 0x68e85<=rva<0x68e8a):return
            if self.bits==32 and (0x52021<=rva<0x523a4 or 0x52b7c<=rva<0x52b84):return
        return super().hook(u,address,size,opaque)

    def parse_live_request(self,payload,dest=None):
        dest=dest or self.playlist
        self.request_payload=payload
        self.parse_settings(payload['settings'],dest)
        self.reg(self.spname,SP)
        self.write(native.JSON_OBJECT+8,b'\x07')
        if self.bits==64:
            self.reg('rdx',native.JSON_OBJECT);self.reg('r8',dest)
            self.run(0x66cb6,0x66cbb,'UI request')
        else:
            self.wp(SP,native.JSON_OBJECT);self.wp(SP+4,dest)
            self.run(0x5188c,0x51891,'UI request')
        return self.r32(dest+self.flag_offset)

    def copy_request_for_config(self,payload):
        self.request_payload=payload
        self.reg(self.spname,SP)
        dest=native.JSON_OBJECT+0x100
        if self.bits==64:
            self.reg('rcx',dest);self.reg('rdx',native.JSON_OBJECT)
            self.run(0x66c1f,0x66c24,'UI copy')
        else:
            self.reg('ecx',dest);self.wp(SP,native.JSON_OBJECT)
            self.run(0x5182c,0x51831,'UI copy')
        return self.persisted_payload

    def manual_click(self,position,commit=True,effective_preset=None):
        new=native.HEAP+0x62000;items=self.alloc(self.count*self.desc)
        self.init_playlist(new,items,0x28,0)
        self.parse_live_request({'settings':{'beginfirst':True,'playintro':False,'rememberposition':True},
                                 'resumeposition':position},new)
        self.reg(self.spname,SP)
        if self.bits==64:
            self.reg('rcx',self.playlist);self.reg('rdx',new)
            self.run(0x66d11,0x66d16,'UI apply')
        else:
            self.reg('ecx',self.playlist);self.wp(SP,new)
            self.run(0x518d3,0x518d8,'UI apply')
        assert len(self.dispatches)==1
        self.dispatches.clear()
        return self.select(commit=commit,force=True,effective_preset=effective_preset)

    def select(self,commit=True,force=False,effective_preset=None):
        self.reg(self.spname,SP)
        if self.bits==64:
            self.reg('rbp',SP+0xc8);self.reg('r14',NODE);self.reg('r13',0)
            self.reg('rdi',int(force));self.reg('r12',NODE+0x10);self.wp(SP+0x30,NODE)
            self.string(SP+0x40,'');self.string(SP+0x68,'')
            self.run(0x67adc,0x6839d,'R04 prepare/select')
            result=SP+0x40
        else:
            bp=SP+0x180
            self.reg('ebp',bp);self.reg('ebx',NODE);self.reg('edi',NODE+8)
            self.wp(bp-8,NODE);self.w32(bp+0xc,int(force))
            self.string(bp-0x74,'');self.string(bp-0x58,'')
            self.run(0x52021,0x52847,'R04 prepare/select')
            result=bp-0x74
        path=self.get_string(result);preset=self.get_string(result+self.preset_offset)
        self.wp(NODE+(0x30 if self.bits==64 else 0x20),native.RENDERER)
        self.string(native.RENDERER+(0xe0 if self.bits==64 else 0x94),path)
        self.string(native.RENDERER+(0x120 if self.bits==64 else 0xc4),
                    preset if effective_preset is None else effective_preset)
        if commit:
            self.reg(self.spname,SP)
            if self.bits==64:
                self.reg('rsi',native.RENDERER)
                self.run(0x68e85,0x68e8a,'R04 commit')
            else:
                self.reg('esi',native.RENDERER)
                self.run(0x52b7c,0x52b84,'R04 commit')
            assert self.reg(self.spname)==SP,'Callback unbalanced the native stack'
        return self.paths.index(path)+1


def setup_arena():
    libc=ctypes.CDLL(None,use_errno=True)
    libc.mmap.argtypes=[ctypes.c_void_p,ctypes.c_size_t,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_long]
    libc.mmap.restype=ctypes.c_void_p
    address=libc.mmap(HEAP,0x1000000,3,0x100022,-1,0)
    assert address==HEAP,('Cannot map shared test arena',address,ctypes.get_errno())
    return libc


def main():
    setup_arena();results={}
    for bits in [64,32]:
        core=Core(bits);cases=0
        # Initial startup and a manual-like series of normal Next calls.
        e=Engine(core,bits)
        assert e.select()==1 and core.records()==[]
        assert [e.select() for _ in range(3)]==[2,3,4]
        assert core.records()[0]['index']==3;e.close();cases+=1
        # Same profile: source node removed and recreated, with its native
        # index zeroed. The independent C cache must restore item 4 directly.
        e=Engine(core,bits,checkpoint=0)
        assert e.select()==4 and e.select()==5
        assert core.records()[0]['index']==4;e.close();cases+=1
        # A different playlist on the same monitor gets its own checkpoint.
        bpaths=[f'OTHER_{i+1:04}' for i in range(10)]
        e=Engine(core,bits,paths=bpaths)
        assert [e.select() for _ in range(3)]==[1,2,3];e.close()
        e=Engine(core,bits);assert e.select()==5;e.close()
        e=Engine(core,bits,paths=bpaths);assert e.select()==3;e.close();cases+=1
        # Real process restart: the C platform bytes survive; RAM is reset.
        for _ in range(5):
            core.restart();e=Engine(core,bits)
            assert e.select()==1
            assert next(r for r in core.records() if r['index']==4)
            e.reconcile();assert e.checkpoint==5
            e.close();cases+=1
        core.restart();e=Engine(core,bits)
        assert e.select()==1;e.close()
        # Startup may rebuild the same playlist internally before its first
        # timer interval has elapsed. Retain the prelude and saved checkpoint.
        e=Engine(core,bits,checkpoint=0)
        assert e.select()==1 and e.select()==5;e.close();cases+=1
        core.restart();e=Engine(core,bits)
        assert [e.select() for _ in range(9)]==[1,5,6,7,8,9,10,1,2]
        e.close();cases+=1
        # Restore every valid endpoint, including 1 and 10, through an actual
        # file-format reload instead of seeding a runtime counter.
        for last in [1,4,9,10]:
            core.clear();e=Engine(core,bits)
            assert e.select()==1
            for _ in range(last if last==1 else last-1):e.select()
            if last==1:
                for _ in range(9):e.select()
            assert e.checkpoint==last,(bits,last,e.checkpoint)
            e.close();core.restart();e=Engine(core,bits,checkpoint=0)
            assert e.select()==1;e.reconcile()
            assert e.select()==last
            assert e.select()==last%10+1
            e.close();cases+=1
        # Three actual monitor/list identities from the R02 failure snapshot.
        have_snapshots=(native.INPUT/'config(1).json').exists() and (native.INPUT/'playliststate(1).bin').exists()
        if have_snapshots:
            config=json.loads((native.INPUT/'config(1).json').read_text())
            config=next(user['general'] for user in config.values() if isinstance(user,dict) and 'wallpaperconfig' in user.get('general',{}))
            selected=config['wallpaperconfig']['selectedwallpapers']
            state=native.unpack_state((native.INPUT/'playliststate(1).bin').read_bytes())[0][1]
        else:
            selected={f'DISPLAY_{i}':{'playlist':{'settings':{'rememberposition':True},'items':[f'MON{i}_WP{n:02}' for n in range(10)]}} for i in range(3)}
            state=[{'monitor':monitor,'checkpoint':0,'file':entry['playlist']['items'][0],'preset':'','bag':[]} for monitor,entry in selected.items()]
        fixtures=[]
        for monitor,entry in selected.items():
            p=entry.get('playlist',{})
            if not p.get('settings',{}).get('rememberposition'):continue
            paths=[v if isinstance(v,str) else v['file'] for v in p['items']]
            presets=['' if isinstance(v,str) else v.get('preset','') for v in p['items']]
            saved=next(r for r in state if r['monitor']==monitor)
            assert saved['checkpoint']==0
            fixtures.append((monitor,paths,presets,saved))
        assert len(fixtures)==3
        core.clear()
        for target,(monitor,paths,presets,saved) in zip([4,6,9],fixtures):
            e=Engine(core,bits,len(paths),monitor=monitor,paths=paths,presets=presets)
            assert e.select()==1
            for _ in range(target-1):e.select()
            assert e.checkpoint==target;e.close()
        assert sorted(r['index']+1 for r in core.records())==[4,6,9]
        # Profile reload in the same process repeats each monitor's own entry.
        for target,(monitor,paths,presets,saved) in zip([4,6,9],fixtures):
            e=Engine(core,bits,len(paths),monitor=monitor,paths=paths,presets=presets)
            assert e.select()==target;e.close();cases+=1
        core.restart()
        for target,(monitor,paths,presets,saved) in zip([4,6,9],fixtures):
            e=Engine(core,bits,len(paths),monitor=monitor,paths=paths,presets=presets)
            e.cold_load(saved) # Native R02 state is zero for all three monitors.
            assert e.select()==1;e.reconcile();assert e.checkpoint==target
            assert e.select()==target
            e.close();cases+=1
        # ASLR, long native string paths and independent monitor state.
        core.restart()
        for target,(monitor,paths,presets,saved) in zip([4,6,9],fixtures):
            e=Engine(core,bits,len(paths),monitor=monitor,paths=paths,presets=presets,relocated=True)
            assert [e.select(),e.select()]==[1,target];e.close();cases+=1
        # Corrupt storage is rejected and an ordinary successful switch creates
        # a fresh checksummed state. No binary state is trusted as a pointer.
        core.lib.PirsCorruptDiskForTest();core.restart();e=Engine(core,bits)
        assert [e.select(),e.select()]==[1,2]
        assert core.records()[0]['index']==1;e.close();cases+=1
        # A disabled playlist never overwrites remembered positions.
        core.clear();e=Engine(core,bits)
        assert [e.select() for _ in range(4)]==[1,2,3,4];e.close()
        before=core.records();e=Engine(core,bits,flags=8)
        assert [e.select(),e.select()]==[1,2];e.close()
        assert core.records()==before;cases+=1
        # A failed write preserves the memory checkpoint and retries on the
        # next successful regular selection.
        core.lib.PirsFailWritesForTest(1);e=Engine(core,bits)
        assert e.select()==4;e.close()
        core.lib.PirsFailWritesForTest(0);e=Engine(core,bits)
        assert e.select()==4 and core.records()[0]['index']==3;e.close();cases+=1
        # Real emitted UI payload, then native parser/assignment/selector, C core.
        requests=json.loads((OUT/'ui-selection-requests.json').read_text())
        for request in requests:
            core.clear();e=Engine(core,bits)
            assert [e.select() for _ in range(7)]==[1,2,3,4,5,6,7]
            target=request['resumeposition']
            assert e.copy_request_for_config(request)=={k:v for k,v in request.items() if k!='resumeposition'}
            assert request['resumeposition']==target
            assert e.manual_click(target)==target
            assert core.records()[0]['index']==target-1
            assert e.select()==target%10+1
            e.close();cases+=1
        # Selecting WP1 while it is the protected prelude must explicitly reset.
        for target in [1,2,10]:
            core.clear();e=Engine(core,bits)
            for _ in range(7):e.select()
            e.close();core.restart();e=Engine(core,bits)
            assert e.select()==1 and core.records()[0]['index']==6
            assert e.manual_click(target)==target
            assert not(e.flags&0xffff0140) and e.read(NODE+e.start_offset,1)==b'\0'
            assert core.records()[0]['index']==target-1
            e.close();core.restart();e=Engine(core,bits)
            assert [e.select(),e.select()]==[1,target]
            assert e.select()==target%10+1;e.close();cases+=1
        # The ordinary profile reapply contains no one-shot request.
        core.clear();e=Engine(core,bits)
        e.select();assert e.manual_click(2)==2
        e.apply_same_playlist();assert e.select()==2 and e.select()==3;e.close();cases+=1
        # Request and global-manager addresses both remain valid after ASLR.
        core.clear();e=Engine(core,bits,relocated=True)
        e.select();assert e.manual_click(9)==9 and e.select()==10;e.close();cases+=1
        # A requested selection without a completed renderer does not checkpoint.
        core.clear();e=Engine(core,bits)
        for _ in range(4):e.select()
        assert e.manual_click(2,commit=False)==2 and core.records()[0]['index']==3
        e.close();core.restart();e=Engine(core,bits)
        assert [e.select(),e.select()]==[1,4];e.close();cases+=1
        # The selected row/preset, rather than just the first matching filepath.
        core.clear();e=Engine(core,bits,paths=['SAME']*10,presets=[f'PRESET_{i}' for i in range(10)])
        e.select();e.manual_click(6)
        assert e.checkpoint==6
        assert e.get_string(native.RENDERER+(0x120 if bits==64 else 0xc4))=='PRESET_5'
        assert core.records()[0]['index']==5;e.close();cases+=1
        # Both clicks and normal advances may resolve an unspecified preset.
        core.clear();e=Engine(core,bits)
        assert e.select()==1
        assert e.manual_click(2,effective_preset='Effective')==2
        assert core.records()[0]['index']==1
        assert e.select(effective_preset='Effective')==3
        assert core.records()[0]['index']==2
        e.close();core.restart();e=Engine(core,bits)
        assert [e.select(),e.select()]==[1,3]
        e.close();cases+=1
        # Numeric JSON requests are strictly bounded and reject other types.
        for bad in [None,True,False,-1,0,32769,1<<40,1.5,'2',{},[]]:
            e=Engine(core,bits)
            flags=e.parse_live_request({'settings':{'beginfirst':True,'rememberposition':True},'resumeposition':bad})
            assert not flags&0xffff0100,(bits,bad,hex(flags));e.close()
        e=Engine(core,bits)
        assert e.parse_live_request({'settings':{'beginfirst':True,'rememberposition':True},'resumeposition':32768})>>16==32768
        e.close();cases+=1
        # A legacy config can replay an old command on every restart. Its
        # settings key must never select a row or skip the protected prelude.
        core.clear();e=Engine(core,bits)
        assert e.select()==1
        assert e.manual_click(4)==4 and e.select()==5
        e.close();core.restart();e=Engine(core,bits)
        legacy={'settings':{'beginfirst':True,'rememberposition':True,'resumeposition':7}}
        assert e.parse_live_request(legacy)==0x28
        assert [e.select(),e.select()]==[1,5]
        assert core.records()[0]['index']==4
        e.close();cases+=1
        # Manual selection on one of the three actual monitor/list identities
        # leaves both other stored positions intact across profile recreation.
        core.clear()
        for target,(monitor,paths,presets,saved) in zip([4,6,9],fixtures):
            e=Engine(core,bits,len(paths),monitor=monitor,paths=paths,presets=presets)
            for _ in range(target):e.select()
            e.close()
        monitor,paths,presets,saved=fixtures[0]
        e=Engine(core,bits,len(paths),monitor=monitor,paths=paths,presets=presets)
        assert e.manual_click(2)==2;e.close()
        assert sorted(r['index']+1 for r in core.records())==[2,6,9]
        for target,(monitor,paths,presets,saved) in zip([2,6,9],fixtures):
            e=Engine(core,bits,len(paths),monitor=monitor,paths=paths,presets=presets)
            assert e.select()==target;e.close()
        cases+=1
        results[str(bits)]={'status':'passed','scenarios':cases,'monitor_fixtures':3,'fixture_source':'uploaded snapshots' if have_snapshots else 'synthetic',
            'scope':'Actual EXE hooks/native selection in Unicorn + shared C core compiled for host; simulated renderer/ownership and file/lock platform. Windows loader and WinAPI I/O not run.'}
        print(bits,'R04 scenarios passed',cases,flush=True)
        if bits==32:
            data=ctypes.create_string_buffer(16400);n=core.lib.PirsDiskForTest(data)
            (OUT/'cache-format-fixture.bin').write_bytes(data.raw[:n])
    (OUT/'R04-NATIVE-RESULTS.json').write_text(json.dumps(results,indent=2)+'\n')


if __name__=='__main__':main()

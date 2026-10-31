"""Build R04 from the pinned originals, retaining R02's selection semantics.

Adds a tiny freestanding local checkpoint DLL per architecture. Its two native
callbacks run before selection and after the actual renderer is known. No UI
session, background service or shutdown callback is needed for persistence.
"""
from pathlib import Path
import hashlib
import json
import os
import struct
import subprocess
import sys

import pefile
from capstone.x86_const import X86_OP_MEM, X86_REG_RIP

import build_r02 as previous

ROOT=Path(__file__).resolve().parents[1]
OUT=Path(os.environ.get('WE_BUILD_OUTPUT',ROOT/'build'))
SOURCE=Path(os.environ.get('RESUME_SOURCE',ROOT/'src'))
OUT.mkdir(parents=True,exist_ok=True)
BaseBuilder=previous.Builder
previous.OUT=OUT


def build_dlls():
    zig=os.environ.get('PIRS_ZIG',str(ROOT/'analysis/toolchain/ziglang/zig'))
    zig_path=Path(zig).resolve()
    headers=Path(os.environ.get('PIRS_WIN_HEADERS',zig_path.parent/'lib/libc/include/any-windows-any'))
    for bits,target,entry in [(64,'x86_64-windows-gnu','DllMain'),(32,'x86-windows-gnu','DllMain@12')]:
        dest=OUT/f'PlaylistResume{bits}.dll'
        args=[zig,'cc','-target',target,'-isystem',str(headers),'-shared','-O2','-ffreestanding',
              '-fno-builtin','-fno-stack-protector','-nostdlib','-Wl,--entry,'+entry]
        if bits==32:args+=['-mstackrealign']
        args+=['-o',str(dest),str(SOURCE/'resume_core.c'),str(SOURCE/'resume_win.c'),'-lkernel32']
        subprocess.run(args,check=True)
        data=bytearray(dest.read_bytes());p=pefile.PE(data=data)
        # Stable, unsigned build metadata; no stale source-machine timestamp.
        struct.pack_into('<I',data,p.FILE_HEADER.get_field_absolute_offset('TimeDateStamp'),0)
        struct.pack_into('<I',data,p.OPTIONAL_HEADER.get_field_absolute_offset('CheckSum'),0)
        checksum=pefile.PE(data=data).generate_checksum()
        struct.pack_into('<I',data,p.OPTIONAL_HEADER.get_field_absolute_offset('CheckSum'),checksum)
        dest.write_bytes(data);p=pefile.PE(data=data)
        assert p.verify_checksum()
        assert [d.dll.lower() for d in p.DIRECTORY_ENTRY_IMPORT]==[b'kernel32.dll']
        assert {e.name for e in p.DIRECTORY_ENTRY_EXPORT.symbols}=={b'ResumePrepare',b'ResumeCommit'}
        manifest=dict(filename=dest.name,kind='new',version='2.8.42',revision='R04',original_sha256=None,
                      original_size=0,patched_size=len(data),patched_sha256=hashlib.sha256(data).hexdigest(),
                      contents_hex=data.hex())
        (OUT/(dest.stem+'.patch.json')).write_text(json.dumps(manifest,indent=2)+'\n')
        print(dest.name,len(data),manifest['patched_sha256'])


class BuilderR04(BaseBuilder):
    def __init__(self,bits):
        super().__init__(bits)
        self.body[:len(b'PLAYLIST-RESUME\0')]=b'PLAYLIST-RESUME\0'
        self.body.extend(b'\0'*(0x400-len(self.body)))
        ptr=bits//8
        self.data_rva=self.rva+0x1000
        self.prepare_iat=self.base+self.data_rva
        self.commit_iat=self.prepare_iat+ptr
        self.manual_key=self.base+self.rva+0x60
        self.body[0x60:0x60+15]=b'resumeposition\0'
        self.body[0x80:0x80+len(f'PlaylistResume{bits}.dll\0')]=f'PlaylistResume{bits}.dll\0'.encode()
        self.body[0xb0:0xb0+16]=b'\0\0ResumePrepare\0'
        self.body[0xd0:0xd0+15]=b'\0\0ResumeCommit\0'
        for offset in [0x100]:
            fmt='<Q' if bits==64 else '<I'
            struct.pack_into(fmt,self.body,offset,self.rva+0xb0)
            struct.pack_into(fmt,self.body,offset+ptr,self.rva+0xd0)
            struct.pack_into(fmt,self.body,offset+2*ptr,0)
        imports=self.pe.DIRECTORY_ENTRY_IMPORT
        table=b''.join(x.struct.__pack__() for x in imports)
        table+=struct.pack('<IIIII',self.rva+0x100,0,0,self.rva+0x80,self.data_rva)
        table+=b'\0'*20
        assert 0x180+len(table)<=0x400
        self.body[0x180:0x180+len(table)]=table
        directory=self.pe.OPTIONAL_HEADER.DATA_DIRECTORY[1]
        self.write_offset(directory.get_file_offset(),struct.pack('<II',self.rva+0x180,len(table)),
                          'extend_imports_with_local_checkpoint_helper')

    def code(self,asm,label,*args,**kwargs):
        if label=='read_rememberposition_setting':
            if self.bits==64:
                old='and dword ptr [r14+0x3c], 0xffffffef'
                extra='''
                    mov rcx, rbx
                    lea rdx, [rip+0x3333]
                    lea r8, [rip+0x4444]
                    call 0x140086de0
                    movzx ecx, byte ptr [rax+8]
                    sub ecx, 1
                    cmp ecx, 1
                    ja done
                    cmp qword ptr [rax], 1
                    jb done
                    cmp qword ptr [rax], 32768
                    ja done
                    mov eax, dword ptr [rax]
                    shl eax, 16
                    or eax, 0x100
                    or dword ptr [r14+0x3c], eax
                '''
            else:
                old='and dword ptr [edi+0x24], 0xffffffef'
                extra=f'''
                    push {self.manual_key+14}
                    push {self.manual_key}
                    mov ecx, esi
                    call 0x4681a0
                    movzx ecx, byte ptr [eax+8]
                    sub ecx, 1
                    cmp ecx, 1
                    ja done
                    cmp dword ptr [eax+4], 0
                    jne done
                    mov eax, dword ptr [eax]
                    cmp eax, 1
                    jb done
                    cmp eax, 32768
                    ja done
                    shl eax, 16
                    or eax, 0x100
                    or dword ptr [edi+0x24], eax
                '''
            assert asm.count(old)==1
            asm=asm.replace(old,old+'\n'+extra)
        if label=='preserve_same_playlist_on_ui_apply':
            # This callsite is only used for an existing native monitor node.
            # Native selectPlaylist normally applies settings without selecting.
            # A marked click must therefore trigger its selector immediately.
            if self.bits==64:
                old='done:\n        add rsp, 0x28'
                new='''done:
                    test dword ptr [rbx+0x3c], 0x100
                    jz return_to_caller
                    lea rdx, [rbx-0x28]
                    lea rcx, [rip+0x5555]
                    mov r8d, 1
                    call 0x140067a00
                    mov dl, 1
                    call 0x14006a030
                  return_to_caller:
                    add rsp, 0x28'''
            else:
                old='done:\n        add esp, 0x14'
                new='''done:
                    test dword ptr [ebx+0x24], 0x100
                    jz return_to_caller
                    lea eax, [ebx-0x1c]
                    push 1
                    push eax
                    mov ecx, 0x7f75a0
                    call 0x451fb0
                    push 1
                    call 0x453640
                  return_to_caller:
                    add esp, 0x14'''
            assert asm.count(old)==1
            asm=asm.replace(old,new)
        rva=super().code(asm,label,*args,**kwargs)
        info=self.hooks[-1];off=rva-self.rva
        code=bytearray(self.body[off:off+info['code_size']])
        for i in self.cs.disasm(bytes(code),self.base+rva):
            for operand in i.operands:
                if operand.type!=X86_OP_MEM:continue
                targets={0x1111:self.prepare_iat,0x2222:self.commit_iat,
                         0x3333:self.manual_key,0x4444:self.manual_key+14,
                         0x5555:self.base+0x4e52e0}
                if self.bits==64 and operand.mem.base==X86_REG_RIP and operand.mem.disp in targets:
                    target=targets[operand.mem.disp]
                    at=i.address-self.base-rva+i.disp_offset
                    struct.pack_into('<i',code,at,target-i.address-i.size)
                if self.bits==32 and operand.mem.base==0 and operand.mem.disp in [self.prepare_iat,self.commit_iat]:
                    self.relocs.append(i.address-self.base+i.disp_offset)
            if self.bits==32:
                from capstone.x86_const import X86_OP_IMM
                for operand in i.operands:
                    if operand.type==X86_OP_IMM and operand.imm in [self.manual_key,self.manual_key+14,0x7f75a0]:
                        self.relocs.append(i.address-self.base+i.imm_offset)
        self.body[off:off+len(code)]=code
        return rva

    def finalize(self):
        if self.bits==64:
            self.code('''
                mov rcx, r14
                mov rdx, rsp
                call qword ptr [rip+0x1111]
                mov ecx, dword ptr [r14+0x70]
                cmp ecx, 2
                jne 0x140067bc7
                jmp 0x140067ae5
            ''','prepare_independent_checkpoint',0x67adc,'83 f9 02 0f 85 e2 00 00 00')
            self.code('''
                mov rcx, rsp
                mov rdx, rsi
                call qword ptr [rip+0x2222]
                lea rcx, [rsp+0x68]
                jmp 0x140068e8a
            ''','commit_successful_regular_checkpoint',0x68e85,'48 8d 4c 24 68')
        else:
            self.code(f'''
                push ebp
                push ebx
                call dword ptr [{self.prepare_iat}]
                add esp, 8
                mov ecx, dword ptr [ebx+0x44]
                cmp ecx, 2
                jmp 0x452027
            ''','prepare_independent_checkpoint',0x52021,'8b 4b 44 83 f9 02')
            wrapper=self.code(f'''
                push ecx
                push esi
                push ebp
                call dword ptr [{self.commit_iat}]
                add esp, 8
                pop ecx
                call 0x42da30
                ret
            ''','commit_successful_regular_checkpoint')
            self.call_hook(0x52b7f,wrapper,0x2da30,'commit_wrapper_before_descriptor_cleanup')
        manifest=super().finalize()
        # The loader replaces import pointers. Give the added IAT its own RW,
        # non-executable page instead of putting writable pointers in code.
        assert len(self.body)<=0x1000
        raw=len(self.data)
        ptr=self.bits//8
        data=self.body[0x100:0x100+3*ptr]
        header_at=self.pe.sections[-1].get_file_offset()+80
        assert header_at+40<=self.pe.OPTIONAL_HEADER.SizeOfHeaders
        assert not any(self.original[header_at:header_at+40])
        header=struct.pack('<8sIIIIIIHHI',b'.pird\0\0\0',len(data),self.data_rva,0x200,raw,0,0,0,0,0xc0000040)
        self.write_offset(header_at,header,'add_non_executable_import_pointer_section')
        def replace_field(offset,value,label):
            for c in self.changes:
                if c['offset']==offset and len(bytes.fromhex(c['after']))==len(value):
                    c['after']=value.hex();self.data[offset:offset+len(value)]=value;return
            self.write_offset(offset,value,label)
        replace_field(self.pe.FILE_HEADER.get_field_absolute_offset('NumberOfSections'),
                      struct.pack('<H',self.pe.FILE_HEADER.NumberOfSections+2),'section_count')
        replace_field(self.pe.OPTIONAL_HEADER.get_field_absolute_offset('SizeOfImage'),
                      struct.pack('<I',self.data_rva+0x1000),'SizeOfImage')
        replace_field(self.pe.OPTIONAL_HEADER.get_field_absolute_offset('SizeOfInitializedData'),
                      struct.pack('<I',self.pe.OPTIONAL_HEADER.SizeOfInitializedData+0x200),'initialized_data_size')
        self.data.extend(bytes(data).ljust(0x200,b'\0'))
        checksum=pefile.PE(data=self.data).generate_checksum()
        replace_field(self.pe.OPTIONAL_HEADER.get_field_absolute_offset('CheckSum'),struct.pack('<I',checksum),'checksum')
        manifest['revision']='R04'
        manifest['changes']=self.changes
        manifest['append_hex']=bytes(self.data[len(self.original):]).hex()
        manifest['patched_size']=len(self.data)
        manifest['patched_sha256']=hashlib.sha256(self.data).hexdigest()
        manifest['checkpoint_helper']=f'PlaylistResume{self.bits}.dll'
        manifest['callback_iat_rvas']={'prepare':self.prepare_iat-self.base,'commit':self.commit_iat-self.base}
        (OUT/self.name).write_bytes(self.data)
        (OUT/self.name.replace('.exe','.patch.json')).write_text(json.dumps(manifest,indent=2)+'\n')
        image=pefile.PE(str(OUT/self.name))
        helper=next(d for d in image.DIRECTORY_ENTRY_IMPORT if d.dll==manifest['checkpoint_helper'].encode())
        assert [x.name for x in helper.imports]==[b'ResumePrepare',b'ResumeCommit']
        assert image.verify_checksum()
        assert not any(s.Characteristics&0x20000000 and s.Characteristics&0x80000000 for s in image.sections)
        assert image.get_section_by_rva(self.data_rva).Characteristics==0xc0000040
        print('R04 final',self.name,manifest['patched_sha256'])
        return manifest


def build_ui():
    manifest=previous.build_ui()
    s=(OUT/'scripts.js').read_text(encoding='utf-8')
    def replace(before,after):
        nonlocal s
        assert s.count(before)==1,before[:100]
        s=s.replace(before,after)
        manifest['replacements'].append({'before':before,'after':after})
    helper='''function applyResumePlaylistEntry(e,c){var m=c.monitor,p=m&&m.playlist,s=p&&p.settings;
if(V.selectedMonitor!==m||m.location!==c.location||p!==c.playlist||p.items[c.index]!==c.entry||c.entry.wallpaper!==e||e.status!=="installed"||!s||s.rememberposition!==true||s.beginfirst!==true||s.mode!=="timer"||s.order!=="sorted")return;
var payload=qe(p),selected=V.wallpaperConfig.selectedwallpapers[c.location]||{};
payload.settings.resumeposition=c.index+1;selected.file=e.file;V.wallpaperConfig.selectedwallpapers[c.location]=selected;
V.currentSelection=e;m.wallpaper=e;
return F.callDeferred("browseWallpaperObject","selectPlaylist",payload,c.location)}
V.callbackPlaylistEntrySelected=function(entry,index){var m=V.selectedMonitor,p=m&&m.playlist,s=p&&p.settings;
if(!entry||!entry.wallpaper)return;
if(s&&s.rememberposition===true&&s.beginfirst===true&&s.mode==="timer"&&s.order==="sorted"&&p.items[index]===entry&&index>=0&&index<32768&&index%1===0)
return V.callbackWallpaperSelected(entry.wallpaper,{monitor:m,location:m.location,playlist:p,entry:entry,index:index});
return V.callbackWallpaperSelected(entry.wallpaper)};'''.replace('\n','')
    replace('V.callbackWallpaperSelected=function(e){',helper+'V.callbackWallpaperSelected=function(e,resumeSelection){')
    replace('V.currentSelection!==e&&0===xt','(V.currentSelection!==e||resumeSelection)&&0===xt')
    replace('"installed"===(V.currentSelection=e).status&&l(e)',
            'resumeSelection?applyResumePlaylistEntry(e,resumeSelection):"installed"===(V.currentSelection=e).status&&l(e)')
    replace('ng-click="callbackWallpaperSelected(entry.wallpaper)"',
            'ng-click="callbackPlaylistEntrySelected(entry,$index)"')
    replace('Wallpaper 1 bleibt in der Rotation.</small>',
            'Wallpaper 1 bleibt in der Rotation. Ein Klick im Playlist-Streifen setzt die gemerkte Position.</small>')
    data=s.encode('utf-8');(OUT/'scripts.js').write_bytes(data)
    manifest['revision']='R04';manifest['patched_size']=len(data)
    manifest['patched_sha256']=hashlib.sha256(data).hexdigest()
    (OUT/'scripts.patch.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    return manifest


def main():
    build_dlls()
    previous.Builder=BuilderR04
    previous.build64();previous.build32()
    build_ui()


if __name__=='__main__':main()

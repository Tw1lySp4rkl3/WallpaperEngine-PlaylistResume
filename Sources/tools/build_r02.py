"""Reproducible, offline R02 patch for the exact user-supplied WE 2.8.42 files.

The originals are read-only inputs. No complete executable or UI bundle is
distributed. PE changes add one RX section, with relocations and x64 unwind
records. See ANALYSE.md for the limits of the native-code emulation.
"""
from pathlib import Path
import hashlib
import json
import os
import struct

import pefile
from capstone import Cs, CS_ARCH_X86, CS_MODE_32, CS_MODE_64
from capstone.x86_const import X86_OP_IMM, X86_OP_MEM, X86_REG_RIP
from keystone import Ks, KS_ARCH_X86, KS_MODE_32, KS_MODE_64

ROOT = Path(__file__).resolve().parents[1]
INPUT = Path(os.environ.get('WE_ORIGINALS',ROOT / "upload"))
OUT = Path(os.environ.get('WE_BUILD_OUTPUT',ROOT / "analysis" / "r02"))
OUT.mkdir(parents=True, exist_ok=True)
PINNED_SHA = {
    'wallpaper32.exe': 'daac1ea7c991207fdb6098616757e3dae393850f6862845db55d04921b6bda07',
    'wallpaper64.exe': '40e2ce021e9352324fadb3b8f72b8ba2a7ee95b71cc571d5b9f84be75cd993b0',
    'scripts.js': 'ab5a72773ceca706e5f352b0e436b19d1cc20f4b70fd4e310e30d62f80540903',
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def align(value, boundary):
    return (value + boundary - 1) & -boundary


class Builder:
    def __init__(self, bits):
        self.bits = bits
        self.name = f"wallpaper{bits}.exe"
        self.original = (INPUT / self.name).read_bytes()
        assert sha(self.original) == PINNED_SHA[self.name], 'Unknown original: ' + self.name
        self.data = bytearray(self.original)
        self.pe = pefile.PE(data=self.original)
        self.base = self.pe.OPTIONAL_HEADER.ImageBase
        self.rva = self.pe.OPTIONAL_HEADER.SizeOfImage
        self.raw = align(len(self.original), self.pe.OPTIONAL_HEADER.FileAlignment)
        self.body = bytearray(b"PI-RESUME-R02\0".ljust(32, b"\0") + b"rememberposition\0")
        self.key = self.base + self.rva + 32
        self.changes = []
        self.hooks = []
        self.runtime = []
        self.relocs = []
        mode = KS_MODE_64 if bits == 64 else KS_MODE_32
        self.ks = Ks(KS_ARCH_X86, mode)
        self.cs = Cs(CS_ARCH_X86, CS_MODE_64 if bits == 64 else CS_MODE_32)
        self.cs.detail = True

    def write(self, rva, new, label):
        offset = self.pe.get_offset_from_rva(rva)
        self.write_offset(offset, new, label, rva)

    def write_offset(self, offset, new, label, rva=None):
        assert offset + len(new) <= len(self.original)
        before = bytes(self.data[offset:offset + len(new)])
        if before == new:
            return
        for change in self.changes:
            a = change["offset"]
            b = a + len(bytes.fromhex(change["before"]))
            assert offset >= b or offset + len(new) <= a, (label, change["label"])
        self.changes.append(dict(label=label, offset=offset, before=before.hex(), after=new.hex(),
                                 **({"rva": rva} if rva is not None else {})))
        self.data[offset:offset + len(new)] = new

    def covering_runtime(self, hook):
        for record in self.pe.DIRECTORY_ENTRY_EXCEPTION:
            r = record.struct
            if r.BeginAddress <= hook < r.EndAddress:
                return struct.pack("<III", r.BeginAddress, r.EndAddress, r.UnwindData)
        raise AssertionError(f"No x64 unwind record for {hook:x}")

    def code(self, asm, label, hook=None, expected=None, own_unwind=None, rip_key=False):
        self.body.extend(b"\xcc" * (align(len(self.body), 16) - len(self.body)))
        rva = self.rva + len(self.body)
        code = bytearray(self.ks.asm(asm, self.base + rva)[0])
        # New x64 string references are RIP relative; x86 immediate addresses
        # receive HIGHLOW relocations for ASLR, just like the original code.
        for ins in self.cs.disasm(bytes(code), self.base + rva):
            if self.bits == 64 and rip_key:
                for op in ins.operands:
                    if op.type == X86_OP_MEM and op.mem.base == X86_REG_RIP and op.mem.disp in (0x1234, 0x5678):
                        target = self.key + (16 if op.mem.disp == 0x5678 else 0)
                        at = ins.address - self.base - rva + ins.disp_offset
                        struct.pack_into("<i", code, at, target - (ins.address + ins.size))
            if self.bits == 32:
                for op in ins.operands:
                    if op.type == X86_OP_IMM and op.imm in (self.key, self.key + 16):
                        assert ins.mnemonic == "push" and ins.size == 5
                        self.relocs.append(ins.address - self.base + ins.imm_offset)
        self.body.extend(code)
        self.hooks.append(dict(label=label, code_rva=rva, code_size=len(code), hook_rva=hook))
        if hook is not None:
            expected = bytes.fromhex(expected)
            assert self.pe.get_data(hook, len(expected)) == expected, label
            jump = b"\xe9" + struct.pack("<i", rva - hook - 5)
            self.write(hook, jump + b"\x90" * (len(expected) - 5), label)
        if self.bits == 64:
            self.runtime.append((rva, rva + len(code), own_unwind, self.covering_runtime(hook) if hook else None))
        return rva

    def call_hook(self, site, target, original_target, label):
        expected = b"\xe8" + struct.pack("<i", original_target - site - 5)
        assert self.pe.get_data(site, 5) == expected
        self.write(site, b"\xe8" + struct.pack("<i", target - site - 5), label)

    def finalize(self):
        if self.bits == 64:
            entries = bytearray()
            for begin, end, unwind, parent in self.runtime:
                self.body.extend(b"\0" * (align(len(self.body), 4) - len(self.body)))
                info_rva = self.rva + len(self.body)
                self.body.extend(unwind if unwind is not None else b"\x21\0\0\0" + parent)
                entries.extend(struct.pack("<III", begin, end, info_rva))
            self.extend_directory(3, ".pdata", entries)
        if self.relocs:
            blocks = bytearray()
            for page in sorted({r & ~0xfff for r in self.relocs}):
                values = [(3 << 12) | (r & 0xfff) for r in self.relocs if r & ~0xfff == page]
                if len(values) % 2:
                    values.append(0)
                blocks.extend(struct.pack("<II", page, 8 + 2 * len(values)))
                blocks.extend(struct.pack("<" + "H" * len(values), *values))
            self.extend_directory(5, ".reloc", blocks)

        pe = self.pe
        new_section_at = pe.sections[-1].get_file_offset() + 40
        assert new_section_at + 40 <= pe.OPTIONAL_HEADER.SizeOfHeaders
        assert not any(self.original[new_section_at:new_section_at + 40])
        raw_size = align(len(self.body), pe.OPTIONAL_HEADER.FileAlignment)
        header = struct.pack("<8sIIIIIIHHI", b".pirs\0\0\0", len(self.body), self.rva,
                             raw_size, self.raw, 0, 0, 0, 0, 0x60000020)
        self.write_offset(new_section_at, header, "add_read_execute_section")
        self.write_offset(pe.FILE_HEADER.get_field_absolute_offset("NumberOfSections"),
                          struct.pack("<H", pe.FILE_HEADER.NumberOfSections + 1), "section_count")
        for field, value in [("SizeOfImage", align(self.rva + len(self.body), pe.OPTIONAL_HEADER.SectionAlignment)),
                             ("SizeOfCode", pe.OPTIONAL_HEADER.SizeOfCode + raw_size)]:
            self.write_offset(pe.OPTIONAL_HEADER.get_field_absolute_offset(field), struct.pack("<I", value), field)
        # The altered executable is unsigned. Preserve all original certificate
        # bytes for an exact inverse, but do not advertise its obsolete signature.
        security = pe.OPTIONAL_HEADER.DATA_DIRECTORY[4]
        self.write_offset(security.get_file_offset(), b"\0" * 8, "clear_obsolete_signature_directory")
        appended = (b"\0" * (self.raw - len(self.original)) + bytes(self.body).ljust(raw_size, b"\0"))
        self.data.extend(appended)
        checksum = pefile.PE(data=self.data).generate_checksum()
        self.write_offset(pe.OPTIONAL_HEADER.get_field_absolute_offset("CheckSum"), struct.pack("<I", checksum), "checksum")
        manifest = dict(filename=self.name, kind="pe", version="2.8.42", revision="R02",
                        architecture='x64' if self.bits == 64 else 'x86', original_sha256=sha(self.original), patched_sha256=sha(self.data),
                        original_size=len(self.original), patched_size=len(self.data), changes=self.changes,
                        append_hex=appended.hex(), hooks=self.hooks)
        (OUT / self.name).write_bytes(self.data)
        (OUT / self.name.replace(".exe", ".patch.json")).write_text(json.dumps(manifest, indent=2) + "\n")
        parsed = pefile.PE(data=self.data)
        assert parsed.verify_checksum()
        if self.bits == 64:
            begins = [r.struct.BeginAddress for r in parsed.DIRECTORY_ENTRY_EXCEPTION]
            assert begins == sorted(begins) and len(set(begins)) == len(begins)
        for s in parsed.sections:
            assert not (s.Characteristics & 0x80000000 and s.Characteristics & 0x20000000)
        print(self.name, "code/metadata", len(self.body), "patched SHA256", manifest["patched_sha256"])
        return manifest

    def extend_directory(self, index, section_name, extra):
        directory = self.pe.OPTIONAL_HEADER.DATA_DIRECTORY[index]
        section = next(s for s in self.pe.sections if s.Name.rstrip(b"\0").decode() == section_name)
        start = directory.VirtualAddress + directory.Size
        assert start + len(extra) <= section.VirtualAddress + section.SizeOfRawData
        assert not any(self.pe.get_data(start, len(extra)))
        self.write(start, bytes(extra), section_name + "_extra_records")
        self.write_offset(directory.get_field_absolute_offset("Size"), struct.pack("<I", directory.Size + len(extra)),
                          section_name + "_directory_size")
        new_size = max(section.Misc_VirtualSize, start + len(extra) - section.VirtualAddress)
        self.write_offset(section.get_file_offset() + 8, struct.pack("<I", new_size), section_name + "_virtual_size")


def build64():
    b = Builder(64)
    def feature(reg, dest):
        return f"""
            cmp dword ptr [{reg}+0x70], 1
            jne {dest}
            cmp dword ptr [{reg}+0x6c], 1
            jne {dest}
            test byte ptr [{reg}+0x74], 0x20
            jz {dest}
            test byte ptr [{reg}+0x74], 8
            jz {dest}
        """

    b.code("""
        cmp byte ptr [rbx+8], 7
        jne done
        mov rcx, rbx
        lea rdx, [rip+0x1234]
        lea r8, [rip+0x5678]
        call 0x140086de0
        cmp byte ptr [rax+8], 5
        jne done
        mov rcx, rax
        call 0x140086300
        test al, al
        jz done
        or dword ptr [r14+0x3c], 0x20
        cmp dword ptr [r14+0x38], 1
        jne done
        cmp dword ptr [r14+0x34], 1
        jne done
        test byte ptr [r14+0x3c], 8
        jz done
        and dword ptr [r14+0x3c], 0xffffffef
      done:
        lea r8, [r14+0x48]
        mov rdx, rbx
        jmp 0x140075e9d
    """, "read_rememberposition_setting", 0x75e96, "4d 8d 46 48 48 8b d3", rip_key=True)

    b.code(feature("r14", "native") + """
        or dword ptr [r14+0x74], 0x40
        mov dword ptr [r14+0x7c], 0
        jmp done
      native:
        mov dword ptr [r14+0x78], r13d
      done:
        mov rdx, qword ptr [r14+0x38]
        jmp 0x140067eee
    """, "keep_checkpoint_during_startup", 0x67ee6, "45 89 6e 78 49 8b 56 38")
    b.code("""
        test byte ptr [r14+0x74], 0x40
        jnz done
        inc dword ptr [r14+0x78]
      done:
        lea rcx, [rsp+0x40]
        jmp 0x140067efc
    """, "startup_does_not_advance_position", 0x67ef3, "41 ff 46 78 48 8d 4c 24 40")
    b.code("""
        test byte ptr [r14+0x74], 0x40
        jz clear
        and dword ptr [r14+0x74], 0xffffffbf
        mov dword ptr [r14+0x7c], 0
        cmp dword ptr [r14+0x78], 0
        je fresh
        dec dword ptr [r14+0x78]
        jmp clear
      fresh:
        mov dword ptr [r14+0x78], 1
      clear:
        mov byte ptr [rax+0xe2], 0
        jmp 0x140067ff9
    """, "replay_checkpoint_after_startup", 0x67ff2, "c6 80 e2 00 00 00 00")
    b.code("""
        test byte ptr [rbx+0x74], 0x40
        jnz done
        lea eax, [rdi+1]
        mov dword ptr [rbx+0x78], eax
      done:
        jmp 0x14006c187
    """, "startup_reconciliation_keeps_position", 0x6c181, "8d 47 01 89 43 78")

    # The UI path replaces only the playlist subobject via 67070. Preserve a
    # checkpoint only for exactly the same ordered (path,preset) sequence.
    wrapper = b.code("""
        push rbx
        push rsi
        push rdi
        push rbp
        push r12
        push r13
        sub rsp, 0x28
        mov rbx, rcx
        mov rsi, rdx
        mov edi, dword ptr [rbx+0x40]
        mov ebp, dword ptr [rbx+0x3c]
        mov dword ptr [rsp+0x20], 0
        cmp dword ptr [rsi+0x38], 1
        jne copy
        cmp dword ptr [rsi+0x34], 1
        jne copy
        mov eax, dword ptr [rsi+0x3c]
        and eax, 0x28
        cmp eax, 0x28
        jne copy
        cmp dword ptr [rbx+0x38], 1
        jne copy
        cmp dword ptr [rbx+0x34], 1
        jne copy
        mov r12, qword ptr [rbx]
        mov r13, qword ptr [rsi]
        mov rax, qword ptr [rbx+8]
        sub rax, r12
        cmp rax, 0x90
        jb copy
        mov rdx, qword ptr [rsi+8]
        sub rdx, r13
        cmp rax, rdx
        jne copy
      compare:
        mov rcx, r12
        mov rdx, r13
        call 0x14000d0f0
        test al, al
        jz copy
        lea rcx, [r12+0x28]
        lea rdx, [r13+0x28]
        call 0x14000d0f0
        test al, al
        jz copy
        add r12, 0x48
        add r13, 0x48
        cmp r13, qword ptr [rsi+8]
        jb compare
        mov dword ptr [rsp+0x20], 1
      copy:
        mov rcx, rbx
        mov rdx, rsi
        call 0x140067070
        cmp dword ptr [rsp+0x20], 0
        je done
        mov dword ptr [rbx+0x40], edi
        and ebp, 0x40
        or dword ptr [rbx+0x3c], ebp
      done:
        add rsp, 0x28
        pop r13
        pop r12
        pop rbp
        pop rdi
        pop rsi
        pop rbx
        ret
    """, "preserve_same_playlist_on_ui_apply", own_unwind=bytes.fromhex("01 0c 07 00 0c 42 08 d0 06 c0 04 50 03 70 02 60 01 30 00 00"))
    b.call_hook(0x66d11, wrapper, 0x67070, "ui_apply_wrapper")
    return b.finalize()


def build32():
    b = Builder(32)
    def feature(reg, dest):
        return f"""
            cmp dword ptr [{reg}+0x44], 1
            jne {dest}
            cmp dword ptr [{reg}+0x40], 1
            jne {dest}
            mov eax, dword ptr [{reg}+0x48]
            and eax, 0x28
            cmp eax, 0x28
            jne {dest}
        """
    # ECX contains the descriptor destination at the selector hook; feature
    # checking there must not clobber it. EAX is not live across that hook.
    b.code(f"""
        cmp byte ptr [esi+8], 7
        jne done
        push {b.key+16}
        push {b.key}
        mov ecx, esi
        call 0x4681a0
        cmp byte ptr [eax+8], 5
        jne done
        mov ecx, eax
        call 0x467b20
        test al, al
        jz done
        or dword ptr [edi+0x24], 0x20
        cmp dword ptr [edi+0x20], 1
        jne done
        cmp dword ptr [edi+0x1c], 1
        jne done
        test byte ptr [edi+0x24], 8
        jz done
        and dword ptr [edi+0x24], 0xffffffef
      done:
        lea eax, [edi+0x30]
        push eax
        push esi
        jmp 0x45c9b8
    """, "read_rememberposition_setting", 0x5c9b3, "8d 47 30 50 56")
    b.code(feature("ebx", "native") + """
        or dword ptr [ebx+0x48], 0x40
        mov dword ptr [ebx+0x50], 0
        jmp done
      native:
        mov dword ptr [ebx+0x4c], 0
      done:
        jmp 0x4523ce
    """, "keep_checkpoint_during_startup", 0x523c7, "c7 43 4c 00 00 00 00")
    b.code("""
        test byte ptr [ebx+0x48], 0x40
        jnz done
        inc dword ptr [ebx+0x4c]
      done:
        mov eax, dword ptr [ebx+0x28]
        sub eax, dword ptr [ebx+0x24]
        jmp 0x4523df
    """, "startup_does_not_advance_position", 0x523d6, "ff 43 4c 8b 43 28 2b 43 24")
    b.code("""
        test byte ptr [ebx+0x48], 0x40
        jz clear
        and dword ptr [ebx+0x48], 0xffffffbf
        mov dword ptr [ebx+0x50], 0
        cmp dword ptr [ebx+0x4c], 0
        je fresh
        dec dword ptr [ebx+0x4c]
        jmp clear
      fresh:
        mov dword ptr [ebx+0x4c], 1
      clear:
        mov byte ptr [eax+0x9a], 0
        jmp 0x4524ca
    """, "replay_checkpoint_after_startup", 0x524c3, "c6 80 9a 00 00 00 00")
    b.code("""
        test byte ptr [esi+0x48], 0x40
        jnz done
        call 0x44fec0
      done:
        jmp 0x45570a
    """, "startup_reconciliation_keeps_position", 0x55705, "e8 b6 a7 ff ff")
    # Helper compares MSVC x86 strings including SSO and long strings. It
    # preserves the wrapper's ESI/EDI; no absolute data addresses are needed.
    eq = b.code("""
        push esi
        push edi
        mov eax, dword ptr [ecx+0x10]
        cmp eax, dword ptr [edx+0x10]
        jne different
        mov esi, ecx
        mov edi, edx
        cmp dword ptr [esi+0x14], 0xf
        jbe left_ready
        mov esi, dword ptr [esi]
      left_ready:
        cmp dword ptr [edi+0x14], 0xf
        jbe right_ready
        mov edi, dword ptr [edi]
      right_ready:
        mov ecx, eax
        test ecx, ecx
        je equal
        repe cmpsb
        jne different
      equal:
        mov eax, 1
        pop edi
        pop esi
        ret
      different:
        xor eax, eax
        pop edi
        pop esi
        ret
    """, "equal_playlist_strings")
    wrapper = b.code(f"""
        push ebp
        mov ebp, esp
        push ebx
        push esi
        push edi
        sub esp, 0x14
        mov ebx, ecx
        mov esi, dword ptr [ebp+8]
        mov eax, dword ptr [ebx+0x28]
        mov dword ptr [ebp-0x10], eax
        mov eax, dword ptr [ebx+0x24]
        mov dword ptr [ebp-0x14], eax
        mov dword ptr [ebp-0x18], 0
        cmp dword ptr [esi+0x20], 1
        jne copy
        cmp dword ptr [esi+0x1c], 1
        jne copy
        mov eax, dword ptr [esi+0x24]
        and eax, 0x28
        cmp eax, 0x28
        jne copy
        cmp dword ptr [ebx+0x20], 1
        jne copy
        cmp dword ptr [ebx+0x1c], 1
        jne copy
        mov edi, dword ptr [ebx]
        mov eax, dword ptr [esi]
        mov dword ptr [ebp-0x1c], eax
        mov edx, dword ptr [esi+4]
        sub edx, eax
        mov eax, dword ptr [ebx+4]
        sub eax, edi
        cmp eax, 0x68
        jb copy
        cmp eax, edx
        jne copy
      compare:
        mov ecx, edi
        mov edx, dword ptr [ebp-0x1c]
        call {b.base+eq}
        test al, al
        jz copy
        lea ecx, [edi+0x1c]
        mov edx, dword ptr [ebp-0x1c]
        add edx, 0x1c
        call {b.base+eq}
        test al, al
        jz copy
        add edi, 0x34
        add dword ptr [ebp-0x1c], 0x34
        mov eax, dword ptr [ebp-0x1c]
        cmp eax, dword ptr [esi+4]
        jb compare
        mov dword ptr [ebp-0x18], 1
      copy:
        push esi
        mov ecx, ebx
        call 0x451a20
        cmp dword ptr [ebp-0x18], 0
        je done
        mov edx, dword ptr [ebp-0x10]
        mov dword ptr [ebx+0x28], edx
        mov edx, dword ptr [ebp-0x14]
        and edx, 0x40
        or dword ptr [ebx+0x24], edx
      done:
        add esp, 0x14
        pop edi
        pop esi
        pop ebx
        pop ebp
        ret 4
    """, "preserve_same_playlist_on_ui_apply")
    b.call_hook(0x518d3, wrapper, 0x51a20, "ui_apply_wrapper")
    return b.finalize()


def build_ui():
    original = (INPUT / "scripts.js").read_bytes()
    assert sha(original) == PINNED_SHA['scripts.js'], 'Unknown original: scripts.js'
    s = original.decode("utf8")
    replacements = []
    def replace(before, after):
        nonlocal s
        assert s.count(before) == 1, (before[:100], s.count(before))
        replacements.append(dict(before=before, after=after))
        s = s.replace(before, after, 1)
    replace('videosequence:!1,updateonpause:!1}}function ye()',
            'videosequence:!1,updateonpause:!1,rememberposition:!1}}function ye()')
    replace('a.settings=angular.copy(r.settings),a.settings.delay=',
            'a.settings=angular.copy(r.settings),a.settings.rememberposition=!0===a.settings.rememberposition,a.settings.delay=')
    replace('a.togglePlayIntro=function(){"timer"===a.settings.mode&&a.settings.beginfirst&&(a.settings.playintro=!a.settings.playintro)},',
            'a.togglePlayIntro=function(){"timer"===a.settings.mode&&a.settings.beginfirst&&!a.settings.rememberposition&&(a.settings.playintro=!a.settings.playintro)},a.toggleRememberPosition=function(){"timer"===a.settings.mode&&"sorted"===a.settings.order&&a.settings.beginfirst&&(a.settings.rememberposition=!a.settings.rememberposition)},a.$watch("settings.rememberposition",function(e){e&&(a.settings.playintro=!1)}),')
    old = 'settings.mode != \\\'timer\\\' || !settings.beginfirst'
    # Both the label opacity and checkbox disabled expression.
    assert s.count(old) == 2
    for pattern in ['ng-attr-style="opacity: {{('+old+')?0.7:1.0}}"',
                    'cb-disabled="'+old+'"']:
        replace(pattern, pattern.replace(old, old+' || settings.rememberposition'))
    anchor = '<checkbox id="inputPlayIntro"'
    at = s.index(anchor)
    end = s.index(' </div> </div>', at) + len(' </div> </div>')
    native_row_tail = s[at:end]
    row = (' <div class="row" ng-if="settings.mode == \\\'timer\\\'"> '
           '<label ng-click="toggleRememberPosition()" for="inputRememberPosition" class="col-sm-7 control-label" '
           'ng-attr-style="opacity: {{(!settings.beginfirst || settings.order != \\\'sorted\\\')?0.7:1.0}}">Playlist-Position merken</label> '
           '<div class="col-sm-5"> <checkbox id="inputRememberPosition" '
           'cb-disabled="!settings.beginfirst || settings.order != \\\'sorted\\\'" '
           'cb-checked="settings.rememberposition"></checkbox> </div> </div> '
           '<div class="row" ng-if="settings.rememberposition &amp;&amp; settings.mode == \\\'timer\\\' &amp;&amp; settings.order == \\\'sorted\\\' &amp;&amp; settings.beginfirst"> '
           '<div class="col-sm-12"><small>Beim Start zuerst Wallpaper 1, danach das zuletzt gespielte Wallpaper. Wallpaper 1 bleibt in der Rotation.</small></div> </div>')
    replace(native_row_tail, native_row_tail + row)
    patched = s.encode("utf8")
    (OUT / "scripts.js").write_bytes(patched)
    manifest = dict(filename="ui/dist/scripts/scripts.js", kind="text", version="2.8.42", revision="R02",
                    original_sha256=sha(original), patched_sha256=sha(patched), original_size=len(original),
                    patched_size=len(patched), replacements=replacements)
    (OUT / "scripts.patch.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+"\n")
    print('scripts.js',sha(patched))
    return manifest


if __name__ == "__main__":
    build64()
    build32()
    build_ui()

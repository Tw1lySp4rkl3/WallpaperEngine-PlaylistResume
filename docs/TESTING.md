# Testing and verification limits

The playlist behavior, profiles, multiple monitors and manual row selection were
confirmed by the user in Wallpaper Engine on Windows. The runtime EXE/UI/DLL patch
payloads in this package retain those confirmed hashes.

The installer is built as an actual x86 Windows GUI executable. Automated checks
execute its compiled code with substituted Win32 APIs; they do **not** render a
real Windows window or verify real Windows file permissions. The project author subsequently reported successful installation and normal
operation of the v1.0 package on Windows. This user report is separate from the
automated checks and is not an exhaustive test of Windows configurations.
The included historical JSON reports describe the checks at build time.

## Run checks

Build the installer first, then run from `Sources` with the exact originals:

```bash
export WE_ORIGINALS=/path/to/original/files
export WE_INSTALLER_BUILD="$PWD/build-installer"
export WE_BUILD_OUTPUT="$PWD/build-runtime"
python3 tests/test_installer_core.py
python3 tests/test_installer_gui.py
node --test tests/*.test.cjs
```

The portable C tests compile the actual core and embedded recipes, replacing only
filesystem/process calls. They check original and legacy versions, full install,
repeat install, repair, exact restore, state migration, unknown files/receipts,
process guards, backup integrity and failure rollback. Allocation counts must
return to zero. An additional generated build treats v1.0 as an archived release
and tests its receipt, direct upgrade and restore.

The GUI checks boot the real executable and invoke its window handlers in Unicorn.
They cover system-language defaults, DE/EN switching, status/version detection,
Unicode Steam paths, folder-picker prompts, error dialogs, worker access failures,
translated retained logs, locked controls, DPI geometry, calling conventions and
heap cleanup. Program-file hashes and status logic are not substituted.

Node tests independently check the byte transforms, restore and migration, plus
the actual patched UI templates and selection callbacks. `reference-patcher.cjs`
is a test reference; it is not the installer and is not needed by end users.

Detailed reports are included in `Sources/tests/INSTALLER-CORE-RESULTS.json`,
`INSTALLER-GUI-RESULTS.json`, `INSTALLER-BUILD.json` and `RELEASE-VALIDATION.json`.
Earlier native instruction/DLL reports remain as evidence for the unchanged runtime.

## Optional runtime instruction tests

After rebuilding the runtime with original files, the native selector and Windows
DLL scenarios can be run with:

```bash
python3 tests/test_r04_native.py
python3 tests/test_r04_windows_dll.py
```

These use actual x86/x64 instructions or DLL exports at the tested boundaries,
while replacing operating-system calls and selected host callbacks. They provide
additional evidence but do not replace the target program's Windows behavior test.

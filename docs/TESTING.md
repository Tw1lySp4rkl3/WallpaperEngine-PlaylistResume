# Testing and verification limits

The project author confirmed on Windows that the 1.0.1-test preview fixes the
startup regression. v1.0.1 embeds the same runtime bytes as that preview.
The release installer changes the displayed version and recognizes the test
receipt and v1.0 for upgrades and restore.

The installer is built as an x86 Windows GUI executable. Automated checks
execute its compiled code with substituted Win32 APIs. These checks cover the
tested scenarios. Real Windows file permissions and other setups can differ.

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
return to zero. An additional generated build treats the current version as an archived release
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
The native instruction and DLL reports cover the v1.0.1 runtime.

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

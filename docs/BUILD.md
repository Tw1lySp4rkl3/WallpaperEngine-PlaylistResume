# Building PlaylistResume

The installer can be built offline from the included patch catalogues. A runtime
rebuild and tests that execute original program instructions additionally require
the exact original Wallpaper Engine files; these are not distributed here.

## Tools

- Python 3 with `Sources/requirements-analysis.txt` installed.
- Zig **0.17.0** and its Windows headers.
- GCC for the portable C core tests under Linux/WSL.
- Node.js for the independent JavaScript/UI regression tests.

These are development dependencies. End users only need the supplied installer.

## Build the installer

From `Sources` under Linux/WSL:

```bash
export PIRS_ZIG=/path/to/zig
export WE_INSTALLER_BUILD="$PWD/build-installer"
python3 tools/build_installer.py
```

The result is `../PlaylistResumeSetup.exe`. The build first reads
`patches/patches.json` and `patches/legacy.json`, generates `installer/payloads.c`,
and embeds all required data. The executable does not read the source JSON files
at installation time. The generated C file is also included for inspection.

## Rebuild the runtime

Provide original `wallpaper32.exe`, `wallpaper64.exe` and `scripts.js` in a separate
directory. The builders enforce their pinned SHA-256 hashes.

```bash
export WE_ORIGINALS=/path/to/original/files
export WE_BUILD_OUTPUT="$PWD/build-runtime"
python3 tools/build_runtime.py
```

The build produces both patched EXEs, the patched UI script, both runtime DLLs,
individual intermediate manifests and the combined `patches.json`. After reviewing
the output, copy the combined catalogue to `Sources/patches/patches.json` and rebuild
the installer. Never include the original or patched manufacturer EXEs/UI bundles
in a source distribution.

The runtime builder uses two implementation modules: `build_r02.py` supplies the
native selector/UI foundation and `build_r04.py` adds persistent checkpoints and
explicit playlist-row selection. They are build dependencies of the current
runtime, rather than installers applied in sequence.

## Adding a future release

Before replacing current patch data, preserve that release in **the same
`legacy.json`**:

1. Copy its version and full `files` list from the previous `patches.json` into a
   new legacy release record. Give it an unused `compatibility_id` and set
   `preview` to `false` for a public release. IDs 1 and 6 are reserved for current
   and partial installations; the existing previews use 2–5.
2. Include its installation `receipt`, as returned by
   `tools/patch_catalog.py`'s `load_catalog()['receipt']` for that old release.
   The receipt contains the old project version, engine version and payload
   fingerprint. The reader validates it and serializes its fields canonically.
3. Update the current catalogue and runtime recipes to the new project version.
   Existing `same_as` aliases can refer to the newly archived version. For example,
   the R04 alias refers to version 1.0 and continues to resolve when 1.0 is archived.
4. Update the installer title, Windows version resources and release text for the
   new project version. The catalogue does not automatically rewrite GUI resources.
5. Rebuild and test recognition, direct upgrade and restore for the archived
   version. Run the installer and runtime checks described in [TESTING.md](TESTING.md).

`test_archived_v1_receipt_upgrade_and_restore` simulates this with v1.0 archived
and a later current catalogue. It compiles the actual installation core and
generated payload and checks version recognition, update and direct restore.

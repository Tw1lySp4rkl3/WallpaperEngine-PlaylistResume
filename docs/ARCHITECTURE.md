# Architecture

## Installer

`Sources/installer/installer_gui.c` creates a standard Win32 window with version,
directory selection, installed status, install, restore and log controls.
`installer_language.c` provides German/English text. Language changes redraw the
cached status and existing log without rereading or modifying the engine files.
Windows error codes are retained separately for localized descriptions.

The Windows adapter handles Unicode paths, Steam registry/library discovery,
process enumeration and file operations. It checks the installer's own directory,
Steam registry paths and `steamapps/libraryfolders.vdf`. A running Wallpaper Engine
or UI process prevents a modifying operation. The installer does not kill processes,
install services, set an autorun entry or use the network.

## Current and legacy data

There are two source data files:

- `patches.json`: the current five runtime recipes and project/engine versions.
- `legacy.json`: all earlier supported releases, their rollback recipes, optional
  installation receipts and aliases to identical payloads.

The schema reader validates both files before generating C data. The R04 entry is
an alias to 1.0, avoiding duplicate recipes. Earlier releases remain supported for
upgrade and restore. The generated installer embeds the recipes and a legacy
release table; it has no runtime dependency on either JSON file.

Each installed file is checked by exact length and SHA-256. A version receipt is
accepted only if it belongs to the current or a catalogued legacy release.
Status classification also checks the matching release's file set and receipt.
Known mixed installations remain repairable; unknown files or receipts stop the
operation before program changes.

For updates, known old patches are reversed into the original bytes in memory,
then the current recipes are applied. This is a full installation, not a sequence
of earlier patch installers. Restore reconstructs the originals using the matching
recipe and can work without an existing backup directory.

## File transaction

All target data is generated and validated before modifying program files.
Originals and existing state are backed up under `playlist-resume-backup`.
Changed original backups are rejected. Files are prepared using exclusively
created temporary files, flushed, then replaced with `MoveFileExW`.

New DLLs are installed before their users; obsolete DLLs are removed after replacing
the EXEs. Position/log migration and the installation receipt belong to the same
transaction. Commit failures restore the previous state in reverse order; incomplete
rollback is explicitly reported. Restore retains user settings and saved positions.

## Runtime

The two runtime DLLs use Kernel32 and execute within Wallpaper Engine. They do not
need a service, background thread, open settings window or shutdown callback.
Native hooks call `ResumePrepare` before selecting a wallpaper and `ResumeCommit`
after the actual renderer is known.

The startup wallpaper is protected from overwriting the regular checkpoint.
Following the startup prelude, selection replays the saved wallpaper and continues
the sorted playlist. A manual click in the lower playlist strip carries a one-shot
row index at the top level of the selection message. The live selectPlaylist
path reads it from the incoming message and removes it from the copy used for
configuration. Older settings.resumeposition values are ignored by the native
parser and discarded by the UI when loading or serializing playlist settings.
Compatibility prompts recheck that the monitor, list and clicked row are still
current before applying the request. The renderer must match the selected file
and any explicitly named preset before the checkpoint is committed. If the
playlist leaves the preset unspecified, the engine may resolve an effective preset.

The state key combines the monitor ID and ordered file/preset pairs. The binary
`WPRS0001` format contains a header, record count, CRC32 and fixed-size records
with the key, list length, zero-based position and use counter. The runtime supports
up to 512 records, 64 monitor sessions and 64 active call frames. Known earlier
state is migrated without replacing an existing valid neutral state file.

Runtime files:

- `PlaylistResume32.dll`, `PlaylistResume64.dll` in the engine folder.
- `bin/playlist-resume.bin`: saved positions.
- `bin/playlist-resume.log`: runtime event log.
- `bin/playlist-resume-install.json`: project version and payload fingerprint.

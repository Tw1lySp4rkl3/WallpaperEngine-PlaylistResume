# Changelog

## v1.0.1 - 2026-11-04

- Fix a saved playlist click being replayed at startup and overwriting the latest position.
- Restore the startup sequence of wallpaper 1 followed by the last saved wallpaper.
- Keep the v1.0 and test builds recognizable for direct upgrades and restore.

Supported engine version: Wallpaper Engine 2.8.42 Steam Edition.

## v1.0 - 2026-10-31

- Remember sorted playlist positions separately for each monitor and playlist.
- Play the first wallpaper as an intro, then replay the saved position and continue.
- Keep checkpoints across restarts and loading monitor profiles.
- Choose a new position by clicking an entry in the lower playlist strip.
- Supply a standalone Windows installer with Steam detection, manual directory
  selection, installed-version status, restore, and German/English language selection.
- Preserve supported preview migrations in a single legacy catalogue.
- Publish source, build instructions, tests, and noncommercial license terms.

The public package keeps the tested v1.0 installer and runtime bytes unchanged.
Publication adds documentation, license terms, contribution guidance, and checksums.
Supported engine version: Wallpaper Engine 2.8.42 Steam Edition.

# PlaylistResume v1.0

Unofficial playlist resume mod for **Wallpaper Engine 2.8.42 – Steam Edition**.

**[Download PlaylistResume_v1.0.zip](https://github.com/Tw1lySp4rkl3/WallpaperEngine-PlaylistResume/raw/refs/heads/main/downloads/PlaylistResume_v1.0.zip)**

Windows | 32-bit and 64-bit Wallpaper Engine | DE/EN installer

**Source available for personal, noncommercial use. Commercial exploitation and
independent distributions require separate permission.** See [LICENSE](LICENSE)
and [Contributing](CONTRIBUTING.md). Not affiliated with Wallpaper Engine.

[English](#english) · [Deutsch](#deutsch)

## English

PlaylistResume plays the first wallpaper on startup, then replays the wallpaper
where the playlist last stopped and continues from there.

**Example:** last wallpaper **4** → restart → **1 → 4 → 5 → 6 …**

Wallpaper 1 remains part of the normal rotation. Each regular change saves the
current position. After a restart, the resumed wallpaper receives a full interval;
the previous session's remaining time is not restored.

### Features

- A **“Playlist-Position merken”** (remember playlist position) checkbox in the
  existing playlist settings.
- Separate saved positions for each monitor and playlist, including presets.
- Positions survive program restarts and loading a saved monitor profile.
- Click an entry in the **lower playlist strip** to choose a new position:
  click wallpaper 2 → the next change plays wallpaper 3. Clicking wallpaper 1
  also works while the startup wallpaper is already showing.
- A complete installer with Steam folder detection, manual folder selection,
  installed-version status, restore, and German/English language selection.

### Install

1. Download **PlaylistResume_v1.0.zip** using the link above and extract the entire ZIP.
2. Fully exit Wallpaper Engine using its **system tray icon**. Closing only the
   settings window is not enough.
3. Run **PlaylistResumeSetup.exe**.
4. Check the detected installation folder or use **Browse …**. Select the
   `wallpaper_engine` folder containing `wallpaper32.exe` and `wallpaper64.exe`.
   Typical location: `C:\Program Files (x86)\Steam\steamapps\common\wallpaper_engine`.
5. Click **Install**, wait for completion, then start Wallpaper Engine as usual.

No previous mod version, Node.js, or additional download is required. The installer
contains all patch data and both runtime DLLs. It installs the mod into your own
Wallpaper Engine installation. Unknown or unsupported program files are rejected.

Choose **Deutsch** or **English** under **Sprache / Language** at the top right.
This changes the installer language; Wallpaper Engine keeps its own language.

### Required playlist settings

| Setting | Value |
| --- | --- |
| Wallpaper changes | Timer / timed sequence |
| Order | Sorted |
| Always start with the first wallpaper | On |
| Show the first wallpaper only at startup | Off |
| **Playlist-Position merken** | **On** |

If using monitor profiles, save the profile again after setting these options.
Reloading a profile shows wallpaper 1 first; **the following change resumes the
saved position**. Use the lower playlist strip to set a position manually.
The main wallpaper catalog keeps its existing selection behavior.

Identical ordered playlists on the same monitor share a saved position across
profile names. Changing the order, paths, presets or monitor ID creates a new
playlist identity.

### Update or remove

For an update, fully exit Wallpaper Engine and run the new installer against the
same folder. Supported earlier versions are recognized and updated; saved positions
are preserved.

To remove the mod, fully exit Wallpaper Engine and click **Restore original** in
the installer. This restores the original EXEs and interface and removes known
mod DLLs and the installation receipt. Settings and saved positions are retained.
Originals and existing state files are backed up in `playlist-resume-backup`.
Steam updates or file verification can replace patched program files.

### License and contributions

Free for personal, noncommercial use under the custom
[PlaylistResume Noncommercial License 1.0](LICENSE). You may inspect and modify
the code for personal noncommercial use and propose changes through pull requests.
Selling, monetizing downloads, integrating the code into commercial products,
and independent standalone distributions are not generally permitted.
GitHub's own rights for viewing and forking public repositories remain unaffected.

The maintainer reviews and accepts contributions; contributors retain rights in
their own work and grant the permissions described in LICENSE. See
[Contributing](CONTRIBUTING.md). This is source-available software with usage
restrictions, rather than OSI-approved open source.

The license covers only material the project may license. Wallpaper Engine
retains its own terms; its original executables and complete UI bundles are not
included. See [Third-party notices](THIRD_PARTY_NOTICES.md).

## Deutsch

PlaylistResume zeigt beim Start zuerst Wallpaper 1. Anschließend wird das zuletzt
regulär abgespielte Wallpaper erneut gezeigt; danach läuft die Playlist weiter.

**Beispiel:** zuletzt Wallpaper **4** → Neustart → **1 → 4 → 5 → 6 …**

Wallpaper 1 bleibt Bestandteil der normalen Rotation. Jeder reguläre Wechsel
speichert die aktuelle Position. Nach einem Neustart erhält das fortgesetzte
Wallpaper ein volles Zeitintervall; die alte Restlaufzeit wird nicht übernommen.

### Funktionen

- **„Playlist-Position merken“** als Checkbox in den vorhandenen Playlist-Einstellungen.
- Getrennte Positionen pro Monitor und Playlist, einschließlich Presets.
- Gespeicherte Positionen bleiben bei Programmneustart und Profil-Laden erhalten.
- Ein Klick im **unteren Playlist-Streifen** setzt eine neue Position:
  Klick auf Wallpaper 2 → beim nächsten Wechsel folgt Wallpaper 3.
  Auch Wallpaper 1 kann angeklickt werden, während es gerade als Startbild läuft.
- Vollständiger Installer mit Steam-Ordnersuche, manueller Ordnerauswahl,
  Versionsanzeige, Wiederherstellung und Sprachwechsel Deutsch/Englisch.

### Installation

1. **PlaylistResume_v1.0.zip** über den Link oben herunterladen und vollständig entpacken.
2. Wallpaper Engine über das **Symbol im Infobereich der Taskleiste vollständig
   beenden**. Nur das Einstellungsfenster zu schließen reicht nicht.
3. **PlaylistResumeSetup.exe** starten.
4. Den erkannten Installationsordner prüfen oder über **Durchsuchen …** auswählen.
   Gemeint ist `wallpaper_engine` mit `wallpaper32.exe` und `wallpaper64.exe` darin.
   Typischer Pfad: `C:\Program Files (x86)\Steam\steamapps\common\wallpaper_engine`.
5. **Installieren** anklicken, den Abschluss abwarten und Wallpaper Engine starten.

Eine vorherige Mod-Version, Node.js oder zusätzliche Downloads werden nicht
benötigt. Alle Patchdaten und beide DLLs sind im Installer enthalten. Der Mod wird
in deine vorhandene Wallpaper-Engine-Installation eingebaut. Unbekannte oder nicht
unterstützte Programmdateien werden abgewiesen.

Oben rechts unter **Sprache / Language** zwischen **Deutsch** und **English**
wechseln. Das betrifft den Installer; Wallpaper Engine behält seine eigene Sprache.

### Benötigte Playlist-Einstellungen

| Einstellung | Wert |
| --- | --- |
| Hintergrund ändern | In zeitlicher Abfolge / Timer |
| Reihenfolge | Sortiert |
| Immer mit erstem Hintergrund starten | An |
| Erster Hintergrund wird nur beim Starten gezeigt | Aus |
| **Playlist-Position merken** | **An** |

Bei Verwendung von Monitorprofilen das Profil danach erneut speichern.
Beim Profil-Laden erscheint zuerst Wallpaper 1; **der nächste Wechsel setzt an der
gespeicherten Position fort**. Zum manuellen Setzen den unteren Playlist-Streifen
verwenden. Die Auswahl im großen Wallpaper-Katalog behält ihr bisheriges Verhalten.

Identische geordnete Playlisten auf demselben Monitor teilen ihren Stand über
Profilnamen hinweg. Änderungen an Reihenfolge, Pfaden, Presets oder Monitor-ID
ergeben eine neue Playlist-Identität.

### Aktualisieren oder entfernen

Für ein Update Wallpaper Engine vollständig beenden und den neuen Installer für
denselben Ordner starten. Unterstützte Vorversionen werden erkannt und aktualisiert;
die gespeicherten Positionen bleiben erhalten.

Zum Entfernen Wallpaper Engine vollständig beenden und im Installer **Original
wiederherstellen** anklicken. Das stellt die ursprünglichen EXEs und die Oberfläche
wieder her und entfernt bekannte Mod-DLLs sowie den Versionsbeleg. Einstellungen
und Positionen bleiben erhalten. Originale und vorhandene Zustandsdateien werden
unter `playlist-resume-backup` gesichert. Steam-Updates oder Dateiüberprüfungen
können die gepatchten Programmdateien ersetzen.

### Lizenz und Mitarbeit

Kostenlose private, nichtkommerzielle Nutzung unter der individuellen
[PlaylistResume Noncommercial License 1.0](LICENSE). Du darfst den Quelltext
ansehen, für private nichtkommerzielle Zwecke anpassen und Änderungen per
Pull Request vorschlagen. Verkauf, monetarisierte Downloads, Einbau in
kommerzielle Produkte und eigenständige Weiterveröffentlichungen sind nicht
allgemein erlaubt; sie benötigen eine gesonderte Erlaubnis.
Die von GitHub eingeräumten Rechte zum Ansehen und Forken bleiben unberührt.

Über die Aufnahme entscheidet der Maintainer. Mitwirkende behalten Rechte an
ihren eigenen Beiträgen und räumen die in LICENSE beschriebenen Nutzungsrechte
ein. Hinweise dazu stehen in [Mitwirken](CONTRIBUTING.md). Der englische Lizenztext
ist maßgeblich. Das Projekt ist wegen seiner Nutzungseinschränkungen
"source available".

Die Projektlizenz gilt nur für Material, an dem die erforderlichen Rechte
bestehen. Für Wallpaper Engine gelten weiterhin dessen eigene Bedingungen.
Siehe [Hinweise zu Fremdmaterial](THIRD_PARTY_NOTICES.md).

## Source code / Quelltext

| Folder | Contents |
| --- | --- |
| `Sources/installer/` | Native Windows installer and installation engine |
| `Sources/src/` | Runtime DLL source |
| `Sources/patches/patches.json` | Current runtime patch recipes |
| `Sources/patches/legacy.json` | Previous versions, recognition and rollback recipes |
| `Sources/tools/` | Build tools and catalogue reader |
| `Sources/tests/` | Tests and verification results |

Developer documentation: [Build](docs/BUILD.md), [Architecture](docs/ARCHITECTURE.md),
[Testing and verification limits](docs/TESTING.md).

## Verification / Prüfung

The installer and runtime are the same binaries as the tested v1.0 package.
The project author reports successful installation and playback on Windows.
Automated installer-core, compiled-GUI emulation, and JavaScript regression
checks are documented in [Testing](docs/TESTING.md). These checks cover the
supported files and tested scenarios, not every Windows configuration.

The installer modifies both engine EXEs and the UI script and adds two runtime
DLLs. It works locally and does not install a service or contact a server.
The standalone installer is not code-signed. Use the supplied restore action to
return known patched files to their supported original state.

SHA-256 checksums: [ZIP](https://github.com/Tw1lySp4rkl3/WallpaperEngine-PlaylistResume/blob/main/downloads/SHA256SUMS) and [installer](SHA256SUMS).

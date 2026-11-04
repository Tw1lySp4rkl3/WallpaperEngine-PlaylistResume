#include "installer_language.h"
typedef struct { const char *de,*en; int prefix; } Translation;
static const Translation translations[]={
    {"Vollständiger Installer für Wallpaper Engine 2.8.42 (Steam).\r\nInstalliert den Mod direkt oder aktualisiert eine vorhandene Installation.",
     "Complete installer for Wallpaper Engine 2.8.42 (Steam).\r\nInstalls the mod or updates an existing installation.",0},
    {"Wallpaper-Engine-Ordner","Wallpaper Engine folder",0},
    {"Bitte den Ordner auswählen, in dem wallpaper32.exe und wallpaper64.exe liegen.\r\nDen Ordner wallpaper_engine wählen – nicht bin oder den Steam-Hauptordner.",
     "Select the folder containing wallpaper32.exe and wallpaper64.exe.\r\nChoose wallpaper_engine, rather than bin or the main Steam folder.",0},
    {"Durchsuchen …","Browse …",0},
    {"Standardmäßig unter: ","Default location: ",1},
    {"Installationsstatus","Installation status",0},
    {"Wird geprüft …","Checking …",0},
    {"Status prüfen","Check status",0},
    {"Installieren","Install",0},
    {"Original wiederherstellen","Restore original",0},
    {"Schließen","Close",0},
    {"Protokoll","Log",0},
    {"Die benötigten Playlist-Einstellungen stehen in README.md.","See README.md for the required playlist settings.",0},
    {"Bitte einen gültigen Wallpaper-Engine-Ordner auswählen.","Please select a valid Wallpaper Engine folder.",0},
    {"Installation läuft …","Installing …",0},
    {"Wiederherstellung läuft …","Restoring …",0},
    {"Die Dateien werden geprüft, gesichert und anschließend übernommen.","Files are being checked, backed up and then applied.",0},
    {"Der Vorgang konnte nicht gestartet werden.","The operation could not be started.",0},
    {"Den Ordner wallpaper_engine auswählen, in dem wallpaper32.exe und wallpaper64.exe liegen.",
     "Select the wallpaper_engine folder containing wallpaper32.exe and wallpaper64.exe.",0},
    {"Die automatische Rücknahme war unvollständig. Bitte das Protokoll und den Ordner playlist-resume-backup prüfen.",
     "Automatic rollback was incomplete. Please check the log and the playlist-resume-backup folder.",0},
    {"Der Vorgang wurde nicht abgeschlossen. Der vorherige Stand wurde beibehalten oder wiederhergestellt. Details stehen im Protokoll.",
     "The operation did not complete. The previous state was retained or restored. See the log for details.",0},
    {"Windows-Fehlercode: ","Windows error code: ",1},

    /* Status and transaction messages from installer_core.c. */
    {"Dateien konnten nicht gelesen werden","Files could not be read",0},
    {"Nicht gefunden","Not found",0},
    {"Bitte den Wallpaper-Engine-Installationsordner auswählen.","Please select the Wallpaper Engine installation folder.",0},
    {"Unbekannte oder nicht unterstützte Dateien","Unknown or unsupported files",0},
    {"Unbekannte Mod-Installationsinfo","Unknown mod installation information",0},
    {"Die vorhandene Installationsinfo gehört nicht zu dieser Ausgabe.","The existing installation information does not match this release.",0},
    {"Installiert – v1.0","Installed – v1.0",0},
    {"Installiert – v1.0.1","Installed – v1.0.1",0},
    {"Installiert – Vorabversion R04","Installed – preview R04",0},
    {"Installiert – Vorabversion R03","Installed – preview R03",0},
    {"Installiert – Vorabversion R02","Installed – preview R02",0},
    {"Installiert – Vorabversion R01","Installed – preview R01",0},
    {"Installiert – Vorabversion ","Installed – preview ",1},
    {"Installiert – v","Installed – v",1},
    {"Nicht installiert","Not installed",0},
    {"Unvollständige Installation – Reparatur möglich","Incomplete installation – repair available",0},
    {"Wallpaper Engine 2.8.42 (Steam): geprüfte Dateien erkannt.","Wallpaper Engine 2.8.42 (Steam): verified files detected.",0},
    {"Beschädigter Positionsspeicher: ","Corrupt position data: ",1},
    {"Vorhandene Original-Sicherung ist verändert: ","Existing original backup has been modified: ",1},
    {"Nicht genügend Arbeitsspeicher.","Not enough memory.",0},
    {"Original konnte nicht rekonstruiert werden: ","Original could not be reconstructed: ",1},
    {"Ungültige Patchdaten: ","Invalid patch data: ",1},
    {"PlaylistResume v1.0.1 ist bereits vollständig installiert.","PlaylistResume v1.0.1 is already fully installed.",0},
    {"Die Originaldateien sind bereits vorhanden.","The original files are already present.",0},
    {"Wallpaper Engine läuft noch. Bitte über das Taskleistensymbol vollständig beenden und erneut versuchen.",
     "Wallpaper Engine is still running. Fully exit it using the system tray icon, then try again.",0},
    {"Sicherung fehlgeschlagen. Programmdateien wurden nicht geändert.","Backup failed. Program files have not been changed.",0},
    {"Vorbereiten fehlgeschlagen: ","Preparation failed: ",1},
    {"Datei wurde zwischenzeitlich geändert: ","File changed during the operation: ",1},
    {"Datei konnte nicht ersetzt oder entfernt werden: ","File could not be replaced or removed: ",1},
    {"Prüfung nach dem Ersetzen fehlgeschlagen: ","Verification after replacement failed: ",1},
    {"Übernommen: ","Applied: ",1},
    {"Entfernt: ","Removed: ",1},
    {"PlaylistResume v1.0.1 wurde installiert.","PlaylistResume v1.0.1 has been installed.",0},
    {"Originaldateien wurden wiederhergestellt. Positionen und Einstellungen bleiben erhalten.",
     "Original files have been restored. Positions and settings are preserved.",0},
    {"Sicherung: ","Backup: ",1},
    {"Rücknahme fehlgeschlagen: ","Rollback failed: ",1},
    {"Rücknahme unvollständig. Originale liegen unter playlist-resume-backup.",
     "Rollback incomplete. Original files are in playlist-resume-backup.",0},
    {"Der vorherige Stand wurde beibehalten oder wiederhergestellt.","The previous state was retained or restored.",0},

    /* Windows adapter errors. System error descriptions are rendered separately. */
    {"Dateipfad zu lang","File path is too long",0},
    {"Lesen fehlgeschlagen","Read failed",0},
    {"Ungültige Dateigröße","Invalid file size",0},
    {"Nicht genügend Arbeitsspeicher","Not enough memory",0},
    {"Datei konnte nicht vollständig gelesen werden","File could not be read completely",0},
    {"Sicherungsordner konnte nicht angelegt werden","Backup folder could not be created",0},
    {"Datei konnte nicht angelegt werden","File could not be created",0},
    {"Schreiben fehlgeschlagen","Write failed",0},
    {"Dateitausch fehlgeschlagen","File replacement failed",0},
    {"Datei konnte nicht entfernt werden","File could not be removed",0},
    {"Prozessprüfung fehlgeschlagen","Process check failed",0}
};
PrLanguage pr_default_language(unsigned id){return (id&0x3ffu)==0x07u?PR_GERMAN:PR_ENGLISH;}
int pr_localize(PrLanguage language,const char *source,char *out,size_t capacity){
    const char *first=source,*tail="";
    if(language==PR_ENGLISH){
        for(size_t i=0;i<sizeof translations/sizeof translations[0];i++){
            const Translation *t=translations+i;size_t n=0;
            while(t->de[n]&&source[n]&&t->de[n]==source[n])n++;
            if(!t->de[n]&&(t->prefix||!source[n])){first=t->en;tail=source+n;break;}
        }
    }
    size_t a=0,b=0;while(first[a])a++;while(tail[b])b++;
    if(!capacity||a>=capacity||b>=capacity-a){if(capacity)out[0]=0;return 0;}
    for(size_t i=0;i<a;i++)out[i]=first[i];for(size_t i=0;i<=b;i++)out[a+i]=tail[i];return 1;
}

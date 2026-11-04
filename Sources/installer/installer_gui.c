/* Standard Win32 controls, no browser, framework, launcher or console window. */
#include "installer_windows.h"
#include "installer_language.h"
#include <shlobj.h>
#include <objbase.h>
#define ID_DIRECTORY 100
#define ID_BROWSE 101
#define ID_REFRESH 102
#define ID_INSTALL 103
#define ID_RESTORE 104
#define ID_CLOSE 105
#define ID_LANGUAGE 106
#define MSG_LOG (WM_APP+1)
#define MSG_DONE (WM_APP+2)
static HWND window,directory,browse,refresh,install,restore,close_button,status_label,detail_label,log_box;
static HWND introduction,folder_group,folder_help,default_hint,status_group,log_label,footer,language_box;
static HINSTANCE instance;static HFONT font;static int dpi=96,busy,root_valid;
static PrWindows *platform;static PrStatus current_status;static PrLanguage language;
static WCHAR input[PR_PATH_CAP],default_path[PR_PATH_CAP],line[PR_PATH_CAP];
static const WCHAR CLASS_NAME[]=L"PlaylistResumeSetupWindow";
static const char INTRODUCTION[]="Vollständiger Installer für Wallpaper Engine 2.8.42 (Steam).\r\nInstalliert den Mod direkt oder aktualisiert eine vorhandene Installation.";
static const char FOLDER_HELP[]="Bitte den Ordner auswählen, in dem wallpaper32.exe und wallpaper64.exe liegen.\r\nDen Ordner wallpaper_engine wählen – nicht bin oder den Steam-Hauptordner.";
static const char FOOTER[]="Die benötigten Playlist-Einstellungen stehen in README.md.";
typedef struct LogEntry {struct LogEntry *next;DWORD error_code;int system_error;char text[];} LogEntry;
static LogEntry *log_first,*log_last;

static int scale(int n){return MulDiv(n,dpi,96);}
static WCHAR *localized(const char *s){
    char translated[2048];return pr_wide(pr_localize(language,s,translated,sizeof translated)?translated:s);
}
static void set_text(HWND h,const char *s){WCHAR *wide=localized(s);if(wide){SetWindowTextW(h,wide);pr_free(wide);}}
static HWND control(const WCHAR *class_name,const char *title,DWORD style,int x,int y,int width,int height,int id,DWORD extra){
    WCHAR *wide=localized(title);
    HWND h=CreateWindowExW(extra,class_name,wide?wide:L"",WS_CHILD|WS_VISIBLE|style,scale(x),scale(y),scale(width),scale(height),window,(HMENU)(INT_PTR)id,instance,0);
    if(wide)pr_free(wide);if(h)SendMessageW(h,WM_SETFONT,(WPARAM)font,TRUE);return h;
}
static void log_fragment(const WCHAR *s){SendMessageW(log_box,EM_REPLACESEL,FALSE,(LPARAM)s);}
static void render_entry(const LogEntry *entry){
    int n=GetWindowTextLengthW(log_box);SendMessageW(log_box,EM_SETSEL,n,n);
    WCHAR *wide=localized(entry->text);if(wide){log_fragment(wide);pr_free(wide);}
    if(entry->system_error){
        WCHAR description[512];description[0]=0;
        DWORD lang=language==PR_GERMAN?MAKELANGID(LANG_GERMAN,SUBLANG_GERMAN):MAKELANGID(LANG_ENGLISH,SUBLANG_ENGLISH_US);
        DWORD flags=FORMAT_MESSAGE_FROM_SYSTEM|FORMAT_MESSAGE_IGNORE_INSERTS;
        if(!FormatMessageW(flags,0,entry->error_code,lang,description,512,0))
            FormatMessageW(flags,0,entry->error_code,0,description,512,0);
        size_t end=pr_wlength(description);while(end&&(description[end-1]=='\r'||description[end-1]=='\n'))description[--end]=0;
        log_fragment(L": ");
        if(!end){
            wide=localized("Windows-Fehlercode: ");if(wide){log_fragment(wide);pr_free(wide);}
            WCHAR digits[16];unsigned count=0;DWORD code=entry->error_code;
            do{digits[count++]=(WCHAR)('0'+code%10);code/=10;}while(code);
            for(unsigned i=0;i<count;i++)description[i]=digits[count-1-i];description[count]=0;
        }
        log_fragment(description);
    }
    log_fragment(L"\r\n");SendMessageW(log_box,EM_SCROLLCARET,0,0);
}
static LogEntry *new_entry(const char *s,int system_error,DWORD code){
    size_t n=0;while(s[n])n++;LogEntry *entry=pr_alloc(sizeof *entry+n+1);if(!entry)return 0;
    entry->next=0;entry->error_code=code;entry->system_error=system_error;
    for(size_t i=0;i<=n;i++)entry->text[i]=s[i];return entry;
}
static void append_entry(LogEntry *entry){
    if(!entry)return;if(log_last)log_last->next=entry;else log_first=entry;log_last=entry;render_entry(entry);
}
static void clear_log(void){
    LogEntry *entry=log_first;while(entry){LogEntry *next=entry->next;pr_free(entry);entry=next;}log_first=log_last=0;
    if(log_box)SetWindowTextW(log_box,L"");
}
static void thread_log(const char *s){
    LogEntry *entry=new_entry(s,0,0);if(entry&&!PostMessageW(window,MSG_LOG,0,(LPARAM)entry))pr_free(entry);
}
static void thread_error(const char *s,DWORD code){
    LogEntry *entry=new_entry(s,1,code);if(entry&&!PostMessageW(window,MSG_LOG,0,(LPARAM)entry))pr_free(entry);
}
static void show_status(void){
    if(!root_valid){
        set_text(status_label,"Nicht gefunden");set_text(detail_label,"Bitte einen gültigen Wallpaper-Engine-Ordner auswählen.");
        EnableWindow(install,FALSE);EnableWindow(restore,FALSE);return;
    }
    set_text(status_label,current_status.label);set_text(detail_label,current_status.detail);
    EnableWindow(install,current_status.can_install);EnableWindow(restore,current_status.can_restore);
}
static void status(void){
    if(busy)return;GetWindowTextW(directory,input,PR_PATH_CAP);root_valid=pr_win_set_root(platform,input);
    if(root_valid){platform->logger=0;platform->error_logger=0;PrFS fs=pr_win_fs(platform);pr_status(&fs,&current_status);}
    show_status();
}
static void default_text(void){
    WCHAR *prefix=localized("Standardmäßig unter: ");pr_wcopy(line,PR_PATH_CAP,prefix?prefix:L"");if(prefix)pr_free(prefix);
    pr_wappend(line,PR_PATH_CAP,default_path);SetWindowTextW(default_hint,line);
}
static void apply_language(void){
    set_text(introduction,INTRODUCTION);set_text(folder_group,"Wallpaper-Engine-Ordner");set_text(folder_help,FOLDER_HELP);
    set_text(browse,"Durchsuchen …");default_text();set_text(status_group,"Installationsstatus");set_text(refresh,"Status prüfen");
    set_text(install,"Installieren");set_text(restore,"Original wiederherstellen");set_text(close_button,"Schließen");
    set_text(log_label,"Protokoll");set_text(footer,FOOTER);show_status();
    SetWindowTextW(log_box,L"");for(LogEntry *entry=log_first;entry;entry=entry->next)render_entry(entry);
}
static void lock_controls(int locked){
    busy=locked;EnableWindow(directory,!locked);EnableWindow(browse,!locked);EnableWindow(refresh,!locked);EnableWindow(close_button,!locked);EnableWindow(language_box,!locked);
    if(locked){EnableWindow(install,FALSE);EnableWindow(restore,FALSE);}
    HMENU menu=GetSystemMenu(window,FALSE);if(menu)EnableMenuItem(menu,SC_CLOSE,MF_BYCOMMAND|(locked?MF_GRAYED:MF_ENABLED));
}
static DWORD WINAPI work(void *argument){
    PrFS fs=pr_win_fs(platform);int result=pr_run(&fs,(int)(INT_PTR)argument);
    platform->logger=0;platform->error_logger=0;PostMessageW(window,MSG_DONE,(WPARAM)result,0);return 0;
}
static void start_action(int action){
    if(busy)return;KillTimer(window,1);GetWindowTextW(directory,input,PR_PATH_CAP);
    if(!pr_win_set_root(platform,input)){status();return;}
    clear_log();lock_controls(1);platform->logger=thread_log;platform->error_logger=thread_error;
    set_text(status_label,action==1?"Installation läuft …":"Wiederherstellung läuft …");
    set_text(detail_label,"Die Dateien werden geprüft, gesichert und anschließend übernommen.");
    HANDLE thread=CreateThread(0,0,work,(void*)(INT_PTR)action,0,0);
    if(thread)CloseHandle(thread);
    else{platform->logger=0;platform->error_logger=0;lock_controls(0);append_entry(new_entry("Der Vorgang konnte nicht gestartet werden.",0,0));status();}
}
static int CALLBACK folder_callback(HWND h,UINT message,LPARAM parameter,LPARAM data){
    (void)parameter;if(message==BFFM_INITIALIZED)SendMessageW(h,BFFM_SETSELECTIONW,TRUE,data);return 0;
}
static void choose_folder(void){
    GetWindowTextW(directory,input,PR_PATH_CAP);WCHAR *title=localized("Den Ordner wallpaper_engine auswählen, in dem wallpaper32.exe und wallpaper64.exe liegen.");
    BROWSEINFOW info;memset(&info,0,sizeof info);info.hwndOwner=window;info.lpszTitle=title;
    info.ulFlags=BIF_RETURNONLYFSDIRS|BIF_NEWDIALOGSTYLE|BIF_EDITBOX;
    info.lpfn=folder_callback;info.lParam=(LPARAM)input;
    PIDLIST_ABSOLUTE selected=SHBrowseForFolderW(&info);if(title)pr_free(title);
    if(selected){if(SHGetPathFromIDListW(selected,input)){SetWindowTextW(directory,input);KillTimer(window,1);status();}CoTaskMemFree(selected);}
}
static void error_box(HWND h,const char *message){
    WCHAR *wide=localized(message);if(wide){MessageBoxW(h,wide,L"PlaylistResume v1.0.1",MB_OK|MB_ICONERROR);pr_free(wide);}
}
static LRESULT CALLBACK procedure(HWND h,UINT message,WPARAM w,LPARAM l){
    switch(message){
    case WM_COMMAND:
        if(LOWORD(w)==ID_DIRECTORY&&HIWORD(w)==EN_CHANGE&&!busy){SetTimer(h,1,450,0);return 0;}
        if(LOWORD(w)==ID_LANGUAGE&&HIWORD(w)==CBN_SELCHANGE){
            if(!busy){LRESULT selected=SendMessageW(language_box,CB_GETCURSEL,0,0);if(selected==0||selected==1){language=(PrLanguage)selected;apply_language();}}return 0;
        }
        if(HIWORD(w)==BN_CLICKED){
            if(LOWORD(w)==ID_BROWSE&&!busy)choose_folder();
            else if(LOWORD(w)==ID_REFRESH&&!busy)status();
            else if(LOWORD(w)==ID_INSTALL)start_action(1);
            else if(LOWORD(w)==ID_RESTORE)start_action(2);
            else if(LOWORD(w)==ID_CLOSE&&!busy)DestroyWindow(h);
            return 0;
        }break;
    case WM_TIMER:if(w==1){KillTimer(h,1);status();return 0;}break;
    case MSG_LOG:append_entry((LogEntry*)l);return 0;
    case MSG_DONE:
        lock_controls(0);status();
        if(w)error_box(h,w==2?"Die automatische Rücknahme war unvollständig. Bitte das Protokoll und den Ordner playlist-resume-backup prüfen.":"Der Vorgang wurde nicht abgeschlossen. Der vorherige Stand wurde beibehalten oder wiederhergestellt. Details stehen im Protokoll.");
        return 0;
    case WM_SETCURSOR:if(busy){SetCursor(LoadCursorW(0,IDC_WAIT));return TRUE;}break;
    case WM_CLOSE:if(!busy)DestroyWindow(h);return 0;
    case WM_DESTROY:KillTimer(h,1);PostQuitMessage(0);return 0;
    }
    return DefWindowProcW(h,message,w,l);
}
void WinMainCRTStartup(void){
    instance=GetModuleHandleW(0);language=pr_default_language(GetUserDefaultUILanguage());
    HANDLE mutex=CreateMutexW(0,FALSE,L"Local\\PlaylistResumeSetup");
    if(mutex&&GetLastError()==ERROR_ALREADY_EXISTS){HWND other=FindWindowW(CLASS_NAME,0);if(other){ShowWindow(other,SW_RESTORE);SetForegroundWindow(other);}CloseHandle(mutex);ExitProcess(0);}
    platform=pr_alloc(sizeof *platform);if(!platform){MessageBoxW(0,language==PR_GERMAN?L"Nicht genügend Arbeitsspeicher.":L"Not enough memory.",L"PlaylistResume v1.0.1",MB_OK|MB_ICONERROR);ExitProcess(1);}
    SetProcessDPIAware();HDC screen=GetDC(0);if(screen){dpi=GetDeviceCaps(screen,LOGPIXELSY);ReleaseDC(0,screen);}if(dpi<96)dpi=96;
    font=CreateFontW(-MulDiv(9,dpi,72),0,0,0,FW_NORMAL,FALSE,FALSE,FALSE,DEFAULT_CHARSET,OUT_DEFAULT_PRECIS,CLIP_DEFAULT_PRECIS,DEFAULT_QUALITY,DEFAULT_PITCH,L"Segoe UI");
    WNDCLASSW cls;memset(&cls,0,sizeof cls);cls.lpfnWndProc=procedure;cls.hInstance=instance;cls.hCursor=LoadCursorW(0,IDC_ARROW);
    cls.hIcon=LoadIconW(0,IDI_APPLICATION);cls.hbrBackground=(HBRUSH)(COLOR_BTNFACE+1);cls.lpszClassName=CLASS_NAME;
    if(!RegisterClassW(&cls))ExitProcess(1);
    DWORD style=WS_OVERLAPPED|WS_CAPTION|WS_SYSMENU|WS_MINIMIZEBOX;
    RECT rect={0,0,scale(720),scale(564)};AdjustWindowRectEx(&rect,style,FALSE,WS_EX_CONTROLPARENT);
    RECT area;SystemParametersInfoW(SPI_GETWORKAREA,0,&area,0);
    int width=rect.right-rect.left,height=rect.bottom-rect.top;
    int x=area.left+(area.right-area.left-width)/2,y=area.top+(area.bottom-area.top-height)/2;
    if(x<area.left)x=area.left;if(y<area.top)y=area.top;
    window=CreateWindowExW(WS_EX_CONTROLPARENT,CLASS_NAME,L"PlaylistResume v1.0.1",style,x,y,width,height,0,0,instance,0);
    if(!window)ExitProcess(1);
    control(L"STATIC","PlaylistResume v1.0.1",0,18,16,410,24,0,0);
    control(L"STATIC","Sprache / Language",0,444,20,120,20,0,0);
    language_box=control(L"COMBOBOX","",WS_TABSTOP|WS_VSCROLL|CBS_DROPDOWNLIST,570,16,132,90,ID_LANGUAGE,0);
    SendMessageW(language_box,CB_ADDSTRING,0,(LPARAM)L"Deutsch");SendMessageW(language_box,CB_ADDSTRING,0,(LPARAM)L"English");
    SendMessageW(language_box,CB_SETCURSEL,(WPARAM)language,0);
    introduction=control(L"STATIC",INTRODUCTION,0,18,47,680,36,0,0);
    folder_group=control(L"BUTTON","Wallpaper-Engine-Ordner",BS_GROUPBOX,18,96,684,138,0,0);
    folder_help=control(L"STATIC",FOLDER_HELP,0,30,117,658,36,0,0);
    directory=control(L"EDIT","",WS_TABSTOP|ES_AUTOHSCROLL,30,159,548,24,ID_DIRECTORY,WS_EX_CLIENTEDGE);
    SendMessageW(directory,EM_SETLIMITTEXT,PR_PATH_CAP-16,0);
    browse=control(L"BUTTON","Durchsuchen …",WS_TABSTOP|BS_PUSHBUTTON,590,158,100,26,ID_BROWSE,0);
    pr_win_default(default_path);default_hint=control(L"STATIC","",0,30,193,658,31,0,0);default_text();
    status_group=control(L"BUTTON","Installationsstatus",BS_GROUPBOX,18,246,684,91,0,0);
    status_label=control(L"STATIC","Wird geprüft …",0,30,268,542,22,0,0);
    detail_label=control(L"STATIC","",0,30,296,658,30,0,0);
    refresh=control(L"BUTTON","Status prüfen",WS_TABSTOP|BS_PUSHBUTTON,590,265,100,27,ID_REFRESH,0);
    install=control(L"BUTTON","Installieren",WS_TABSTOP|BS_DEFPUSHBUTTON,18,354,160,32,ID_INSTALL,0);
    restore=control(L"BUTTON","Original wiederherstellen",WS_TABSTOP|BS_PUSHBUTTON,190,354,202,32,ID_RESTORE,0);
    close_button=control(L"BUTTON","Schließen",WS_TABSTOP|BS_PUSHBUTTON,590,354,112,32,ID_CLOSE,0);
    log_label=control(L"STATIC","Protokoll",0,18,404,684,18,0,0);
    log_box=control(L"EDIT","",WS_VSCROLL|ES_MULTILINE|ES_AUTOVSCROLL|ES_READONLY,18,427,684,94,0,WS_EX_CLIENTEDGE);
    SendMessageW(log_box,EM_SETLIMITTEXT,200000,0);
    footer=control(L"STATIC",FOOTER,0,18,536,684,18,0,0);
    HRESULT com=CoInitializeEx(0,COINIT_APARTMENTTHREADED);
    if(!pr_win_detect(input))pr_wcopy(input,PR_PATH_CAP,default_path);
    SetWindowTextW(directory,input);KillTimer(window,1);status();
    ShowWindow(window,SW_SHOWNORMAL);UpdateWindow(window);SetFocus(directory);
    MSG msg;int error=0;
    for(;;){BOOL result=GetMessageW(&msg,0,0,0);if(!result)break;if(result==-1){error=1;break;}if(!IsDialogMessageW(window,&msg)){TranslateMessage(&msg);DispatchMessageW(&msg);}}
    clear_log();if(SUCCEEDED(com))CoUninitialize();if(font)DeleteObject(font);pr_free(platform);if(mutex)CloseHandle(mutex);ExitProcess((UINT)error);
}

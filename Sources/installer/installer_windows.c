#include "installer_windows.h"
#include <tlhelp32.h>

/* Freestanding build: compiler aggregate copies may emit these calls. */
void *memcpy(void *dest,const void *src,size_t n){volatile unsigned char *d=dest;const volatile unsigned char *s=src;for(size_t i=0;i<n;i++)d[i]=s[i];return dest;}
void *memset(void *dest,int v,size_t n){volatile unsigned char *d=dest;for(size_t i=0;i<n;i++)d[i]=(unsigned char)v;return dest;}
void *memmove(void *dest,const void *src,size_t n){volatile unsigned char *d=dest;const volatile unsigned char *s=src;if(d<s){for(size_t i=0;i<n;i++)d[i]=s[i];}else{while(n){n--;d[n]=s[n];}}return dest;}
void *pr_alloc(size_t n){return HeapAlloc(GetProcessHeap(),HEAP_ZERO_MEMORY,n?n:1);}
void pr_free(void *p){if(p)HeapFree(GetProcessHeap(),0,p);}
size_t pr_wlength(const WCHAR *s){size_t n=0;while(s[n])n++;return n;}
int pr_wcopy(WCHAR *d,size_t capacity,const WCHAR *s){size_t n=pr_wlength(s);if(n>=capacity)return 0;for(size_t i=0;i<=n;i++)d[i]=s[i];return 1;}
int pr_wappend(WCHAR *d,size_t capacity,const WCHAR *s){size_t n=pr_wlength(d);return n<capacity&&pr_wcopy(d+n,capacity-n,s);}
WCHAR *pr_wide(const char *s){
    int n=MultiByteToWideChar(CP_UTF8,MB_ERR_INVALID_CHARS,s,-1,0,0);if(!n)return 0;
    WCHAR *out=pr_alloc((size_t)n*sizeof(WCHAR));if(!out)return 0;
    if(!MultiByteToWideChar(CP_UTF8,MB_ERR_INVALID_CHARS,s,-1,out,n)){pr_free(out);return 0;}return out;
}
static void note_error(PrWindows *w,const char *action,DWORD code){
    WCHAR description[512];char utf8[1024];description[0]=0;
    FormatMessageW(FORMAT_MESSAGE_FROM_SYSTEM|FORMAT_MESSAGE_IGNORE_INSERTS,0,code,0,description,512,0);
    int bytes=WideCharToMultiByte(CP_UTF8,0,description,-1,utf8,sizeof utf8,0,0);if(!bytes)utf8[0]=0;
    size_t n=0;while(action[n]&&n<500){w->error[n]=action[n];n++;}
    const char *middle=": ";for(unsigned i=0;middle[i]&&n<1535;i++)w->error[n++]=middle[i];
    for(unsigned i=0;utf8[i]&&n<1535;i++)if(utf8[i]!='\r'&&utf8[i]!='\n')w->error[n++]=utf8[i];
    w->error[n]=0;if(w->error_logger)w->error_logger(action,code);else if(w->logger)w->logger(w->error);
}
int pr_win_set_root(PrWindows *w,const WCHAR *source){
    size_t n=pr_wlength(source),start=0;while(start<n&&(source[start]==' '||source[start]=='\t'))start++;
    while(n>start&&(source[n-1]==' '||source[n-1]=='\t'))n--;
    if(n>start+1&&source[start]=='"'&&source[n-1]=='"'){start++;n--;}
    if(n-start>=PR_PATH_CAP||n==start)return 0;
    WCHAR *temp=pr_alloc((n-start+1)*sizeof(WCHAR));if(!temp)return 0;
    for(size_t i=start;i<n;i++)temp[i-start]=source[i]=='/'?'\\':source[i];temp[n-start]=0;
    DWORD written=GetFullPathNameW(temp,PR_PATH_CAP,w->root,0);pr_free(temp);
    if(!written||written>=PR_PATH_CAP){w->root[0]=0;return 0;}
    while(written>3&&w->root[written-1]=='\\')w->root[--written]=0;
    w->error[0]=0;return 1;
}
/* Return the first relative-path character. Only relative built-in names are
 * accepted by the core; the chosen root must already contain the application. */
static size_t path(PrWindows *w,WCHAR *out,const char *relative){
    out[0]=0;const WCHAR *root=w->root;
    if(root[0]=='\\'&&root[1]=='\\'&&root[2]=='?'&&root[3]=='\\'){}
    else if(root[0]=='\\'&&root[1]=='\\'){if(!pr_wcopy(out,PR_PATH_CAP,L"\\\\?\\UNC\\"))return 0;root+=2;}
    else if(!pr_wcopy(out,PR_PATH_CAP,L"\\\\?\\"))return 0;
    if(!pr_wappend(out,PR_PATH_CAP,root))return 0;
    size_t n=pr_wlength(out);if(n&&out[n-1]!='\\'){if(n+1>=PR_PATH_CAP)return 0;out[n++]='\\';}
    size_t start=n;
    for(size_t i=0;relative[i];i++){if(n+1>=PR_PATH_CAP)return 0;out[n++]=relative[i]=='/'?'\\':(unsigned char)relative[i];}
    out[n]=0;return start;
}
static int read_file(void *context,const char *relative,PrBuffer *out){
    PrWindows *w=context;out->data=0;out->size=0;out->exists=0;
    if(!path(w,w->path1,relative)){note_error(w,"Dateipfad zu lang",ERROR_FILENAME_EXCED_RANGE);return 0;}
    HANDLE file=CreateFileW(w->path1,GENERIC_READ,FILE_SHARE_READ|FILE_SHARE_WRITE|FILE_SHARE_DELETE,0,OPEN_EXISTING,FILE_ATTRIBUTE_NORMAL,0);
    if(file==INVALID_HANDLE_VALUE){DWORD error=GetLastError();if(error==ERROR_FILE_NOT_FOUND||error==ERROR_PATH_NOT_FOUND)return 1;note_error(w,"Lesen fehlgeschlagen",error);return 0;}
    LARGE_INTEGER size;if(!GetFileSizeEx(file,&size)||size.QuadPart<0||size.QuadPart>64*1024*1024){DWORD e=GetLastError();CloseHandle(file);note_error(w,"Ungültige Dateigröße",e?e:ERROR_FILE_TOO_LARGE);return 0;}
    unsigned char *data=pr_alloc(size.QuadPart?(size_t)size.QuadPart:1);
    if(!data){CloseHandle(file);note_error(w,"Nicht genügend Arbeitsspeicher",ERROR_NOT_ENOUGH_MEMORY);return 0;}
    size_t at=0;DWORD error=0;
    while(at<(size_t)size.QuadPart){DWORD n=0,want=(DWORD)((size_t)size.QuadPart-at);if(want>1048576)want=1048576;
        if(!ReadFile(file,data+at,want,&n,0)||!n){error=GetLastError();if(!error)error=ERROR_HANDLE_EOF;break;}at+=n;}
    CloseHandle(file);
    if(error){pr_free(data);note_error(w,"Datei konnte nicht vollständig gelesen werden",error);return 0;}
    out->data=data;out->size=at;out->exists=1;return 1;
}
static int write_file(void *context,const char *relative,const unsigned char *data,size_t size){
    PrWindows *w=context;size_t start=path(w,w->path1,relative);if(!start)return 0;
    for(size_t i=start;w->path1[i];i++)if(w->path1[i]=='\\'){
        w->path1[i]=0;
        if(!CreateDirectoryW(w->path1,0)){
            DWORD e=GetLastError(),attributes=GetFileAttributesW(w->path1);
            if(e!=ERROR_ALREADY_EXISTS||attributes==INVALID_FILE_ATTRIBUTES||!(attributes&FILE_ATTRIBUTE_DIRECTORY)){
                w->path1[i]='\\';note_error(w,"Sicherungsordner konnte nicht angelegt werden",e);return 0;
            }
        }
        w->path1[i]='\\';
    }
    HANDLE file=CreateFileW(w->path1,GENERIC_WRITE,0,0,CREATE_NEW,FILE_ATTRIBUTE_NORMAL,0);
    if(file==INVALID_HANDLE_VALUE){note_error(w,"Datei konnte nicht angelegt werden",GetLastError());return 0;}
    size_t at=0;DWORD error=0;
    while(at<size){DWORD n=0,want=(DWORD)(size-at);if(want>1048576)want=1048576;
        if(!WriteFile(file,data+at,want,&n,0)||!n){error=GetLastError();if(!error)error=ERROR_WRITE_FAULT;break;}at+=n;}
    if(!error&&!FlushFileBuffers(file))error=GetLastError();
    if(!CloseHandle(file)&&!error)error=GetLastError();
    if(error){DeleteFileW(w->path1);note_error(w,"Schreiben fehlgeschlagen",error);return 0;}return 1;
}
static int replace_file(void *context,const char *source,const char *target){
    PrWindows *w=context;if(!path(w,w->path1,source)||!path(w,w->path2,target))return 0;
    if(MoveFileExW(w->path1,w->path2,MOVEFILE_REPLACE_EXISTING|MOVEFILE_WRITE_THROUGH))return 1;
    note_error(w,"Dateitausch fehlgeschlagen",GetLastError());return 0;
}
static int remove_file(void *context,const char *relative){
    PrWindows *w=context;if(!path(w,w->path1,relative))return 0;
    if(DeleteFileW(w->path1))return 1;DWORD e=GetLastError();if(e==ERROR_FILE_NOT_FOUND||e==ERROR_PATH_NOT_FOUND)return 1;
    note_error(w,"Datei konnte nicht entfernt werden",e);return 0;
}
static int process_name(const WCHAR *a,const WCHAR *b){
    for(size_t i=0;;i++){WCHAR x=a[i],y=b[i];if(x>='A'&&x<='Z')x+=32;if(y>='A'&&y<='Z')y+=32;if(x!=y)return 0;if(!x)return 1;}
}
static int stopped(void *context){
    PrWindows *w=context;HANDLE snapshot=CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS,0);
    if(snapshot==INVALID_HANDLE_VALUE){note_error(w,"Prozessprüfung fehlgeschlagen",GetLastError());return 0;}
    PROCESSENTRY32W p;memset(&p,0,sizeof p);p.dwSize=sizeof p;
    if(!Process32FirstW(snapshot,&p)){DWORD e=GetLastError();CloseHandle(snapshot);note_error(w,"Prozessprüfung fehlgeschlagen",e);return 0;}
    do{
        if(process_name(p.szExeFile,L"wallpaper32.exe")||process_name(p.szExeFile,L"wallpaper64.exe")||process_name(p.szExeFile,L"wallpaperui.exe")){CloseHandle(snapshot);return 0;}
    }while(Process32NextW(snapshot,&p));
    DWORD e=GetLastError();CloseHandle(snapshot);if(e!=ERROR_NO_MORE_FILES){note_error(w,"Prozessprüfung fehlgeschlagen",e);return 0;}return 1;
}
static void log_line(void *context,const char *line){PrWindows *w=context;if(w->logger)w->logger(line);}
PrFS pr_win_fs(PrWindows *w){PrFS fs={w,read_file,write_file,replace_file,remove_file,stopped,log_line};return fs;}

static int registry(HKEY hive,REGSAM view,const WCHAR *name,WCHAR *out,DWORD capacity){
    HKEY key;if(RegOpenKeyExW(hive,L"Software\\Valve\\Steam",0,KEY_READ|view,&key)!=ERROR_SUCCESS)return 0;
    DWORD type=0,size=capacity*sizeof(WCHAR);LONG result=RegQueryValueExW(key,name,0,&type,(BYTE*)out,&size);RegCloseKey(key);
    if(result!=ERROR_SUCCESS||(type!=REG_SZ&&type!=REG_EXPAND_SZ)||size<sizeof(WCHAR)||size>capacity*sizeof(WCHAR))return 0;
    out[capacity-1]=0;return out[0]!=0;
}
static int is_engine(PrWindows *w,const WCHAR *candidate){
    if(!pr_win_set_root(w,candidate))return 0;
    const char *files[]={"wallpaper32.exe","wallpaper64.exe","ui/dist/scripts/scripts.js"};
    for(unsigned i=0;i<3;i++){
        if(!path(w,w->path1,files[i]))return 0;DWORD a=GetFileAttributesW(w->path1);
        if(a==INVALID_FILE_ATTRIBUTES||(a&FILE_ATTRIBUTE_DIRECTORY))return 0;
    }
    return 1;
}
void pr_win_default(WCHAR out[PR_PATH_CAP]){
    DWORD n=GetEnvironmentVariableW(L"ProgramFiles(x86)",out,PR_PATH_CAP);
    if(!n||n>=PR_PATH_CAP)n=GetEnvironmentVariableW(L"ProgramFiles",out,PR_PATH_CAP);
    if(!n||n>=PR_PATH_CAP)pr_wcopy(out,PR_PATH_CAP,L"C:\\Program Files (x86)");
    pr_wappend(out,PR_PATH_CAP,L"\\Steam\\steamapps\\common\\wallpaper_engine");
}
int pr_win_detect(WCHAR out[PR_PATH_CAP]){
    static WCHAR roots[8][2048],candidate[PR_PATH_CAP];static char library_paths[32][1024];
    unsigned count=0;PrWindows *w=pr_alloc(sizeof *w);if(!w)return 0;
    DWORD n=GetModuleFileNameW(0,candidate,PR_PATH_CAP);
    if(n&&n<PR_PATH_CAP){while(n&&candidate[n-1]!='\\'&&candidate[n-1]!='/')n--;if(n){candidate[n]=0;if(is_engine(w,candidate)){pr_wcopy(out,PR_PATH_CAP,w->root);pr_free(w);return 1;}}}
    if(registry(HKEY_CURRENT_USER,KEY_WOW64_32KEY,L"SteamPath",roots[count],2048))count++;
    if(registry(HKEY_CURRENT_USER,KEY_WOW64_64KEY,L"SteamPath",roots[count],2048))count++;
    if(registry(HKEY_LOCAL_MACHINE,KEY_WOW64_32KEY,L"InstallPath",roots[count],2048))count++;
    if(registry(HKEY_LOCAL_MACHINE,KEY_WOW64_64KEY,L"InstallPath",roots[count],2048))count++;
    for(unsigned i=0;i<2;i++){
        DWORD length=GetEnvironmentVariableW(i?L"ProgramFiles":L"ProgramFiles(x86)",roots[count],2048);
        if(length&&length<2000&&pr_wappend(roots[count],2048,L"\\Steam"))count++;
    }
    for(unsigned i=0;i<count;i++){
        pr_wcopy(candidate,PR_PATH_CAP,roots[i]);pr_wappend(candidate,PR_PATH_CAP,L"\\steamapps\\common\\wallpaper_engine");
        if(is_engine(w,candidate)){pr_wcopy(out,PR_PATH_CAP,w->root);pr_free(w);return 1;}
        if(!pr_win_set_root(w,roots[i]))continue;
        PrBuffer vdf={0};if(!read_file(w,"steamapps/libraryfolders.vdf",&vdf))continue;
        if(vdf.exists){
            int libraries=pr_vdf_paths(vdf.data,vdf.size,library_paths,32);
            for(int k=0;k<libraries;k++){
                WCHAR *library=pr_wide(library_paths[k]);if(!library)continue;
                int ok=pr_wcopy(candidate,PR_PATH_CAP,library)&&pr_wappend(candidate,PR_PATH_CAP,L"\\steamapps\\common\\wallpaper_engine");pr_free(library);
                if(ok&&is_engine(w,candidate)){pr_free(vdf.data);pr_wcopy(out,PR_PATH_CAP,w->root);pr_free(w);return 1;}
            }
        }
        if(vdf.data)pr_free(vdf.data);
    }
    pr_free(w);return 0;
}

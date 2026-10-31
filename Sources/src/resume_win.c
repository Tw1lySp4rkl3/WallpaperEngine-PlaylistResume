#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include "resume_core.h"
static volatile long gate;
static WCHAR state_path[32768],temporary_path[32768],trace_path[32768];
static unsigned path_ready;

/* Freestanding DLL: compiler-generated aggregate copies may call these. */
void *memcpy(void *dest,const void *src,size_t n) {
    volatile unsigned char *d=dest;const volatile unsigned char *s=src;
    for(size_t i=0;i<n;i++)d[i]=s[i];return dest;
}
void *memset(void *dest,int c,size_t n) {
    volatile unsigned char *d=dest;for(size_t i=0;i<n;i++)d[i]=(unsigned char)c;return dest;
}
void pirs_platform_lock(void) {
    while(__atomic_exchange_n(&gate,1,__ATOMIC_ACQUIRE))Sleep(0);
}
void pirs_platform_unlock(void){__atomic_store_n(&gate,0,__ATOMIC_RELEASE);}
static int suffix(WCHAR *dest,unsigned prefix,const WCHAR *tail) {
    unsigned i=0;while(tail[i]){if(prefix+i>=32767)return 0;dest[prefix+i]=tail[i];i++;}
    dest[prefix+i]=0;return 1;
}
static int paths(void) {
    if(path_ready)return path_ready==1;
    DWORD n=GetModuleFileNameW(0,state_path,32768);
    if(!n || n>=32768){path_ready=2;return 0;}
    while(n && state_path[n-1]!=L'\\' && state_path[n-1]!=L'/')n--;
    if(!n){path_ready=2;return 0;}
    for(unsigned i=0;i<n;i++){temporary_path[i]=state_path[i];trace_path[i]=state_path[i];}
    if(!suffix(state_path,n,L"bin\\playlist-resume.bin") ||
       !suffix(temporary_path,n,L"bin\\playlist-resume.tmp") ||
       !suffix(trace_path,n,L"bin\\playlist-resume.log")){path_ready=2;return 0;}
    path_ready=1;return 1;
}
int pirs_platform_read(unsigned char *out,unsigned capacity) {
    if(!paths())return -1;
    HANDLE f=CreateFileW(state_path,GENERIC_READ,FILE_SHARE_READ|FILE_SHARE_WRITE|FILE_SHARE_DELETE,0,OPEN_EXISTING,FILE_ATTRIBUTE_NORMAL,0);
    if(f==INVALID_HANDLE_VALUE)return GetLastError()==ERROR_FILE_NOT_FOUND?0:-1;
    LARGE_INTEGER size;DWORD read=0;
    int ok=GetFileSizeEx(f,&size) && size.QuadPart>=0 && size.QuadPart<=capacity &&
           ReadFile(f,out,(DWORD)size.QuadPart,&read,0) && read==(DWORD)size.QuadPart;
    CloseHandle(f);return ok?(int)read:-1;
}
int pirs_platform_write(const unsigned char *data,unsigned size) {
    if(!paths())return 0;
    HANDLE f=CreateFileW(temporary_path,GENERIC_WRITE,0,0,CREATE_ALWAYS,FILE_ATTRIBUTE_NORMAL,0);
    if(f==INVALID_HANDLE_VALUE)return 0;
    DWORD written=0;
    int ok=WriteFile(f,data,size,&written,0) && written==size && FlushFileBuffers(f);
    if(!CloseHandle(f))ok=0;
    if(ok)ok=MoveFileExW(temporary_path,state_path,MOVEFILE_REPLACE_EXISTING|MOVEFILE_WRITE_THROUGH);
    if(!ok)DeleteFileW(temporary_path);
    return ok;
}
static unsigned append(char *b,unsigned at,const char *s){while(*s && at<220)b[at++]=*s++;return at;}
static unsigned decimal(char *b,unsigned at,unsigned value) {
    char digits[10];unsigned n=0;do{digits[n++]=(char)('0'+value%10);value/=10;}while(value);
    while(n && at<220)b[at++]=digits[--n];return at;
}
void pirs_platform_trace(const char *event,uint64_t monitor,unsigned position,unsigned detail) {
    if(!paths())return;
    char line[224];unsigned n=append(line,0,event);n=append(line,n," monitor=");
    const char *hex="0123456789abcdef";
    for(unsigned i=0;i<16;i++)line[n++]=hex[(monitor>>(60-4*i))&15];
    n=append(line,n," position=");n=decimal(line,n,position);n=append(line,n," detail=");n=decimal(line,n,detail);
    line[n++]='\r';line[n++]='\n';
    HANDLE f=CreateFileW(trace_path,FILE_APPEND_DATA|GENERIC_READ,FILE_SHARE_READ,0,OPEN_ALWAYS,FILE_ATTRIBUTE_NORMAL,0);
    if(f==INVALID_HANDLE_VALUE)return;
    LARGE_INTEGER size;
    if(GetFileSizeEx(f,&size) && size.QuadPart>1048576) {
        CloseHandle(f);f=CreateFileW(trace_path,FILE_APPEND_DATA,FILE_SHARE_READ,0,CREATE_ALWAYS,FILE_ATTRIBUTE_NORMAL,0);
        if(f==INVALID_HANDLE_VALUE)return;
    }
    DWORD written;WriteFile(f,line,n,&written,0);CloseHandle(f);
}
BOOL WINAPI DllMain(HINSTANCE module,DWORD reason,LPVOID reserved) {
    (void)reserved;if(reason==DLL_PROCESS_ATTACH)DisableThreadLibraryCalls(module);return TRUE;
}

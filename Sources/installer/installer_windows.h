#ifndef PLAYLIST_RESUME_INSTALLER_WINDOWS_H
#define PLAYLIST_RESUME_INSTALLER_WINDOWS_H
#define WIN32_LEAN_AND_MEAN
#define UNICODE
#define _UNICODE
#include <windows.h>
#include "installer_core.h"
#define PR_PATH_CAP 32768
typedef struct {
    WCHAR root[PR_PATH_CAP],path1[PR_PATH_CAP],path2[PR_PATH_CAP];
    char error[1536];
    void (*logger)(const char *);
    /* Keep system error codes for rendering in either installer language. */
    void (*error_logger)(const char *,DWORD);
} PrWindows;
int pr_win_set_root(PrWindows *,const WCHAR *);
PrFS pr_win_fs(PrWindows *);
int pr_win_detect(WCHAR out[PR_PATH_CAP]);
void pr_win_default(WCHAR out[PR_PATH_CAP]);
size_t pr_wlength(const WCHAR *);
int pr_wcopy(WCHAR *,size_t,const WCHAR *);
int pr_wappend(WCHAR *,size_t,const WCHAR *);
WCHAR *pr_wide(const char *);
#endif

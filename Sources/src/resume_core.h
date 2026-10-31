#ifndef PIRS_RESUME_CORE_H
#define PIRS_RESUME_CORE_H
#include <stdint.h>
#include <stddef.h>
#ifdef _WIN32
#define PIRS_EXPORT __declspec(dllexport)
#else
#define PIRS_EXPORT __attribute__((visibility("default")))
#endif
#define PIRS_MAX_RECORDS 512
#define PIRS_DISK_MAX (16 + 32 * PIRS_MAX_RECORDS)
int pirs_platform_read(unsigned char *out, unsigned capacity);
int pirs_platform_write(const unsigned char *data, unsigned size);
void pirs_platform_trace(const char *event, uint64_t monitor, unsigned position, unsigned detail);
void pirs_platform_lock(void);
void pirs_platform_unlock(void);
PIRS_EXPORT void ResumePrepare(void *node, uintptr_t frame);
PIRS_EXPORT void ResumeCommit(uintptr_t frame, void *renderer);
#ifdef PIRS_TEST
PIRS_EXPORT void PirsResetForTest(void);
PIRS_EXPORT unsigned PirsRecordCountForTest(void);
#endif
#endif

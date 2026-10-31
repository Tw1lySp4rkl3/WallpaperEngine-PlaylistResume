/* Linux-only persistence seam for running exactly the same core in tests. */
#include "resume_core.h"
#include <string.h>
static unsigned char disk[PIRS_DISK_MAX];
static unsigned length,writes,fail_writes;
int pirs_platform_read(unsigned char *out,unsigned capacity){if(length>capacity)return -1;memcpy(out,disk,length);return (int)length;}
int pirs_platform_write(const unsigned char *data,unsigned size){writes++;if(fail_writes)return 0;if(size>sizeof(disk))return 0;memcpy(disk,data,size);length=size;return 1;}
void pirs_platform_trace(const char *a,uint64_t b,unsigned c,unsigned d){(void)a;(void)b;(void)c;(void)d;}
void pirs_platform_lock(void){}
void pirs_platform_unlock(void){}
PIRS_EXPORT void PirsClearDiskForTest(void){length=0;writes=0;fail_writes=0;memset(disk,0,sizeof(disk));}
PIRS_EXPORT unsigned PirsWriteCountForTest(void){return writes;}
PIRS_EXPORT unsigned PirsDiskForTest(unsigned char *out){memcpy(out,disk,length);return length;}
PIRS_EXPORT void PirsFailWritesForTest(unsigned fail){fail_writes=fail;}
PIRS_EXPORT void PirsCorruptDiskForTest(void){if(length)disk[length-1]^=1;}

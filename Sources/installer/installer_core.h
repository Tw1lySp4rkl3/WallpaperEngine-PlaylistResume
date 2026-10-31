#ifndef PLAYLIST_RESUME_INSTALLER_CORE_H
#define PLAYLIST_RESUME_INSTALLER_CORE_H
#include <stddef.h>
#include <stdint.h>

typedef struct { const unsigned char *data; size_t size; } PrSpan;
typedef struct { unsigned char *data; size_t size; int exists; } PrBuffer;
typedef struct { uint32_t offset; PrSpan before,after; } PrChange;
typedef struct { PrSpan before,after; } PrReplacement;
typedef struct {
    const char *filename;
    int kind; /* 0: PE recipe, 1: UTF-8 replacements, 2: newly supplied DLL */
    int release; /* 1 v1.0, 2 R04, 3 R03, 4 R02, 5 R01 */
    size_t original_size,patched_size;
    const unsigned char *original_hash,*patched_hash;
    const PrChange *changes; size_t change_count;
    const PrReplacement *replacements; size_t replacement_count;
    PrSpan append,contents;
} PrManifest;
typedef struct {
    int release,preview;
    const char *version;
    const PrManifest *const *files;
    size_t file_count;
    PrSpan receipt; /* Empty for releases predating installation receipts. */
} PrLegacyRelease;

/* Every read returns owned memory allocated with pr_alloc, including empty
 * existing files. A missing file is success with exists=0. No callback may
 * silently turn an access error into a missing file. */
typedef struct {
    void *context;
    int (*read)(void *,const char *,PrBuffer *);
    int (*write_new)(void *,const char *,const unsigned char *,size_t);
    int (*replace)(void *,const char *,const char *);
    int (*remove)(void *,const char *);
    int (*stopped)(void *);
    void (*log)(void *,const char *);
} PrFS;

typedef struct {
    int found,supported,can_install,can_restore;
    int version; /* 0: original, 1: v1.0, 2: R04, 3: R03, 4: R02, 5: R01, 6: partial */
    char label[256],detail[512];
} PrStatus;

void *pr_alloc(size_t);
void pr_free(void *);
void pr_hash(const unsigned char *,size_t,unsigned char out[32]);
int pr_transform(const PrBuffer *,const PrManifest *,int forward,PrBuffer *);
int pr_status(const PrFS *,PrStatus *);
/* action=1 install/update/repair, action=2 restore. Returns 0 success,
 * 1 failure with prior files retained/restored, 2 incomplete rollback. */
int pr_run(const PrFS *,int action);
int pr_vdf_paths(const unsigned char *,size_t,char paths[][1024],unsigned capacity);

extern const PrManifest *const pr_current[5];
extern const PrManifest *const pr_known[];
extern const size_t pr_known_count;
extern const PrLegacyRelease pr_legacy_releases[];
extern const size_t pr_legacy_release_count;
extern const char pr_project_version[];
extern const char *const pr_paths[7];
extern const unsigned char pr_receipt[];
extern const size_t pr_receipt_size;
#endif

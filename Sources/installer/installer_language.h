#ifndef PLAYLIST_RESUME_INSTALLER_LANGUAGE_H
#define PLAYLIST_RESUME_INSTALLER_LANGUAGE_H
#include <stddef.h>

typedef enum { PR_GERMAN=0, PR_ENGLISH=1 } PrLanguage;
/* German Windows display languages select German; all others select English. */
PrLanguage pr_default_language(unsigned windows_language_id);
/* Messages remain canonical German inside the unchanged installation core.
 * Translates exact text or documented message prefixes, preserving path tails.
 * Unknown text (e.g. filenames) passes through. No allocation or global state. */
int pr_localize(PrLanguage,const char *source,char *out,size_t capacity);
#endif

/* Linux test adapter only; not part of the Windows executable. */
#include <stdlib.h>
#include "installer_core.h"
static long outstanding;
void *pr_alloc(size_t n){void *p=malloc(n?n:1);if(p)outstanding++;return p;}
void pr_free(void *p){if(p){outstanding--;free(p);}}
long pr_test_allocations(void){return outstanding;}

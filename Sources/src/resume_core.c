/* WE 2.8.42: independent, per-monitor/list checkpoint storage.
 * No engine calls, allocation, hooks, threads or network operations here.
 * The two version-pinned EXE hooks supply the native object and call frame.
 */
#include "resume_core.h"
#if defined(PIRS_LAYOUT32) || UINTPTR_MAX == UINT32_MAX
#define PTR_BYTES 4
#define MONITOR_OFF 0x08
#define PLAYLIST_OFF 0x24
#define FLAGS_OFF 0x48
#define ORDER_OFF 0x40
#define MODE_OFF 0x44
#define INDEX_OFF 0x4c
#define TIME_OFF 0x50
#define FILE_OFF 0x68
#define FORCE_OFF 0x98
#define START_OFF 0x99
#define INTRO_OFF 0x9a
#define ITEM_SIZE 0x34
#define ITEM_PRESET 0x1c
#define RENDER_FILE 0x94
#define RENDER_PRESET 0xc4
#else
#define PTR_BYTES 8
#define MONITOR_OFF 0x10
#define PLAYLIST_OFF 0x38
#define FLAGS_OFF 0x74
#define ORDER_OFF 0x6c
#define MODE_OFF 0x70
#define INDEX_OFF 0x78
#define TIME_OFF 0x7c
#define FILE_OFF 0xa0
#define FORCE_OFF 0xe0
#define START_OFF 0xe1
#define INTRO_OFF 0xe2
#define ITEM_SIZE 0x48
#define ITEM_PRESET 0x28
#define RENDER_FILE 0xe0
#define RENDER_PRESET 0x120
#endif
#define INIT_FLAG 0x80u
#define INTRO_FLAG 0x40u
#define FEATURE_FLAGS 0x28u
#define REQUEST_FLAG 0x100u
#define REQUEST_MASK 0xffff0100u
#define MAX_SESSIONS 64
#define MAX_FRAMES 64

typedef struct { const unsigned char *data; uint32_t size; } Span;
typedef struct { uint64_t a,b; uint32_t count,index; uint64_t used; } Record;
typedef struct {
    uint64_t mon_a,mon_b,a,b;
    uintptr_t node;
    uint32_t expected_next, intro;
    unsigned valid;
} Session;
typedef struct {
    uintptr_t frame,node;
    uint64_t mon_a,mon_b,a,b;
    unsigned valid,manual;
} Frame;
typedef struct {
    uint64_t a,b,mon_a,mon_b;
    unsigned count;
    unsigned char *node,*items;
} Identity;
static struct {
    Record records[PIRS_MAX_RECORDS];
    Session sessions[MAX_SESSIONS];
    Frame frames[MAX_FRAMES];
    uint64_t sequence;
    unsigned count, loaded;
    unsigned char io[PIRS_DISK_MAX];
} state;

static uint32_t u32(const void *p) {
    const unsigned char *b=p;
    return (uint32_t)b[0] | (uint32_t)b[1]<<8 | (uint32_t)b[2]<<16 | (uint32_t)b[3]<<24;
}
static uint64_t u64(const void *p) {
    const unsigned char *b=p;
    return (uint64_t)u32(b) | (uint64_t)u32(b+4)<<32;
}
static uintptr_t pointer(const void *p) {
#if PTR_BYTES == 4
    return (uintptr_t)u32(p);
#else
    return (uintptr_t)u64(p);
#endif
}
static void put32(void *p,uint32_t v) {
    unsigned char *b=p;
    b[0]=(unsigned char)v;b[1]=(unsigned char)(v>>8);b[2]=(unsigned char)(v>>16);b[3]=(unsigned char)(v>>24);
}
static void put64(void *p,uint64_t v) { put32(p,(uint32_t)v);put32((unsigned char*)p+4,(uint32_t)(v>>32)); }
static int bytes_equal(const void *a,const void *b,unsigned n) {
    const unsigned char *x=a,*y=b;
    for(unsigned i=0;i<n;i++)if(x[i]!=y[i])return 0;
    return 1;
}
static int span(const void *object,Span *out) {
    const unsigned char *p=object;
    uintptr_t n=pointer(p+0x10),cap=pointer(p+0x10+PTR_BYTES);
    if(n>16384 || cap<n)return 0;
    out->data=cap<=15?p:(const unsigned char*)pointer(p);
    out->size=(uint32_t)n;
    return out->data!=0 || n==0;
}
static void clear_string(void *object) {
    unsigned char *p=object;
    Span s;
    if(!span(p,&s))return;
    if(s.data)((unsigned char*)s.data)[0]=0;
#if PTR_BYTES == 4
    put32(p+0x10,0);
#else
    put64(p+0x10,0);
#endif
}
static void hash_byte(uint64_t *a,uint64_t *b,unsigned char c) {
    *a=(*a^c)*UINT64_C(1099511628211);
    *b=(*b^c)*UINT64_C(14029467366897019727);
}
static void hash_span(uint64_t *a,uint64_t *b,Span s) {
    for(unsigned i=0;i<4;i++)hash_byte(a,b,(unsigned char)(s.size>>(i*8)));
    for(unsigned i=0;i<s.size;i++)hash_byte(a,b,s.data[i]);
}
static int identity(void *object,Identity *out) {
    unsigned char *n=object;
    if(!n || u32(n+MODE_OFF)!=1 || u32(n+ORDER_OFF)!=1 ||
       (u32(n+FLAGS_OFF)&FEATURE_FLAGS)!=FEATURE_FLAGS)return 0;
    uintptr_t begin=pointer(n+PLAYLIST_OFF),end=pointer(n+PLAYLIST_OFF+PTR_BYTES);
    if(!begin || end<begin || (end-begin)%ITEM_SIZE)return 0;
    uintptr_t count=(end-begin)/ITEM_SIZE;
    if(!count || count>32768)return 0;
    Span s;
    if(!span(n+MONITOR_OFF,&s) || !s.size || s.size>2048)return 0;
    out->mon_a=UINT64_C(14695981039346656037);
    out->mon_b=UINT64_C(7809847782465536322);
    hash_span(&out->mon_a,&out->mon_b,s);
    out->a=out->mon_a;out->b=out->mon_b;
    for(unsigned i=0;i<4;i++)hash_byte(&out->a,&out->b,(unsigned char)(count>>(i*8)));
    for(unsigned i=0;i<count;i++) {
        const unsigned char *item=(const unsigned char*)(begin+i*ITEM_SIZE);
        if(!span(item,&s))return 0;
        hash_span(&out->a,&out->b,s);
        if(!span(item+ITEM_PRESET,&s))return 0;
        hash_span(&out->a,&out->b,s);
    }
    out->node=n;out->items=(unsigned char*)begin;out->count=(unsigned)count;
    return 1;
}
static uint32_t crc32(const unsigned char *p,unsigned n) {
    uint32_t crc=~0u;
    for(unsigned i=0;i<n;i++) {
        crc^=p[i];
        for(unsigned j=0;j<8;j++)crc=(crc>>1)^(0xedb88320u&(0u-(crc&1)));
    }
    return ~crc;
}
static void load(void) {
    if(state.loaded)return;
    state.loaded=1;state.sequence=1;
    int size=pirs_platform_read(state.io,PIRS_DISK_MAX);
    if(size==0)return;
    unsigned count=size>=16?u32(state.io+8):PIRS_MAX_RECORDS+1;
    if(size<16 || count>PIRS_MAX_RECORDS || (unsigned)size!=16+count*32 ||
       (!bytes_equal(state.io,"WPRS0001",8) && !bytes_equal(state.io,"PIRS0003",8)) ||
       crc32(state.io+16,count*32)!=u32(state.io+12)) {
        pirs_platform_trace("invalid-state",0,0,0);return;
    }
    for(unsigned i=0;i<count;i++) {
        const unsigned char *p=state.io+16+i*32;
        Record r={u64(p),u64(p+8),u32(p+16),u32(p+20),u64(p+24)};
        if(!r.count || r.count>32768 || r.index>=r.count) {
            state.count=0;pirs_platform_trace("invalid-record",0,0,i);return;
        }
        state.records[i]=r;
        if(r.used>=state.sequence)state.sequence=r.used+1;
    }
    state.count=count;
}
static void save(void) {
    for(unsigned i=0;i<8;i++)state.io[i]=(unsigned char)"WPRS0001"[i];
    put32(state.io+8,state.count);
    for(unsigned i=0;i<state.count;i++) {
        unsigned char *p=state.io+16+i*32;Record *r=state.records+i;
        put64(p,r->a);put64(p+8,r->b);put32(p+16,r->count);put32(p+20,r->index);put64(p+24,r->used);
    }
    put32(state.io+12,crc32(state.io+16,state.count*32));
    if(!pirs_platform_write(state.io,16+state.count*32))pirs_platform_trace("write-failed",0,0,0);
}
static Record *record(Identity *id,int create) {
    for(unsigned i=0;i<state.count;i++)
        if(state.records[i].a==id->a && state.records[i].b==id->b && state.records[i].count==id->count)return state.records+i;
    if(!create)return 0;
    unsigned slot=state.count;
    if(slot<PIRS_MAX_RECORDS)state.count++;
    else {
        slot=0;
        for(unsigned i=1;i<PIRS_MAX_RECORDS;i++)if(state.records[i].used<state.records[slot].used)slot=i;
    }
    Record *r=state.records+slot;
    r->a=id->a;r->b=id->b;r->count=id->count;r->index=0;r->used=state.sequence++;
    return r;
}
static Session *session(Identity *id,int *first) {
    unsigned vacant=MAX_SESSIONS;
    for(unsigned i=0;i<MAX_SESSIONS;i++) {
        Session *s=state.sessions+i;
        if(s->valid && s->mon_a==id->mon_a && s->mon_b==id->mon_b){*first=0;return s;}
        if(!s->valid && vacant==MAX_SESSIONS)vacant=i;
    }
    if(vacant==MAX_SESSIONS)return 0;
    Session *s=state.sessions+vacant;
    s->valid=1;s->mon_a=id->mon_a;s->mon_b=id->mon_b;*first=1;
    return s;
}
static Frame *frame_slot(uintptr_t token,int create) {
    Frame *vacant=0;
    for(unsigned i=0;i<MAX_FRAMES;i++) {
        Frame *f=state.frames+i;
        if(f->valid && f->frame==token)return f;
        if(!f->valid && !vacant)vacant=f;
    }
    return create?vacant:0;
}
PIRS_EXPORT void ResumePrepare(void *object,uintptr_t token) {
    pirs_platform_lock();
    Frame *f=frame_slot(token,0);
    if(f)f->valid=0;
    Identity id;
    if(!identity(object,&id)){pirs_platform_unlock();return;}
    load();
    int first=0;
    Session *s=session(&id,&first);
    f=frame_slot(token,1);
    if(!s || !f){pirs_platform_unlock();return;}
    f->valid=1;f->frame=token;f->node=(uintptr_t)object;
    f->a=id.a;f->b=id.b;f->mon_a=id.mon_a;f->mon_b=id.mon_b;
    unsigned flags=u32(id.node+FLAGS_OFF),next=u32(id.node+INDEX_OFF);
    unsigned requested=(flags&REQUEST_FLAG)?flags>>16:0;
    f->manual=requested>0 && requested<=id.count;
    if(flags&REQUEST_FLAG) {
        flags&=~REQUEST_MASK;
        put32(id.node+FLAGS_OFF,flags);
    }
    if(f->manual) {
        /* A one-shot UI request overrides both profile restore and the prelude.
         * Only Commit may persist it, after the actual renderer matches. */
        next=requested-1;
        flags=(flags|INIT_FLAG)&~INTRO_FLAG;
        clear_string(id.node+FILE_OFF);
        id.node[FORCE_OFF]=0;id.node[START_OFF]=0;id.node[INTRO_OFF]=0;
        put32(id.node+INDEX_OFF,next);put32(id.node+FLAGS_OFF,flags);put32(id.node+TIME_OFF,0);
        s->node=(uintptr_t)object;s->a=id.a;s->b=id.b;s->expected_next=next;s->intro=0;
        pirs_platform_trace("manual-select",id.mon_a,requested,id.count);
        pirs_platform_unlock();return;
    }
    int activation=first || !(flags&INIT_FLAG) || s->node!=(uintptr_t)object || s->a!=id.a || s->b!=id.b ||
                   s->expected_next!=next || s->intro!=!!(flags&INTRO_FLAG);
    if(activation) {
        int continuing_intro=!first && s->intro && s->a==id.a && s->b==id.b;
        Record *r=record(&id,0);
        if(first && !r && next>0 && next<=id.count) {
            r=record(&id,1);r->index=next-1;r->used=state.sequence++;save();
        }
        clear_string(id.node+FILE_OFF);
        id.node[FORCE_OFF]=0;id.node[INTRO_OFF]=0;
        flags=(flags|INIT_FLAG)&~INTRO_FLAG;
        if((first || continuing_intro) && id.count>1) {
            next=r?r->index+1:0;
            id.node[START_OFF]=1;
            pirs_platform_trace(first?"startup":"intro-reapply",id.mon_a,r?r->index+1:0,id.count);
        } else {
            next=r?r->index:0;
            id.node[START_OFF]=0;
            pirs_platform_trace("activate",id.mon_a,r?r->index+1:0,id.count);
        }
        put32(id.node+INDEX_OFF,next);put32(id.node+FLAGS_OFF,flags);put32(id.node+TIME_OFF,0);
        s->node=(uintptr_t)object;s->a=id.a;s->b=id.b;s->expected_next=next;s->intro=0;
    }
    pirs_platform_unlock();
}
PIRS_EXPORT void ResumeCommit(uintptr_t token,void *renderer) {
    pirs_platform_lock();
    Frame *f=frame_slot(token,0);
    if(!f){pirs_platform_unlock();return;}
    Frame call=*f;f->valid=0;
    Identity id;
    if(!identity((void*)call.node,&id) || id.a!=call.a || id.b!=call.b){pirs_platform_unlock();return;}
    int first=0;Session *s=session(&id,&first);
    if(!s){pirs_platform_unlock();return;}
    s->expected_next=u32(id.node+INDEX_OFF);s->intro=!!(u32(id.node+FLAGS_OFF)&INTRO_FLAG);
    if(s->intro || !renderer){pirs_platform_unlock();return;}
    uint32_t next=s->expected_next;
    if(!next || next>id.count){pirs_platform_unlock();return;}
    unsigned index=next-1;
    unsigned char *item=id.items+index*ITEM_SIZE;
    Span file,preset,actual_file,actual_preset;
    if(!span(item,&file) || !span(item+ITEM_PRESET,&preset) ||
       !span((unsigned char*)renderer+RENDER_FILE,&actual_file) ||
       !span((unsigned char*)renderer+RENDER_PRESET,&actual_preset) ||
       file.size!=actual_file.size || preset.size!=actual_preset.size ||
       !bytes_equal(file.data,actual_file.data,file.size) || !bytes_equal(preset.data,actual_preset.data,preset.size)) {
        pirs_platform_trace("renderer-mismatch",id.mon_a,next,id.count);
        pirs_platform_unlock();return;
    }
    Record *r=record(&id,1);r->index=index;r->used=state.sequence++;
    save();pirs_platform_trace(call.manual?"manual-checkpoint":"checkpoint",id.mon_a,next,id.count);
    pirs_platform_unlock();
}
#ifdef PIRS_TEST
PIRS_EXPORT void PirsResetForTest(void) {
    unsigned char *p=(unsigned char*)&state;
    for(unsigned i=0;i<sizeof(state);i++)p[i]=0;
}
PIRS_EXPORT unsigned PirsRecordCountForTest(void){return state.count;}
#endif
